"""Wiring tests for the rewrite-native-deps action and its embedding in the
source-build actions. The heavy lifting (the actual path->version rewrite) lives
in the alef CLI and is tested there; here we only assert the action surface and
that each source-build action invokes the rewrite for the correct language."""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _read(action_dir: str) -> str:
    path = _ROOT / action_dir / "action.yml"
    assert path.is_file(), f"missing {path}"
    return path.read_text()


def test_rewrite_action_installs_alef_then_runs_publish_prepare():
    content = _read("rewrite-native-deps")
    assert "uses: xberg-io/actions/install-alef@v1" in content
    assert "publish prepare --lang" in content
    assert "--require-registry" in content


def test_rewrite_action_exposes_expected_inputs():
    content = _read("rewrite-native-deps")
    for field in ("lang:", "alef-version:", "require-registry:", "working-directory:"):
        assert field in content, f"missing input {field}"


def test_rewrite_action_require_registry_is_conditional():
    content = _read("rewrite-native-deps")
    assert 'if [ "${INPUT_REQUIRE_REGISTRY}" = "true" ]; then' in content


def test_rewrite_action_validates_lang_charset():
    content = _read("rewrite-native-deps")
    assert "=~ ^[a-z]+(,[a-z]+)*$" in content


def test_rewrite_action_runs_at_repo_root_by_default():
    content = _read("rewrite-native-deps")
    assert 'default: "."' in content


@pytest.mark.parametrize(
    ("action_dir", "lang"),
    [
        ("build-ruby-gem", "ruby"),
        ("build-php-extension", "php"),
        ("build-elixir-natives", "elixir"),
        ("build-python-sdist", "python"),
    ],
)
def test_source_build_action_embeds_rewrite(action_dir: str, lang: str):
    content = _read(action_dir)
    assert "uses: xberg-io/actions/rewrite-native-deps@v1" in content
    assert f"lang: {lang}" in content
    assert "rewrite-native-deps:" in content
    assert "if: inputs.rewrite-native-deps == 'true'" in content


@pytest.mark.parametrize(
    "action_dir",
    [
        "build-elixir-natives",
        "build-elixir-hex",
        "build-php-extension",
        "build-python-sdist",
        "build-ruby-gem",
    ],
)
def test_source_build_action_skips_rewrite_on_dry_run(action_dir: str):
    content = _read(action_dir)
    assert "dry-run:" in content
    assert "if: inputs.rewrite-native-deps == 'true' && inputs.dry-run != 'true'" in content
