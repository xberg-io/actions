import re
from pathlib import Path

import pytest
import yaml

_ACTION = Path(__file__).resolve().parents[1] / "build-swift-artifactbundle" / "action.yml"


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [
        ({"targets": "aarch64-unknown-linux-gnu", "dry-run": "false", "prebuilt-libs-dir": ""}, True),
        ({"targets": "", "dry-run": "false", "prebuilt-libs-dir": ""}, True),
        ({"targets": "aarch64-apple-darwin", "dry-run": "false", "prebuilt-libs-dir": ""}, False),
        ({"targets": "aarch64-unknown-linux-gnu", "dry-run": "true", "prebuilt-libs-dir": ""}, False),
        ({"targets": "", "dry-run": "false", "prebuilt-libs-dir": "archives"}, False),
    ],
    ids=["linux", "all-targets", "apple-only", "dry-run", "assemble-only"],
)
def test_should_provision_pinned_zig_only_for_actual_linux_build_steps(inputs, expected):
    action = yaml.safe_load(_ACTION.read_text())
    assert action["inputs"].get("zig-version", {}).get("default") == "0.17.0", "missing pinned Zig release input"
    steps = action["runs"]["steps"]
    selected = [step for step in steps if step.get("env", {}).get("ZIG_VERSION") == "${{ inputs.zig-version }}"]
    assert len(selected) == 1, "expected one explicit Zig provisioning step"
    step = selected[0]
    assert "${{ github.action_path }}/../setup-zig/scripts/unix.sh" in step["run"], (
        "must reuse the same action checkout"
    )
    assert steps.index(step) < next(i for i, item in enumerate(steps) if item.get("id") == "build")
    build = next(item for item in steps if item.get("id") == "build")
    assert build["env"]["INPUT_ZIG_VERSION"] == "${{ inputs.zig-version }}"
    condition = step["if"].strip().removeprefix("${{").removesuffix("}}")
    condition = re.sub(r"inputs\.([a-z-]+)", lambda match: repr(inputs[match[1]]), condition)
    condition = condition.replace("&&", " and ").replace("||", " or ")
    actual = eval(condition, {"__builtins__": {}, "contains": lambda value, part: part in value})
    assert actual is expected, (inputs, expected, actual)
