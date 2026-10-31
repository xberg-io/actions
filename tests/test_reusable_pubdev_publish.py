import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "reusable-pubdev-publish.yml"


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text())


def _triggers(workflow: dict) -> dict:
    """PyYAML reads the bare `on` key as the boolean True."""
    return workflow["on"] if "on" in workflow else workflow[True]


def _inputs() -> dict:
    return _triggers(_workflow())["workflow_call"]["inputs"]


def _job() -> dict:
    return _workflow()["jobs"]["publish-pub"]


def _steps() -> list[dict]:
    return _job()["steps"]


def _step(name: str) -> dict:
    return next(step for step in _steps() if step.get("name") == name)


def test_is_only_callable_with_oidc_and_cross_run_artifact_access():
    workflow = _workflow()

    assert list(_triggers(workflow)) == ["workflow_call"]
    assert workflow["permissions"] == {"contents": "read", "id-token": "write", "actions": "read"}


def test_every_input_expression_names_a_declared_input():
    referenced = set(re.findall(r"inputs\.([A-Za-z0-9_-]+)", _WORKFLOW.read_text()))

    assert referenced, "no inputs.<name> expression found"
    assert referenced - set(_inputs()) == set()


def test_caller_owns_concurrency():
    """A job-level concurrency block in a called workflow overrides the caller's. ~keep"""
    assert "concurrency" not in _workflow()
    assert "concurrency" not in _job()


def test_tag_guard_runs_first_and_fails_on_a_branch():
    guard = _steps()[0]

    assert guard["name"] == "Require a tag ref"
    assert guard["if"] == "${{ github.ref_type != 'tag' }}"
    assert guard["run"].rstrip().endswith("exit 1")


def test_publishes_last_through_publish_pub_with_a_version_guard():
    publish = _steps()[-1]

    assert publish["uses"] == "xberg-io/actions/publish-pub@v1"
    assert "if" not in publish
    assert publish["with"] == {
        "package-dir": "${{ inputs.package-dir }}",
        "expected-version": "${{ inputs.expected-version || github.ref_name }}",
        "dry-run": "${{ inputs.dry-run }}",
    }


def test_publish_pub_receives_only_inputs_it_declares():
    composite = yaml.safe_load((_ROOT / "publish-pub" / "action.yml").read_text())["inputs"]

    assert set(_steps()[-1]["with"]) - set(composite) == set()


def test_exactly_one_source_step_runs_for_each_input_combination():
    checkout = _step("Check out the package source")
    current = _step("Download the package from the current run")
    other = _step("Download the package from another run")

    assert checkout["uses"] == "actions/checkout@v7"
    assert checkout["if"] == "${{ inputs.artifact-name == '' }}"
    assert checkout["with"]["ref"] == "${{ inputs.ref || github.ref_name }}"
    assert current["if"] == "${{ inputs.artifact-name != '' && inputs.run-id == '' }}"
    assert "run-id" not in current["with"]
    assert other["if"] == "${{ inputs.artifact-name != '' && inputs.run-id != '' }}"
    assert other["with"]["run-id"] == "${{ inputs.run-id }}"
    assert other["with"]["github-token"] == "${{ secrets.GITHUB_TOKEN }}"
    for step in (current, other):
        assert step["uses"] == "actions/download-artifact@v8"
        assert step["with"]["name"] == "${{ inputs.artifact-name }}"
        assert step["with"]["path"] == "${{ inputs.package-dir }}"


def test_downloaded_package_is_verified_before_publishing():
    steps = _steps()
    verify = _step("Verify the downloaded package")

    assert verify["if"] == "${{ inputs.artifact-name != '' }}"
    assert 'test -f "$PACKAGE_DIR/pubspec.yaml"' in verify["run"]
    assert verify["env"]["REQUIRE_NATIVES"] == "${{ inputs.require-native-libraries }}"
    assert steps.index(_step("Download the package from another run")) < steps.index(verify) < len(steps) - 1


def test_defaults_match_the_consumer_layout():
    inputs = _inputs()

    assert inputs["package-dir"]["default"] == "packages/dart"
    assert inputs["artifact-name"]["default"] == ""
    assert inputs["require-native-libraries"]["default"] is False
    assert inputs["dry-run"]["default"] is False
    assert _job()["timeout-minutes"] == "${{ inputs.timeout-minutes }}"
