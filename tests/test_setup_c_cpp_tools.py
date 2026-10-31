from pathlib import Path

import yaml

from tests.mise_install_steps import assert_installs_through_mise

ROOT = Path(__file__).resolve().parents[1]


def test_action_installs_uv_through_mise_before_clang_format() -> None:
    steps = yaml.safe_load((ROOT / "setup-c-cpp-tools/action.yml").read_text())["runs"]["steps"]
    assert not [step for step in steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")]
    uv_steps = [step for step in steps if "install-tools.sh" in str(step.get("run", ""))]
    assert len(uv_steps) == 1
    install = uv_steps[0]
    assert install["if"] == "${{ inputs.install-clang-format == 'true' }}"
    assert_installs_through_mise("setup-c-cpp-tools", install, "uv")
    first_install = next(index for index, step in enumerate(steps) if "scripts/linux.sh" in str(step.get("run", "")))
    assert steps.index(install) < first_install
