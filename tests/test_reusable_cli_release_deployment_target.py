"""The reusable CLI release forwards a macOS deployment target to the macOS build legs only."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github/workflows/reusable-cli-release.yml"
_STEP = "Export macOS deployment target"
_MATRIX_JOBS = ["cli-binaries", "cli-binaries-extra"]


def _workflow() -> dict[Any, Any]:
    return yaml.safe_load(_WORKFLOW.read_text())


def _steps(job: str) -> list[dict[str, Any]]:
    return _workflow()["jobs"][job]["steps"]


def _export_step(job: str) -> dict[str, Any]:
    matches = [step for step in _steps(job) if step.get("name") == _STEP]
    assert len(matches) == 1
    return matches[0]


def _run_export(tmp_path: Path, job: str, requested: str, runner_os: str) -> subprocess.CompletedProcess[str]:
    step = _export_step(job)
    assert step["env"]["MACOS_DEPLOYMENT_TARGET"] == "${{ inputs.macos-deployment-target }}"
    assert "${{" not in step["run"]
    bash = shutil.which("bash")
    assert bash is not None
    output = tmp_path / "github-env"
    output.touch()
    return subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", step["run"]],
        env={
            **os.environ,
            "GITHUB_ENV": str(output),
            "RUNNER_OS": runner_os,
            "MACOS_DEPLOYMENT_TARGET": requested,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_input_is_optional_and_defaults_to_the_toolchain_default() -> None:
    target = _workflow()[True]["workflow_call"]["inputs"]["macos-deployment-target"]
    assert target["type"] == "string"
    assert target["required"] is False
    assert target["default"] == ""


@pytest.mark.parametrize("job", _MATRIX_JOBS)
def test_export_runs_before_the_build_and_only_when_requested(job: str) -> None:
    names = [step.get("name") or step.get("uses", "") for step in _steps(job)]
    build = next(i for i, name in enumerate(names) if "build-rust-cli@" in name)
    assert names.index(_STEP) < build
    assert _export_step(job)["if"] == "${{ inputs.macos-deployment-target != '' }}"


def test_matrix_jobs_share_one_export_step() -> None:
    assert _export_step("cli-binaries") == _export_step("cli-binaries-extra")


def test_musl_job_never_exports_a_deployment_target() -> None:
    assert _STEP not in [step.get("name") for step in _steps("cli-binaries-musl")]


@pytest.mark.parametrize("job", _MATRIX_JOBS)
@pytest.mark.parametrize("requested", ["26.0", "11.0", "26.10"])
def test_macos_leg_exports_the_requested_target(tmp_path: Path, job: str, requested: str) -> None:
    result = _run_export(tmp_path, job, requested, "macOS")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-env").read_text() == f"MACOSX_DEPLOYMENT_TARGET={requested}\n"


@pytest.mark.parametrize("job", _MATRIX_JOBS)
@pytest.mark.parametrize("runner_os", ["Linux", "Windows"])
def test_non_macos_leg_leaves_the_environment_unset(tmp_path: Path, job: str, runner_os: str) -> None:
    result = _run_export(tmp_path, job, "26.0", runner_os)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-env").read_text() == ""


@pytest.mark.parametrize("job", _MATRIX_JOBS)
@pytest.mark.parametrize("runner_os", ["macOS", "Linux"])
@pytest.mark.parametrize("requested", ["26", "26.0.1", "v26.0", "26.0\nRUSTFLAGS=x", "26.0 ", "latest"])
def test_malformed_target_fails_on_every_leg(tmp_path: Path, job: str, runner_os: str, requested: str) -> None:
    result = _run_export(tmp_path, job, requested, runner_os)
    assert result.returncode != 0
    assert "macos-deployment-target" in result.stderr
    assert (tmp_path / "github-env").read_text() == ""
