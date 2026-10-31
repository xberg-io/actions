import re
from pathlib import Path

import tomllib
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_WORKFLOW = _WORKFLOWS / "reusable-actions-bump.yml"


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text())


def _triggers(workflow: dict) -> dict:
    """PyYAML reads the bare `on` key as the boolean True."""
    return workflow["on"] if "on" in workflow else workflow[True]


def _job() -> dict:
    return _workflow()["jobs"]["bump"]


def _step(name: str) -> dict:
    return next(step for step in _job()["steps"] if step.get("name") == name)


def _step_index(name: str) -> int:
    return [step.get("name") for step in _job()["steps"]].index(name)


def test_is_only_callable_and_the_job_alone_writes():
    workflow = _workflow()

    assert list(_triggers(workflow)) == ["workflow_call"]
    assert workflow["permissions"] == {"contents": "read"}
    assert _job()["permissions"] == {"contents": "write", "pull-requests": "write"}


def test_inputs_and_their_defaults():
    inputs = _triggers(_workflow())["workflow_call"]["inputs"]

    assert {name: spec["default"] for name, spec in inputs.items()} == {
        "mode": "pr",
        "runner": "ubuntu-latest",
        "paths": "",
        "commit-message": "ci: move actions to their latest major version",
    }
    assert _job()["runs-on"] == "${{ inputs.runner }}"


def test_every_input_expression_names_a_declared_input():
    referenced = set(re.findall(r"inputs\.([A-Za-z0-9_-]+)", _WORKFLOW.read_text()))
    declared = set(_triggers(_workflow())["workflow_call"]["inputs"])

    assert referenced, "no inputs.<name> expression found"
    assert referenced - declared == set()


def test_caller_owns_schedule_and_concurrency():
    """A job-level concurrency block in a called workflow overrides the caller's. ~keep"""
    assert "concurrency" not in _workflow()
    assert "concurrency" not in _job()


def test_rejects_an_unknown_mode_before_doing_anything():
    first = _job()["steps"][0]

    assert first["name"] == "Check the mode"
    assert first["env"]["MODE"] == "${{ inputs.mode }}"
    assert "push | pr) ;;" in first["run"]
    assert "exit 1" in first["run"]


def test_checks_out_the_default_branch_with_the_push_token():
    checkout = _job()["steps"][1]

    assert checkout["uses"] == "actions/checkout@v7"
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["token"] == "${{ secrets.token || github.token }}"


def test_installs_gau_and_actionlint_with_this_repository_config_as_fallback():
    install = _step("Set up gh-actions-updater and actionlint")
    fallback = _step("Check out the fallback mise config")

    assert install["uses"] == "xberg-io/actions/setup-mise@v1"
    assert install["with"]["tools"].split() == ["github:Goldziher/gh-actions-updater", "actionlint"]
    assert install["env"]["INSTALL_TOOLS_FALLBACK_ROOT"] == "${{ github.workspace }}/.xberg-actions-fallback"
    assert fallback["with"]["repository"] == "xberg-io/actions"
    assert fallback["with"]["ref"] == "v1"
    assert fallback["with"]["path"] == ".xberg-actions-fallback"
    assert fallback["with"]["sparse-checkout"].split() == ["mise.toml", "mise.lock"]
    assert _step_index("Check out the fallback mise config") < _step_index("Set up gh-actions-updater and actionlint")
    assert _step_index("Remove the fallback mise config") < _step_index("Move every action to its latest major version")


def test_this_repository_mise_config_declares_gau_and_actionlint():
    """The fallback root resolves only tools this repository's mise.toml declares. ~keep"""
    tools = tomllib.loads((_ROOT / "mise.toml").read_text())["tools"]

    assert "github:Goldziher/gh-actions-updater" in tools
    assert "actionlint" in tools


def test_runs_gau_as_a_major_bump_over_github_and_every_action_metadata_file():
    script = _step("Move every action to its latest major version")["run"]

    assert "gau --update --latest-tag --pin-style major --validate" in script
    assert '"$GITHUB_WORKSPACE/.github"' in script
    assert "':(glob)**/action.yml' ':(glob)**/action.yaml'" in script
    assert "EXTRA_PATHS" in script
    assert '-gt 0 ] || { echo "::error::' in script, "a run that scans nothing must fail"


def test_actionlint_runs_before_the_commit_push_and_pull_request():
    lint = _step_index("Lint the changed workflows")

    assert "actionlint" in _step("Lint the changed workflows")["run"]
    assert _step_index("Detect changes") < lint
    assert lint < _step_index("Commit the bump")
    assert lint < _step_index("Push to the default branch")
    assert lint < _step_index("Open or refresh the pull request")


def test_lint_commit_and_publish_run_only_when_gau_changed_something():
    changed = "steps.diff.outputs.changed == 'true'"

    for name in ("Lint the changed workflows", "Commit the bump"):
        assert _step(name)["if"] == changed, name
    assert _step("Push to the default branch")["if"] == f"{changed} && inputs.mode == 'push'"
    assert _step("Open or refresh the pull request")["if"] == f"{changed} && inputs.mode == 'pr'"


def test_push_mode_pushes_to_the_default_branch():
    push = _step("Push to the default branch")

    assert push["env"]["DEFAULT_BRANCH"] == "${{ github.event.repository.default_branch }}"
    assert push["run"] == 'git push origin "HEAD:refs/heads/$DEFAULT_BRANCH"'


def test_pr_mode_refreshes_one_branch_with_a_lease_and_opens_one_pull_request():
    step = _step("Open or refresh the pull request")
    script = step["run"]

    assert step["env"]["GH_TOKEN"] == "${{ secrets.token || github.token }}"
    assert "--force-with-lease=" in script
    assert "--force " not in script
    assert "gh pr list --head" in script
    assert script.index("gh pr list") < script.index("gh pr create")


def test_commit_message_comes_from_the_input():
    commit = _step("Commit the bump")

    assert commit["env"]["COMMIT_MESSAGE"] == "${{ inputs.commit-message }}"
    assert 'git commit --message "$COMMIT_MESSAGE"' in commit["run"]


def test_dogfood_calls_the_reusable_weekly_in_pr_mode():
    dogfood = yaml.safe_load((_WORKFLOWS / "actions-bump.yml").read_text())
    triggers = _triggers(dogfood)
    job = dogfood["jobs"]["bump"]

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert len(triggers["schedule"]) == 1
    assert len(triggers["schedule"][0]["cron"].split()) == 5
    assert "concurrency" in dogfood
    assert job["uses"] == "./.github/workflows/reusable-actions-bump.yml"
    assert job["with"] == {"mode": "pr"}
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}


def test_allow_full_lists_every_full_tag_this_repository_keeps():
    """Every non-major remote ref must be an allow_full upstream, or lint-pins fails this repo. ~keep"""
    config = tomllib.loads((_ROOT / ".gh-actions-updater.toml").read_text())
    allowed = set(config["update"]["allow_full"])
    files = [*_WORKFLOWS.glob("*.yml"), *_ROOT.glob("*/action.yml")]
    refs = [
        ref
        for path in files
        for ref in re.findall(r"uses:\s*[\"']?([\w.-]+/[\w.-]+)[\w./-]*@([^\s\"'#]+)", path.read_text())
    ]
    full = {owner_repo for owner_repo, ref in refs if not re.fullmatch(r"v?\d+", ref)}

    assert len(refs) > 100, "the scan matched too few remote refs"
    assert full <= allowed
