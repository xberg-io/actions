"""setup-mise runs inside the Debian container that release builds use, and installs the locked Go."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "setup-mise/tests/fixtures/container"


def _job():
    workflow = yaml.safe_load((ROOT / ".github/workflows/test-setup-mise.yml").read_text())
    return workflow["jobs"]["container"]


def _step(name):
    return next(step for step in _job()["steps"] if step.get("name") == name)


def test_container_job_runs_setup_mise_with_go_in_debian_on_both_linux_arches():
    job = _job()
    assert job["container"] == "debian:bookworm"
    assert job["runs-on"] == "${{ matrix.os }}"
    assert job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "ubuntu-24.04-arm"]
    names = [step.get("name", step.get("uses")) for step in job["steps"]]
    assert names.index("Install the container prerequisites") < names.index("actions/checkout@v7")
    preamble = _step("Install the container prerequisites")["run"]
    assert "apt-get install -y --no-install-recommends curl ca-certificates git" in preamble
    setup = _step("Setup mise with Go")
    assert setup["uses"] == "./setup-mise"
    assert setup["with"] == {
        "working-directory": "setup-mise/tests/fixtures/container",
        "tools": "go",
        "cache": "false",
    }


def test_container_fixture_locks_its_go_for_both_linux_arches():
    config = (FIXTURE / "mise.toml").read_text()
    lock = (FIXTURE / "mise.lock").read_text()
    assert 'go = "1.27.3"' in config
    assert '[[tools.go]]\nversion = "1.27.3"\nbackend = "core:go"' in lock
    for platform in ("linux-x64", "linux-arm64"):
        assert f'[tools.go."platforms.{platform}"]\nchecksum = "sha256:' in lock


@pytest.fixture
def verify(tmp_path):
    shutil.copy(FIXTURE / "mise.lock", tmp_path / "mise.lock")
    install = tmp_path / "installs/go/bin"
    install.mkdir(parents=True)
    go = install / "go"
    go.write_text(f"#!{sys.executable}\nimport os\nprint(os.environ['GO_OUTPUT'])\n")
    go.chmod(0o755)
    mise = tmp_path / "mise"
    mise.write_text(f"#!/bin/sh\necho {tmp_path / 'installs/go'}\n")
    mise.chmod(0o755)

    def run(go_output, locked="1"):
        environment = {
            **os.environ,
            "PATH": f"{install}{os.pathsep}{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "GO_OUTPUT": go_output,
            "MISE_LOCKED": locked,
        }
        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", _step("Verify Go matches the lock")["run"]],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    return tmp_path, run


def test_verify_step_accepts_the_locked_go(verify):
    _, run = verify
    result = run("go version go1.27.3 linux/arm64")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "go: go version go1.27.3 linux/arm64 (locked 1.27.3)" in result.stdout


@pytest.mark.parametrize(
    "go_output",
    ["go version go1.27.2 linux/amd64", "go version go1.27.3 darwin/arm64", ""],
    ids=["other-version", "not-linux", "no-output"],
)
def test_verify_step_rejects_a_go_the_lock_does_not_select(verify, go_output):
    _, run = verify
    assert run(go_output).returncode != 0


def test_verify_step_rejects_an_unlocked_install(verify):
    _, run = verify
    assert run("go version go1.27.3 linux/amd64", locked="").returncode != 0


def test_verify_step_rejects_a_lock_without_go(verify):
    tmp_path, run = verify
    (tmp_path / "mise.lock").write_text('lockfile_version = 3\n\n[[tools.jq]]\nversion = "1.8.2"\n')
    result = run("go version go1.8.2 linux/amd64")
    assert result.returncode != 0
    assert "mise.lock locks no Go version" in result.stdout
