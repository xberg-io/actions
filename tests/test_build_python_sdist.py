"""Wiring tests for the build-python-sdist action. The actual rewrite is alef's
(tested there) and maturin's; here we assert the action installs the rewrite +
runs maturin in both package-dir and manifest-path modes."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    path = _ROOT / "build-python-sdist" / "action.yml"
    assert path.is_file(), f"missing {path}"
    return path.read_text()


def test_runs_rewrite_then_maturin():
    content = _read()
    assert "uses: kreuzberg-dev/actions/rewrite-native-deps@v1" in content
    assert "lang: python" in content
    # Sdist build is delegated to the out-of-workspace helper so the
    # path-rewrite + maturin invocation can share a single staging dir.
    assert "scripts/build-out-of-workspace.sh" in content


def test_rewrite_is_opt_outable_and_default_on():
    content = _read()
    assert "rewrite-native-deps:" in content
    assert "if: inputs.rewrite-native-deps == 'true'" in content
    assert 'default: "true"' in content


def test_supports_both_package_dir_and_manifest_path_modes():
    content = _read()
    # The action passes either INPUT_MANIFEST_PATH or INPUT_PACKAGE_DIR to
    # build-out-of-workspace.sh via shell-default substitution, letting the
    # helper handle both layouts uniformly.
    assert 'input_path="${INPUT_MANIFEST_PATH:-${INPUT_PACKAGE_DIR}}"' in content


def test_output_dir_resolved_under_workspace():
    content = _read()
    assert 'out="${GITHUB_WORKSPACE}/${INPUT_OUTPUT_DIR}"' in content
