"""Assertions shared by the composites that install a tool through setup-mise's install-tools.sh."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION_PATH = "$GITHUB_ACTION_PATH"
WORKING_DIRECTORY = "${{ inputs.working-directory }}"


def load_action(action_dir: str) -> dict:
    return yaml.safe_load((ROOT / action_dir / "action.yml").read_text())


def mise_setup_step(steps: list[dict]) -> dict:
    setups = [step for step in steps if step.get("uses") == "xberg-io/actions/setup-mise@v1"]
    assert len(setups) == 1
    return setups[0]


def assert_installs_through_mise(action_dir: str, install: dict, tools: str) -> None:
    """The step runs install-tools.sh in the caller's working directory with this repository as the fallback."""
    action = load_action(action_dir)
    assert action["inputs"]["working-directory"]["default"] == "."
    run = install["run"].rstrip("\n")
    assert run.endswith(f'install-tools.sh" "$WORKING_DIRECTORY" {tools}')
    assert install["env"]["WORKING_DIRECTORY"] == WORKING_DIRECTORY
    assert mise_setup_step(action["runs"]["steps"])["with"]["working-directory"] == WORKING_DIRECTORY
    assert "INSTALL_TOOLS_FALLBACK_ROOT" not in install["env"]
    assignment, _, command = run.partition(" \\\n")
    assert command.lstrip().startswith(f'bash "{ACTION_PATH}/../setup-mise/scripts/install-tools.sh" ')
    assert assignment.startswith('INSTALL_TOOLS_FALLBACK_ROOT="')
    assert assignment.endswith('"')
    fallback = assignment.removeprefix('INSTALL_TOOLS_FALLBACK_ROOT="').removesuffix('"')
    assert fallback.startswith(ACTION_PATH + "/")
    resolved = (ROOT / action_dir / fallback.removeprefix(ACTION_PATH + "/")).resolve()
    assert resolved == ROOT
    assert (resolved / "mise.toml").is_file()
    assert (resolved / "mise.lock").is_file()
