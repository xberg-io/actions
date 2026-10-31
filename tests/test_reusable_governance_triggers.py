"""Governance source updates must schedule the real reusable validation jobs."""

import copy
import fnmatch
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/test-reusable-governance.yml"
PRODUCERS = {
    "ai-rulez-validation": "./.github/workflows/reusable-ai-rulez-validation.yml",
    "toolchain": "./.github/workflows/reusable-toolchain.yml",
}


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def triggers(document):
    return document.get("on", document.get(True))


def assert_producers(document):
    assert set(document["jobs"]) == set(PRODUCERS), "both validation producers must run"
    assert document["permissions"] == {"contents": "read"}
    for name, target in PRODUCERS.items():
        job = document["jobs"][name]
        assert job["uses"] == target, "the current repository's reusable workflow must run"
        assert "if" not in job, "validation must not be conditional"
        assert job.get("continue-on-error", False) is False, "validation failures must remain fatal"
    assert document["jobs"]["ai-rulez-validation"]["with"]["budgets"] == "claude=4300\ncodex=4800\n"


@pytest.mark.parametrize("event", ["push", "pull_request"])
@pytest.mark.parametrize(
    "changed",
    [
        ".ai-rulez/config.toml",
        ".ai-rulez/ai-rulez.lock",
        ".ai-rulez/skills/release-workflow/SKILL.md",
        ".ai-rulez/rules/index.md",
    ],
)
def test_governance_inputs_and_generated_indexes_schedule_both_producers(event, changed):
    document = workflow()
    assert_producers(document)
    assert any(fnmatch.fnmatchcase(changed, pattern) for pattern in triggers(document)[event]["paths"])


def test_manual_validation_runs_both_current_repository_producers():
    document = workflow()
    assert "workflow_dispatch" in triggers(document)
    assert triggers(document)["push"]["branches"] == ["main"]
    assert_producers(document)


@pytest.mark.parametrize("event", ["push", "pull_request"])
@pytest.mark.parametrize("changed", ["README.md", "setup-node-workspace/action.yml"])
def test_unrelated_changes_do_not_schedule_the_governance_wrapper(event, changed):
    assert not any(fnmatch.fnmatchcase(changed, pattern) for pattern in triggers(workflow())[event]["paths"])


@pytest.mark.parametrize("change", ["missing", "wrong-producer", "skipped", "ignored"])
def test_validation_contract_rejects_missing_or_disabled_producers(change):
    document = copy.deepcopy(workflow())
    if change == "missing":
        document["jobs"].pop("ai-rulez-validation")
        reason = "both validation producers must run"
    elif change == "wrong-producer":
        document["jobs"]["ai-rulez-validation"]["uses"] = "./.github/workflows/reusable-validate.yml"
        reason = "current repository's reusable workflow must run"
    elif change == "skipped":
        document["jobs"]["ai-rulez-validation"]["if"] = "false"
        reason = "validation must not be conditional"
    else:
        document["jobs"]["ai-rulez-validation"]["continue-on-error"] = True
        reason = "validation failures must remain fatal"
    with pytest.raises(AssertionError, match=reason):
        assert_producers(document)
