import re
from pathlib import Path

import pytest
import yaml

_ACTION = Path(__file__).resolve().parents[1] / "build-swift-artifactbundle" / "action.yml"


def test_should_forward_optional_notice_files_to_the_bundle_builder():
    action = yaml.safe_load(_ACTION.read_text())
    notice_input = action["inputs"]["additional-license-files"]
    assert notice_input["required"] is False
    assert notice_input["default"] == ""
    builds = [step for step in action["runs"]["steps"] if step.get("id") == "build"]
    assert len(builds) == 1
    assert builds[0]["env"]["INPUT_ADDITIONAL_LICENSE_FILES"] == "${{ inputs.additional-license-files }}"


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
def test_should_provision_mise_zig_only_for_actual_linux_build_steps(inputs, expected):
    action = yaml.safe_load(_ACTION.read_text())
    assert action["inputs"].get("zig-version", {}).get("default") == "", "zig-version must default to mise.toml's"
    steps = action["runs"]["steps"]
    selected = [step for step in steps if step.get("env", {}).get("ZIG_VERSION") == "${{ inputs.zig-version }}"]
    assert len(selected) == 1, "expected one explicit Zig provisioning step"
    step = selected[0]
    assert step["id"] == "zig"
    assert "$GITHUB_ACTION_PATH/../setup-mise/scripts/install-tools.sh" in step["run"], (
        "must reuse the same action checkout"
    )
    assert '"zig=$ZIG_VERSION"' in step["run"]
    assert "github:rust-cross/cargo-zigbuild" in step["run"]
    assert "cargo install" not in step["run"]
    assert steps.index(step) < next(i for i, item in enumerate(steps) if item.get("id") == "build")
    build = next(item for item in steps if item.get("id") == "build")
    assert build["env"]["INPUT_ZIG_VERSION"] == "${{ steps.zig.outputs.version || inputs.zig-version }}"
    for gated in [item for item in steps if item.get("id") in {"mise", "zig"}]:
        condition = gated["if"].strip().removeprefix("${{").removesuffix("}}")
        condition = re.sub(r"inputs\.([a-z-]+)", lambda match: repr(inputs[match[1]]), condition)
        condition = condition.replace("&&", " and ").replace("||", " or ")
        actual = eval(condition, {"__builtins__": {}, "contains": lambda value, part: part in value})
        assert actual is expected, (gated["name"], inputs, expected, actual)
