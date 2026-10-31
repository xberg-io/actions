import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "reusable-ai-rulez-validation.yml"
_REQUIRED_STEPS = [
    "actions/checkout@v7",
    "xberg-io/actions/setup-ai-rulez@v1",
    "xberg-io/actions/validate-ai-rulez@v1",
    "xberg-io/agent-conventions/actions/context-exposure@v1",
]


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text())


def _triggers(workflow: dict) -> dict:
    """PyYAML reads the bare `on` key as the boolean True."""
    return workflow["on"] if "on" in workflow else workflow[True]


def _inputs() -> dict:
    return _triggers(_workflow())["workflow_call"]["inputs"]


def _steps() -> list[dict]:
    return _workflow()["jobs"]["validate"]["steps"]


def _step(uses: str) -> dict:
    return next(step for step in _steps() if step.get("uses") == uses)


def test_is_only_callable_and_reads_contents():
    workflow = _workflow()

    assert list(_triggers(workflow)) == ["workflow_call"]
    assert workflow["permissions"] == {"contents": "read"}


def test_every_input_expression_names_a_declared_input():
    referenced = set(re.findall(r"inputs\.([A-Za-z0-9_-]+)", _WORKFLOW.read_text()))

    assert referenced, "no inputs.<name> expression found"
    assert referenced - set(_inputs()) == set()


def test_caller_owns_concurrency():
    """A job-level concurrency block in a called workflow overrides the caller's. ~keep"""
    workflow = _workflow()

    assert "concurrency" not in workflow
    assert "concurrency" not in workflow["jobs"]["validate"]


def test_required_steps_run_unconditionally_in_order():
    uses = [step.get("uses") for step in _steps() if "if" not in step]

    assert uses == _REQUIRED_STEPS


def test_budgets_are_required_and_reach_context_exposure():
    exposure = _step("xberg-io/agent-conventions/actions/context-exposure@v1")

    assert _inputs()["budgets"]["required"] is True
    assert exposure["with"]["budgets"] == "${{ inputs.budgets }}"
    assert exposure["with"]["repo-name"] == "${{ inputs.repo-name || github.event.repository.name }}"


def test_validate_inputs_pass_through_with_the_composite_defaults():
    inputs = _inputs()
    composite = yaml.safe_load((_ROOT / "validate-ai-rulez" / "action.yml").read_text())["inputs"]
    passed = _step("xberg-io/actions/validate-ai-rulez@v1")["with"]

    names = [
        "expected-config-count",
        "additional-config-directories",
        "verify-plugin",
        "version-sync-script",
        "public-skills-check-script",
    ]
    assert sorted(passed) == sorted(names)
    for name in names:
        assert passed[name] == f"${{{{ inputs.{name} }}}}", name
        default = inputs[name]["default"]
        # Composite inputs are strings; a boolean workflow input renders as "true" or "false". ~keep
        if inputs[name]["type"] == "boolean":
            default = str(default).lower()
        assert default == composite[name]["default"], name


def test_mise_tools_install_only_when_requested_and_before_ai_rulez():
    steps = _steps()
    mise = next(step for step in steps if step.get("uses") == "xberg-io/actions/setup-mise@v1")

    assert mise["if"] == "${{ inputs.mise-install-args != '' }}"
    assert mise["with"]["install-args"] == "${{ inputs.mise-install-args }}"
    assert steps.index(mise) < steps.index(_step("xberg-io/actions/setup-ai-rulez@v1"))


def test_runner_defaults_to_github_hosted_ubuntu():
    assert _workflow()["jobs"]["validate"]["runs-on"] == "${{ inputs.runner }}"
    assert _inputs()["runner"]["default"] == "ubuntu-latest"
