from pathlib import Path

import tomlkit
import yaml

_ROOT = Path(__file__).resolve().parents[1]


def test_task_test_collects_every_configured_testpath():
    tasks = tomlkit.parse((_ROOT / "mise.toml").read_text())["tasks"]
    test_unit = tasks["test:unit"]["run"]

    assert test_unit == "uv run pytest -v"
    assert [step["task"] for step in tasks["test"]["run"]] == ["test:unit", "test:bats", "test:pester"]

    release_skill = (_ROOT / ".ai-rulez" / "skills" / "release-workflow" / "SKILL.md").read_text()
    assert "task test                         # pytest + Bats + Pester" in release_skill
    assert "pytest tests/" not in release_skill


def test_unit_workflow_runs_when_reusable_validate_changes():
    workflow = yaml.safe_load((_ROOT / ".github" / "workflows" / "test-unit.yml").read_text())
    triggers = workflow[True]

    workflow_path = ".github/workflows/reusable-validate.yml"
    for event in ("push", "pull_request"):
        paths = triggers[event]["paths"]
        assert workflow_path in paths
        assert "Taskfile.yml" in paths


def test_validate_versions_workflow_uses_current_alef_schema():
    workflow = (_ROOT / ".github" / "workflows" / "test-validate-versions.yml").read_text()

    assert "[manifests]" not in workflow
    assert workflow.count("[[crates]]") == 2
    assert workflow.count('languages = ["node"]') == 2
    assert "_fixture/mismatch" not in workflow
    assert 'if [[ "${OUTCOME}" != "failure" ]]; then' in workflow


def test_release_asset_workflow_targets_an_existing_immutable_release():
    workflow = (_ROOT / ".github" / "workflows" / "test-verify-release-assets.yml").read_text()

    assert "tag: v0.79.2" in workflow
    assert "tag: v0.26.2" not in workflow
