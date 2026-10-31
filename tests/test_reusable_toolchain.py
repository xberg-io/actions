import re
from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "reusable-toolchain.yml"


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text())


def _triggers(workflow: dict) -> dict:
    """PyYAML reads the bare `on` key as the boolean True."""
    return workflow["on"] if "on" in workflow else workflow[True]


def _job() -> dict:
    return _workflow()["jobs"]["check-toolchain"]


def test_is_only_callable_and_reads_contents():
    workflow = _workflow()

    assert list(_triggers(workflow)) == ["workflow_call"]
    assert workflow["permissions"] == {"contents": "read"}


def test_every_input_expression_names_a_declared_input():
    referenced = set(re.findall(r"inputs\.([A-Za-z0-9_-]+)", _WORKFLOW.read_text()))
    declared = set(_triggers(_workflow())["workflow_call"]["inputs"])

    assert referenced, "no inputs.<name> expression found"
    assert referenced - declared == set()


def test_caller_owns_concurrency():
    """A job-level concurrency block in a called workflow overrides the caller's. ~keep"""
    assert "concurrency" not in _workflow()
    assert "concurrency" not in _job()


def test_runner_defaults_to_github_hosted_ubuntu():
    inputs = _triggers(_workflow())["workflow_call"]["inputs"]

    assert _job()["runs-on"] == "${{ inputs.runner }}"
    assert inputs["runner"]["default"] == "ubuntu-latest"


def test_checks_the_baseline_then_installs_from_the_lock():
    steps = _job()["steps"]

    assert [step.get("uses") for step in steps] == [
        "actions/checkout@v7",
        "xberg-io/actions/check-toolchain@v1",
        "xberg-io/actions/setup-mise@v1",
    ]
    assert not [step for step in steps if "if" in step], "every step runs on every call"


def test_install_covers_the_whole_lock():
    """`install-args` or `tools` would narrow the install to a subset of mise.lock. ~keep"""
    install = _job()["steps"][2]

    for narrowing in ("install-args", "tools", "install"):
        assert narrowing not in install.get("with", {}), narrowing


def test_own_ci_calls_the_local_reusable():
    """This repository's own toolchain gate is the reusable's dogfood caller. ~keep"""
    caller = yaml.safe_load((_WORKFLOW.parent / "toolchain.yml").read_text())
    triggers = _triggers(caller)

    assert caller["jobs"] == {"check-toolchain": {"uses": "./.github/workflows/reusable-toolchain.yml"}}
    for event in ("push", "pull_request"):
        assert ".github/workflows/reusable-toolchain.yml" in triggers[event]["paths"], event
