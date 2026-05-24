"""Unit tests for publish-homebrew-source-formulas/scripts/render.py."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "publish-homebrew-source-formulas" / "scripts" / "render.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("render_homebrew", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_action_yml_calls_render_script() -> None:
    action = (_ROOT / "publish-homebrew-source-formulas" / "action.yml").read_text()
    assert "python3" in action
    assert "scripts/render.py" in action
    assert "ensure-gh@v1" in action
    assert "dry-run:" in action


def test_zero_sha_constant_is_64_hex_zeros() -> None:
    mod = _load_module()
    assert mod.ZERO_SHA == "0" * 64
    assert len(mod.ZERO_SHA) == 64


def test_interpolate_asset_name_substitutes_tag_and_version() -> None:
    mod = _load_module()
    out = mod._interpolate_asset_name(
        "html-to-markdown-rs-ffi-${tag}-aarch64-apple-darwin.tar.gz",
        tag="v3.5.0-rc.2",
        version="3.5.0-rc.2",
    )
    assert out == "html-to-markdown-rs-ffi-v3.5.0-rc.2-aarch64-apple-darwin.tar.gz"


def test_interpolate_passes_through_literal_filenames() -> None:
    mod = _load_module()
    out = mod._interpolate_asset_name("cli-aarch64-apple-darwin.tar.gz", tag="v1.2.3", version="1.2.3")
    assert out == "cli-aarch64-apple-darwin.tar.gz"


def test_compute_sha256_matches_hashlib(tmp_path: Path) -> None:
    mod = _load_module()
    p = tmp_path / "asset"
    payload = b"hello homebrew"
    p.write_bytes(payload)
    assert mod._compute_sha256(p) == hashlib.sha256(payload).hexdigest()


def test_render_template_substitutes_all_keys(tmp_path: Path) -> None:
    mod = _load_module()
    tmpl = tmp_path / "f.rb.tmpl"
    tmpl.write_text("version=${version} tag=${tag} sha=${cli_sha}")
    out = mod._render_template(tmpl, {"version": "1.0.0", "tag": "v1.0.0", "cli_sha": "abc"})
    assert out == "version=1.0.0 tag=v1.0.0 sha=abc"


def test_render_template_raises_on_undefined_placeholder(tmp_path: Path) -> None:
    mod = _load_module()
    tmpl = tmp_path / "f.rb.tmpl"
    tmpl.write_text("${missing}")
    with pytest.raises(KeyError):
        mod._render_template(tmpl, {})


def test_main_writes_formulas_with_zero_sha_on_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()
    tap = tmp_path / "tap"
    (tap / "Formula").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    template = repo / "tmpl.rb.tmpl"
    template.write_text('version "${version}" sha "${cli_sha}"')
    config = repo / "homebrew.json"
    config.write_text(
        '{"formulas":[{"name":"testpkg","template":"' + template.name + '","assets":{"cli_sha":"cli-x86_64.tar.gz"}}]}'
    )

    def _fail_download(*_args, **_kwargs):
        return None

    monkeypatch.setattr(mod, "_download_asset", _fail_download)
    monkeypatch.setenv("INPUT_TAP_DIR", str(tap))
    monkeypatch.setenv("INPUT_CONFIG_FILE", str(config))
    monkeypatch.setenv("INPUT_TAG", "v9.9.9-dryrun")
    monkeypatch.setenv("INPUT_VERSION", "9.9.9-dryrun")
    monkeypatch.setenv("INPUT_GITHUB_REPO", "example/repo")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))
    out_file = tmp_path / "out"
    out_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))

    assert mod.main() == 0

    rendered = (tap / "Formula" / "testpkg.rb").read_text()
    assert 'version "9.9.9-dryrun"' in rendered
    assert f'sha "{mod.ZERO_SHA}"' in rendered
    assert "formulas-changed<<EOF" in out_file.read_text()


def test_main_fails_when_asset_missing_and_not_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_module()
    tap = tmp_path / "tap"
    (tap / "Formula").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    template = repo / "tmpl.rb.tmpl"
    template.write_text("${cli_sha}")
    config = repo / "homebrew.json"
    config.write_text(
        '{"formulas":[{"name":"testpkg","template":"' + template.name + '","assets":{"cli_sha":"cli-x86_64.tar.gz"}}]}'
    )

    monkeypatch.setattr(mod, "_download_asset", lambda *a, **kw: None)
    monkeypatch.setenv("INPUT_TAP_DIR", str(tap))
    monkeypatch.setenv("INPUT_CONFIG_FILE", str(config))
    monkeypatch.setenv("INPUT_TAG", "v1.0.0")
    monkeypatch.setenv("INPUT_VERSION", "1.0.0")
    monkeypatch.setenv("INPUT_GITHUB_REPO", "example/repo")
    monkeypatch.setenv("INPUT_DRY_RUN", "false")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "could not fetch" in err


def test_main_rejects_missing_tap_formula_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    config = repo / "homebrew.json"
    config.write_text('{"formulas": []}')

    monkeypatch.setenv("INPUT_TAP_DIR", str(tmp_path / "missing-tap"))
    monkeypatch.setenv("INPUT_CONFIG_FILE", str(config))
    monkeypatch.setenv("INPUT_TAG", "v1.0.0")
    monkeypatch.setenv("INPUT_VERSION", "1.0.0")
    monkeypatch.setenv("INPUT_GITHUB_REPO", "example/repo")
    monkeypatch.setenv("INPUT_DRY_RUN", "false")

    assert mod.main() == 1
