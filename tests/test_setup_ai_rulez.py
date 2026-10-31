from pathlib import Path

import yaml

from tests.mise_install_steps import WORKING_DIRECTORY, assert_installs_through_mise

ROOT = Path(__file__).resolve().parents[1]


def _steps() -> list[dict]:
    return yaml.safe_load((ROOT / "setup-ai-rulez/action.yml").read_text())["runs"]["steps"]


def test_action_installs_uv_through_mise_for_every_caller() -> None:
    steps = _steps()
    assert not [step for step in steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")]
    uv_steps = [
        step for step in steps if str(step.get("run", "")).endswith(" uv") and "install-tools.sh" in step["run"]
    ]
    assert len(uv_steps) == 1
    install = uv_steps[0]
    assert "if" not in install
    assert_installs_through_mise("setup-ai-rulez", install, "uv")


def test_source_build_go_installs_in_the_working_directory() -> None:
    go = next(step for step in _steps() if 'install-tools.sh" ' in str(step.get("run", "")) and "go=" in step["run"])
    assert go["run"].endswith('install-tools.sh" "$WORKING_DIRECTORY" "go=$GO_VERSION"')
    assert go["env"]["WORKING_DIRECTORY"] == WORKING_DIRECTORY


def test_mise_is_set_up_once_before_the_first_mise_install() -> None:
    steps = _steps()
    setups = [index for index, step in enumerate(steps) if step.get("uses") == "xberg-io/actions/setup-mise@v1"]
    assert len(setups) == 1
    assert steps[setups[0]]["if"] == "steps.mise.outputs.present != 'true'"
    first_install = next(index for index, step in enumerate(steps) if "install-tools.sh" in str(step.get("run", "")))
    assert setups[0] < first_install
