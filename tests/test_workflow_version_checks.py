"""Version assertions must not require Git Bash's absent /dev/stderr file."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKS = {
    "mise": ("test-setup-mise.yml", "Verify the selected versions are first on PATH"),
    "node": ("test-setup-node-workspace.yml", "Verify installation"),
}


def version_step(which):
    workflow, name = CHECKS[which]
    source = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    steps = [step for job in source["jobs"].values() for step in job.get("steps", []) if step.get("name") == name]
    assert len(steps) == 1
    return steps[0]["run"]


@pytest.fixture
def commands(tmp_path):
    versions = {"yq": "yq version 4.53.6", "jq": "jq-1.8.2", "node": "v26.12.1", "pnpm": "12.15.0"}
    for name, value in versions.items():
        path = tmp_path / name
        path.write_text(
            f"#!{sys.executable}\nimport os\n"
            f"print('wrong-version' if os.environ.get('WRONG_TOOL') == '{name}' else '{value}')\n"
        )
        path.chmod(0o755)
    mise = tmp_path / "mise"
    mise.write_text(f"#!{sys.executable}\nimport sys\nprint({{'node':'26.12.1','pnpm':'12.15.0'}}[sys.argv[2]])\n")
    mise.chmod(0o755)
    tee = tmp_path / "tee"
    tee.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "sys.stdout.write(sys.stdin.read())\n"
        "print('tee: /dev/stderr: No such file or directory',file=sys.stderr)\n"
        "sys.exit(1)\n"
    )
    tee.chmod(0o755)
    npmrc = tmp_path / ".npmrc"
    npmrc.write_text("//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}\nregistry=https://registry.npmjs.org/\n")
    return {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "MISE_LOCKED": "1",
        "NODE_AUTH_TOKEN": "XXXXX-XXXXX-XXXXX-XXXXX",
        "NPM_CONFIG_USERCONFIG": str(npmrc),
    }


@pytest.mark.parametrize("which", CHECKS)
def test_actual_version_step_passes_without_a_dev_stderr_file(commands, which):
    result = subprocess.run(
        ["bash", "-c", version_step(which)], env=commands, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tee:" not in result.stderr


@pytest.mark.parametrize(("which", "tool"), [("mise", "yq"), ("mise", "jq"), ("node", "node"), ("node", "pnpm")])
def test_actual_version_step_still_rejects_every_wrong_tool_version(commands, which, tool):
    commands["WRONG_TOOL"] = tool
    result = subprocess.run(
        ["bash", "-c", version_step(which)], env=commands, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert "wrong-version" in result.stdout + result.stderr
    assert "tee:" not in result.stderr
