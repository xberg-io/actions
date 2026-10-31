import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/reusable-validate-pr.yml"
TRUSTED_ASSOCIATIONS = ["OWNER", "MEMBER", "COLLABORATOR"]


@pytest.fixture
def run_title_step(tmp_path):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["validate-pr-title"]["steps"]
    assert len(steps) == 1
    assert steps[0]["name"] == "Check conventional commit format"
    script = steps[0]["run"]
    assert script.strip()
    calls = tmp_path / "gh-calls"
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\0" "$*" >> "$GH_CALLS"\n'
        'if [ "$GH_FAIL" = yes ]; then echo "HTTP 403: Resource not accessible" >&2; exit 1; fi\n'
        'if [ "$1" = api ] && [ "$3" = --jq ]; then printf "%s" "$GH_COMMENT_ID"; fi\n'
    )
    gh.chmod(0o755)

    def run(title, association, *, fail=False, comment_id=""):
        environment = {
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "PR_TITLE": title,
            "AUTHOR_ASSOCIATION": association,
            "PR_URL": "https://github.com/example/project/pull/1",
            "REPO": "example/project",
            "PR_NUMBER": "1",
            "GH_TOKEN": "fixture-token",
            "GH_CALLS": str(calls),
            "GH_FAIL": "yes" if fail else "no",
            "GH_COMMENT_ID": comment_id,
        }
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        return result, calls.read_text().split("\0")[:-1] if calls.exists() else []

    return run


@pytest.mark.parametrize("association", TRUSTED_ASSOCIATIONS)
@pytest.mark.parametrize(
    "title",
    [
        *[
            f"{kind}: describe change"
            for kind in ("feat", "fix", "docs", "chore", "refactor", "test", "ci", "perf", "build", "style", "revert")
        ],
        "fix(parser): handle empty input",
        "feat(api(v2)): preserve existing scope acceptance",
        "feat!: represent Rust u64",
        "feat(dart)!: represent Rust u64 as BigInt",
    ],
)
def test_valid_titles_pass_without_github_calls(run_title_step, title, association):
    result, calls = run_title_step(title, association)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert calls == []


@pytest.mark.parametrize("association", TRUSTED_ASSOCIATIONS)
@pytest.mark.parametrize(
    "title",
    [
        "add feature",
        "unknown: describe change",
        "feat: ",
        "feat!:missing space",
        "feat!!: describe change",
        "feat(dart)!!: describe change",
        "feat!(dart): describe change",
        "feat(dart)! : describe change",
    ],
)
def test_invalid_trusted_titles_fail_without_github_calls(run_title_step, title, association):
    result, calls = run_title_step(title, association)
    assert result.returncode == 1
    assert "::error::PR title must follow conventional commit format" in result.stdout
    assert f"Got: {title}" in result.stdout
    assert calls == []


@pytest.mark.parametrize("association", ["CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"])
@pytest.mark.parametrize("fail,comment_id", [(False, ""), (False, "42"), (True, "")])
def test_invalid_outside_titles_get_best_effort_guidance(run_title_step, association, fail, comment_id):
    result, calls = run_title_step("add feature", association, fail=fail, comment_id=comment_id)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::PR title does not follow conventional format" in result.stdout
    assert len(calls) == 4
    assert calls[0].startswith("label create needs-triage ")
    assert calls[1].startswith("api repos/example/project/issues/1/comments --jq ")
    assert calls[2].startswith("api repos/example/project/issues/comments/42 -X PATCH" if comment_id else "pr comment ")
    assert "<!-- xberg-title-convention -->" in calls[2]
    assert calls[3] == "pr edit https://github.com/example/project/pull/1 --add-label needs-triage"
    if fail:
        assert "HTTP 403" in result.stderr
        assert "Could not create" in result.stdout
        assert "Could not post" in result.stdout
        assert "Could not apply" in result.stdout
