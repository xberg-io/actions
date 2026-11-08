"""The reusable CLI release ships each `binary-aliases` name next to the binary in every archive."""

import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github/workflows/reusable-cli-release.yml"
_STEP = "Package CLI artifact"
_JOBS = {
    "cli-binaries": "x86_64-unknown-linux-gnu",
    "cli-binaries-extra": "aarch64-unknown-linux-gnu",
    "cli-binaries-musl": "x86_64-unknown-linux-musl",
}


def _workflow() -> dict[Any, Any]:
    return yaml.safe_load(_WORKFLOW.read_text())


def _package_step(job: str) -> dict[str, Any]:
    matches = [step for step in _workflow()["jobs"][job]["steps"] if step.get("name") == _STEP]
    assert len(matches) == 1
    return matches[0]


def _package(tmp_path: Path, job: str, aliases: str) -> subprocess.CompletedProcess[str]:
    step = _package_step(job)
    assert step["env"]["BINARY_ALIASES"] == "${{ inputs.binary-aliases }}"
    assert "${{" not in step["run"]
    binary = tmp_path / "build" / "tool"
    binary.parent.mkdir()
    binary.write_bytes(b"\x7fELF fake binary")
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "RUNNER_OS": "Linux",
            "BINARY_PATH": str(binary),
            "TARGET": _JOBS[job],
            "BINARY_NAME": "html-to-markdown",
            "BINARY_ALIASES": aliases,
            "ASSET_PREFIX": "cli-",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _members(tmp_path: Path, job: str) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(tmp_path / f"cli-{_JOBS[job]}.tar.gz") as archive:
        return {Path(member.name).name: member for member in archive.getmembers()}


def _content(tmp_path: Path, job: str, name: str) -> bytes:
    with tarfile.open(tmp_path / f"cli-{_JOBS[job]}.tar.gz") as archive:
        member = next(m for m in archive.getmembers() if Path(m.name).name == name)
        extracted = archive.extractfile(member)
        assert extracted is not None
        return extracted.read()


def test_input_is_optional_and_empty_by_default() -> None:
    aliases = _workflow()[True]["workflow_call"]["inputs"]["binary-aliases"]
    assert aliases["type"] == "string"
    assert aliases["required"] is False
    assert aliases["default"] == ""


@pytest.mark.parametrize("job", list(_JOBS))
def test_alias_ships_as_a_regular_copy_of_the_binary(tmp_path: Path, job: str) -> None:
    result = _package(tmp_path, job, "h2m")
    assert result.returncode == 0, result.stderr
    members = _members(tmp_path, job)
    assert members["html-to-markdown"].isfile()
    assert members["h2m"].isfile()
    assert _content(tmp_path, job, "h2m") == _content(tmp_path, job, "html-to-markdown") == b"\x7fELF fake binary"


@pytest.mark.parametrize("job", list(_JOBS))
def test_no_aliases_ships_only_the_binary(tmp_path: Path, job: str) -> None:
    result = _package(tmp_path, job, "")
    assert result.returncode == 0, result.stderr
    assert sorted(name for name in _members(tmp_path, job) if name.startswith(("html", "h2m"))) == ["html-to-markdown"]


@pytest.mark.parametrize("job", list(_JOBS))
def test_alias_with_a_path_separator_is_rejected(tmp_path: Path, job: str) -> None:
    result = _package(tmp_path, job, "../evil")
    assert result.returncode != 0
    assert "invalid binary alias" in result.stdout
    assert not (tmp_path / f"cli-{_JOBS[job]}.tar.gz").exists()


@pytest.mark.parametrize("job", ["cli-binaries", "cli-binaries-extra"])
def test_windows_legs_copy_each_alias_as_an_exe(job: str) -> None:
    assert 'cp "$BINARY_PATH" "$STAGE/${alias}.exe"' in _package_step(job)["run"]
