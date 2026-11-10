"""Run the publisher's actual install step in artifact-only and source-checkout layouts."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _write_mise_stub(directory: Path) -> Path:
    stub = directory / "mise"
    stub.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\ncase "$1" in\n'
        'current) exec "$REAL_MISE" "$@" ;;\n'
        'install) printf "%s|%s|%s\\n" "$PWD" "${MISE_LOCKED:-}" "$*" >>"$INSTALL_TRACE" ;;\n'
        'bin-paths) printf "/selected/%s/bin\\n" "$2" ;;\n'
        "*) exit 64 ;;\nesac\n"
    )
    stub.chmod(0o755)
    return stub


@pytest.fixture
def artifact_job(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    real_mise = shutil.which("mise")
    assert real_mise, "mise is required to verify actual config discovery"
    caller = tmp_path / "caller"
    caller.mkdir()
    artifacts = caller / "dist"
    artifacts.mkdir()
    (artifacts / "liter_llm-2.4.4-py3-none-any.whl").write_bytes(b"artifact placeholder")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_mise_stub(bin_dir)
    trace = tmp_path / "install.log"
    env = {key: value for key, value in os.environ.items() if not key.startswith("MISE_")}
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        REAL_MISE=real_mise,
        INSTALL_TRACE=str(trace),
        GITHUB_ACTION_PATH=str(ROOT / "publish-pypi"),
        GITHUB_PATH=str(tmp_path / "github_path"),
        MISE_OFFLINE="1",
        MISE_DATA_DIR=str(tmp_path / "data"),
        MISE_CACHE_DIR=str(tmp_path / "cache"),
        MISE_STATE_DIR=str(tmp_path / "state"),
        MISE_GLOBAL_CONFIG_FILE=str(tmp_path / "global.toml"),
    )
    return caller, env, trace


@pytest.mark.parametrize("caller_pin", [False, True], ids=["artifact-only", "caller-pinned"])
def test_publisher_installs_uv_locked_from_its_owner_config(artifact_job, caller_pin):
    caller, env, trace = artifact_job
    if caller_pin:
        (caller / "mise.toml").write_text('[tools]\nuv = "0.12.0"\n')
        (caller / "mise.lock").write_text('[[tools.uv]]\nversion = "0.12.0"\n')
        env["MISE_LOCKED"] = "1"
    else:
        assert sorted(path.name for path in caller.iterdir()) == ["dist"]
    action = yaml.safe_load((ROOT / "publish-pypi" / "action.yml").read_text())
    install = next(step for step in action["runs"]["steps"] if step["name"] == "Install uv through mise")
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", install["run"]],
        cwd=caller,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if caller_pin:
        assert trace.read_text().splitlines() == [f"{caller}|1|install uv"]
        expected_path = "/selected/uv/bin\n"
    else:
        assert trace.read_text().splitlines() == [f"{ROOT.resolve()}|1|install uv@0.13.7"]
        assert "uv is not declared" in result.stdout
        expected_path = "/selected/uv@0.13.7/bin\n"
    assert Path(env["GITHUB_PATH"]).read_text() == expected_path
    assert sorted(path.name for path in caller.iterdir()) == (
        ["dist", "mise.lock", "mise.toml"] if caller_pin else ["dist"]
    )
