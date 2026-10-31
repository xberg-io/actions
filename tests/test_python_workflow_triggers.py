"""Shared installer changes must schedule the Python action checks."""

import fnmatch
import math
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
INSTALLER = "setup-mise/scripts/install-tools.sh"


@pytest.mark.parametrize(
    ("workflow", "event"),
    [
        ("test-setup-python-env.yml", "push"),
        ("test-setup-python-env.yml", "pull_request"),
        ("test-build-python-wheels.yml", "push"),
    ],
)
def test_shared_installer_changes_schedule_python_action_checks(workflow, event):
    document = yaml.load((WORKFLOWS / workflow).read_text(), Loader=yaml.BaseLoader)
    paths = document["on"][event]["paths"]
    assert any(fnmatch.fnmatchcase(INSTALLER, pattern) for pattern in paths), (workflow, event, paths)


@pytest.mark.parametrize(
    ("workflow", "expected_jobs"), [("test-setup-python-env.yml", 6), ("test-build-python-wheels.yml", 2)]
)
def test_manual_main_validation_schedules_every_python_matrix_job(workflow, expected_jobs):
    document = yaml.load((WORKFLOWS / workflow).read_text(), Loader=yaml.BaseLoader)
    assert "workflow_dispatch" in document["on"]
    assert document["on"]["push"]["branches"] == ["main"]
    assert set(document["jobs"]) == {"test"}
    job = document["jobs"]["test"]
    assert job.get("if") in (None, "github.ref == 'refs/heads/main'")
    matrix = job["strategy"]["matrix"]
    assert "exclude" not in matrix
    jobs = len(matrix["include"]) if "include" in matrix else math.prod(len(axis) for axis in matrix.values())
    assert jobs == expected_jobs
