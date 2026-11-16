"""require-job-results turns a channel blocked by a failed build into a red job that names it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ACTION = Path(__file__).resolve().parents[1] / "require-job-results"
_SCRIPT = _ACTION / "scripts" / "require_results.py"


def _needs(**results: str) -> str:
    return json.dumps({job: {"result": result, "outputs": {}} for job, result in results.items()})


def _run(
    needs: str, succeeded: str = "", succeeded_or_skipped: str = "", channel: str = "PyPI"
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "INPUT_CHANNEL": channel,
        "INPUT_NEEDS": needs,
        "INPUT_SUCCEEDED": succeeded,
        "INPUT_SUCCEEDED_OR_SKIPPED": succeeded_or_skipped,
    }
    return subprocess.run([sys.executable, str(_SCRIPT)], env=env, capture_output=True, text=True, check=False)


def test_all_required_jobs_succeeded_passes():
    result = _run(_needs(wheels="success", musl="success"), succeeded="wheels\nmusl\n")

    assert result.returncode == 0, result.stdout
    assert "all 2 required job result(s) accepted" in result.stdout


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped"])
def test_a_required_job_that_did_not_succeed_fails_and_names_the_channel(outcome):
    result = _run(_needs(wheels="success", musl=outcome), succeeded="wheels,musl")

    assert result.returncode == 1
    assert f"::error title=PyPI not published::musl finished '{outcome}' (needs success)" in result.stdout
    assert "wheels finished" not in result.stdout


def test_skipped_is_accepted_only_where_allowed():
    passing = _run(_needs(upload="skipped", crates="success"), succeeded_or_skipped="upload\ncrates")
    failing = _run(_needs(upload="failure"), succeeded_or_skipped="upload")

    assert passing.returncode == 0, passing.stdout
    assert failing.returncode == 1
    assert "upload finished 'failure' (needs skipped or success)" in failing.stdout


def test_blank_entries_from_an_empty_expression_are_ignored():
    result = _run(_needs(wheels="success"), succeeded="wheels\n\n  \n")

    assert result.returncode == 0, result.stdout
    assert "all 1 required job result(s) accepted" in result.stdout


def test_a_job_missing_from_needs_fails_instead_of_passing_unchecked():
    result = _run(_needs(wheels="success"), succeeded="wheels\nwheel-musl")

    assert result.returncode == 1
    assert "wheel-musl is not in this job's needs" in result.stdout


def test_no_jobs_named_fails_rather_than_checking_nothing():
    result = _run(_needs(wheels="success"))

    assert result.returncode == 1
    assert "name at least one job" in result.stdout


@pytest.mark.parametrize("needs", ["", "not json", "[]"])
def test_needs_that_is_not_the_needs_object_fails(needs):
    result = _run(needs, succeeded="wheels")

    assert result.returncode == 1
    assert "toJSON(needs)" in result.stdout


def test_action_passes_every_input_to_the_script():
    action = yaml.safe_load((_ACTION / "action.yml").read_text())
    step = action["runs"]["steps"][0]

    assert step["env"] == {
        "INPUT_CHANNEL": "${{ inputs.channel }}",
        "INPUT_NEEDS": "${{ inputs.needs }}",
        "INPUT_SUCCEEDED": "${{ inputs.succeeded }}",
        "INPUT_SUCCEEDED_OR_SKIPPED": "${{ inputs.succeeded-or-skipped }}",
    }
    assert "require_results.py" in step["run"]
