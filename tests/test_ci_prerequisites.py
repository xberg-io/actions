"""Exercise expected native failures and the Intel macOS CI tool lock."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]


def rejection_step():
    workflow = yaml.safe_load((ROOT / ".github/workflows/test-install-pester.yml").read_text())
    return next(
        step["run"]
        for step in workflow["jobs"]["test"]["steps"]
        if step.get("name") == "Reject versions that cannot be checksum-verified"
    )


def run_rejections(tmp_path, child_success):
    binary = shutil.which("pwsh")
    assert binary is not None, "PowerShell is required for the real exit-status regression"
    workspace = tmp_path / "workspace"
    script = workspace / "install-pester/scripts/install.ps1"
    script.parent.mkdir(parents=True)
    script.write_text(
        "Add-Content -LiteralPath $env:CALL_LOG -Value $env:INPUT_VERSION\n"
        + ("exit 0\n" if child_success else "exit 1\n")
    )
    parent = tmp_path / "parent.ps1"
    parent.write_text(
        rejection_step() + "\nif (Test-Path -LiteralPath variable:\\LASTEXITCODE) { exit $LASTEXITCODE }\n"
    )
    return subprocess.run(
        [binary, "-NoProfile", "-NonInteractive", "-File", str(parent)],
        env={
            **os.environ,
            "CALL_LOG": str(tmp_path / "calls.txt"),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_WORKSPACE": str(workspace),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_expected_child_failures_do_not_fail_the_github_powershell_step(tmp_path):
    result = run_rejections(tmp_path, False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "calls.txt").read_text().splitlines() == ["latest", "6.9.9", "1.2.3.4", "1.2.3;rm", "../../etc"]


def test_unexpected_child_success_still_fails_the_github_powershell_step(tmp_path):
    result = run_rejections(tmp_path, True)
    assert result.returncode == 1
    assert (tmp_path / "calls.txt").read_text().splitlines() == ["latest"]
    assert "expected install-pester to reject version" in result.stderr


def test_intel_macos_chromium_has_locked_node_and_pnpm():
    mise = tomllib.loads((ROOT / "mise.toml").read_text())
    lock = tomllib.loads((ROOT / "mise.lock").read_text())
    workflow = yaml.safe_load((ROOT / ".github/workflows/test-setup-chromium.yml").read_text())
    assert "macos-26-intel" in workflow["jobs"]["test"]["strategy"]["matrix"]["os"]
    assert "macos-x64" in mise["settings"]["lockfile_platforms"]
    for name in ("node", "pnpm"):
        records = [row for row in lock["tools"][name] if row["version"] == mise["tools"][name]]
        assert len(records) == 1
        assert "platforms.macos-x64" in records[0]


@pytest.mark.parametrize(
    "name", ["test-build-node-napi", "test-setup-mise", "test-install-pester", "test-setup-chromium"]
)
def test_prerequisite_workflows_can_run_the_current_ref_manually(name):
    workflow = yaml.load((ROOT / f".github/workflows/{name}.yml").read_text(), Loader=yaml.BaseLoader)
    assert "workflow_dispatch" in workflow["on"]
    assert "push" in workflow["on"]
    assert "pull_request" in workflow["on"]
