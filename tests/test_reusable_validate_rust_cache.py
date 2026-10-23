"""Exercise the reusable workflow's cache input through the Rust setup script."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]


def _rust_environment(tmp_path: Path, requested: bool | None) -> dict[str, str]:
    workflow = yaml.safe_load((_ROOT / ".github/workflows/reusable-validate.yml").read_text())
    action = yaml.safe_load((_ROOT / "setup-rust/action.yml").read_text())
    setups = [step for step in workflow["jobs"]["validate"]["steps"] if step.get("name") == "Set up Rust"]
    assert len(setups) == 1
    value = setups[0]["with"].get("use-sccache", action["inputs"]["use-sccache"]["default"])
    if value == "${{ inputs.rust-use-sccache }}":
        default = workflow[True]["workflow_call"]["inputs"]["rust-use-sccache"]["default"]
        value = default if requested is None else requested
    steps = [step for step in action["runs"]["steps"] if step.get("name") == "Configure Rust flags"]
    assert len(steps) == 1
    assert steps[0]["env"]["RUST_USE_SCCACHE"] == "${{ inputs.use-sccache }}"
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, body in {"rustc": "", "sccache": 'print("test sccache")'}.items():
        executable = tools / name
        executable.write_text(f"#!{sys.executable}\n{body}\n")
        executable.chmod(0o755)
    output = tmp_path / "github-env"
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", steps[0]["run"]],
        env={
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_ACTION_PATH": str(_ROOT / "setup-rust"),
            "GITHUB_ENV": str(output),
            "RUST_USE_SCCACHE": str(value).lower(),
            "RUST_MACOS_DYNAMIC_LOOKUP": "false",
            "RUSTFLAGS": "",
        },
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in output.read_text().splitlines())


def test_rust_cache_input_defaults_to_the_existing_enabled_behavior() -> None:
    workflow = yaml.safe_load((_ROOT / ".github/workflows/reusable-validate.yml").read_text())
    cache = workflow[True]["workflow_call"]["inputs"]["rust-use-sccache"]
    assert cache["type"] == "boolean"
    assert cache["required"] is False
    assert cache["default"] is True


@pytest.mark.parametrize("requested", [None, True, False], ids=["default", "enabled", "disabled"])
def test_rust_cache_selection_reaches_compiler_environment(tmp_path: Path, requested: bool | None) -> None:
    environment = _rust_environment(tmp_path, requested)
    enabled = requested is not False
    assert environment["SCCACHE_GHA_ENABLED"] == str(enabled).lower()
    assert environment["RUSTC_WRAPPER"] == ("sccache" if enabled else "")
    assert environment["RUSTFLAGS"] == (
        "-D warnings -A unpredictable-function-pointer-comparisons -A mismatched-lifetime-syntaxes "
        "-A fn_ptr_eq --cfg has_fn_ptr_eq_lint"
    )
