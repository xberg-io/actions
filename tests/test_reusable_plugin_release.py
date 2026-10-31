import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "reusable-plugin-release.yml"
_PACKAGE = "xberg-io/actions/package-ai-rulez-plugin@v1"
_UPLOAD = "xberg-io/actions/upload-release-assets@v1"


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text())


def _triggers(workflow: dict) -> dict:
    """PyYAML reads the bare `on` key as the boolean True."""
    return workflow["on"] if "on" in workflow else workflow[True]


def _inputs() -> dict:
    return _triggers(_workflow())["workflow_call"]["inputs"]


def _job() -> dict:
    return _workflow()["jobs"]["package"]


def _steps() -> list[dict]:
    return _job()["steps"]


def _step(key: str) -> dict:
    return next(step for step in _steps() if key in (step.get("uses"), step.get("name")))


def _composite_inputs(action: str) -> dict:
    return yaml.safe_load((_ROOT / action / "action.yml").read_text())["inputs"]


def test_is_only_callable_and_writes_release_assets():
    workflow = _workflow()

    assert list(_triggers(workflow)) == ["workflow_call"]
    assert workflow["permissions"] == {"contents": "write"}


def test_every_input_expression_names_a_declared_input():
    referenced = set(re.findall(r"inputs\.([A-Za-z0-9_-]+)", _WORKFLOW.read_text()))

    assert referenced, "no inputs.<name> expression found"
    assert referenced - set(_inputs()) == set()


def test_caller_owns_concurrency():
    """A job-level concurrency block in a called workflow overrides the caller's. ~keep"""
    assert "concurrency" not in _workflow()
    assert "concurrency" not in _job()


def test_tag_is_required():
    assert _inputs()["tag"]["required"] is True


def test_unconditional_steps_run_in_order():
    uses = [step.get("uses") or step["name"] for step in _steps() if "if" not in step]

    assert uses == [
        "actions/checkout@v7",
        "xberg-io/actions/setup-ai-rulez@v1",
        _PACKAGE,
        "Archive verified runtime bundles and marketplace indexes",
        _UPLOAD,
    ]


def test_checks_out_the_ref_or_tag_with_full_history():
    checkout = _step("actions/checkout@v7")

    assert checkout["with"] == {"ref": "${{ inputs.ref || inputs.tag }}", "fetch-depth": 0}


def test_package_inputs_pass_through_with_the_composite_defaults():
    composite = _composite_inputs("package-ai-rulez-plugin")
    passed = _step(_PACKAGE)["with"]
    inputs = _inputs()

    assert passed["tag"] == "${{ inputs.tag }}"
    assert set(passed) - set(composite) == set()
    for name in ("version-sync-script", "config-directory"):
        assert passed[name] == f"${{{{ inputs.{name} }}}}", name
        assert inputs[name]["default"] == composite[name]["default"], name
    assert passed["cursor-marketplace"] == "${{ inputs.cursor-marketplace }}"
    # Every consumer exports the Cursor marketplace, unlike the composite's default. ~keep
    assert inputs["cursor-marketplace"]["default"] is True


def test_public_skills_check_is_skippable():
    check = _step("Verify public skill exports")

    assert check["if"] == "${{ inputs.public-skills-check-script != '' }}"
    assert check["run"] == 'python3 "$SCRIPT" --check'
    assert _inputs()["public-skills-check-script"]["default"] == "scripts/sync_public_skills.py"


def test_provenance_runs_from_the_workflow_commit_before_packaging():
    steps = _steps()
    provenance = _step("Verify the release source provenance")

    assert provenance["if"] == "${{ inputs.provenance-script != '' }}"
    assert provenance["env"]["WORKFLOW_SHA"] == "${{ github.workflow_sha }}"
    assert '"$RUNNER_TEMP/plugin-source-provenance.json"' in provenance["run"]
    assert steps.index(provenance) < steps.index(_step(_PACKAGE))
    archive = _step("Archive verified runtime bundles and marketplace indexes")
    assert "dist/plugin/source-provenance.json" in archive["run"]


def test_archive_defaults_its_name_to_the_repository():
    archive = _step("Archive verified runtime bundles and marketplace indexes")

    assert archive["env"]["PLUGIN_PRODUCT"] == "${{ inputs.product || github.event.repository.name }}"
    assert 'bundle="dist/${PLUGIN_PRODUCT}-plugins-${PLUGIN_TAG//\\//-}.tar.gz"' in archive["run"]


def test_uploads_the_archive_and_its_checksum():
    upload = _step(_UPLOAD)

    assert set(upload["with"]) - set(_composite_inputs("upload-release-assets")) == set()
    assert upload["with"]["tag"] == "${{ inputs.tag }}"
    assert upload["with"]["clobber"] == "${{ inputs.clobber }}"
    assert upload["with"]["assets"].split() == ["dist/*-plugins-*.tar.gz", "dist/*-plugins-*.tar.gz.sha256"]
    assert _inputs()["clobber"]["default"] is True
