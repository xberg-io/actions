"""Keep generated OKF formatting exemptions narrow without losing lint coverage."""

import copy
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
INDEXES = {
    "/.ai-rulez/index.md",
    "/.ai-rulez/context/index.md",
    "/.ai-rulez/rules/index.md",
    "/.ai-rulez/skills/index.md",
    "/.ai-rulez/skills/release-workflow/index.md",
    "/.ai-rulez/skills/testing-conventions/index.md",
}


def configuration():
    poly = tomllib.loads((ROOT / "poly.toml").read_text())
    mise = tomllib.loads((ROOT / "mise.toml").read_text())
    return poly, mise


def formatter_command(mise):
    commands = mise["tasks"]["lint"]["run"]
    assert commands[0] == "poly lint ."
    matches = [
        shlex.split(command) for command in commands if isinstance(command, str) and command.startswith("poly fmt ")
    ]
    assert len(matches) == 1
    return matches[0]


def assert_ownership(poly, mise):
    command = formatter_command(mise)
    assert command[:4] == ["poly", "fmt", "--check", "."]
    assert len(command[4:]) == 2 * len(INDEXES)
    assert command[4::2] == ["--exclude"] * len(INDEXES)
    assert set(command[5::2]) == INDEXES
    hook = poly["hooks"]["builtin"]
    additions = set(hook["fmt"]["exclude"]) - set(hook["lint"]["exclude"])
    assert additions == INDEXES
    assert not INDEXES.intersection(poly["discovery"]["exclude"])


def test_only_six_generated_indexes_are_exempt_from_formatting():
    assert_ownership(*configuration())


@pytest.mark.parametrize("change", ["missing-hook", "missing-task", "broad-glob"])
def test_ownership_contract_rejects_missing_or_broadened_coverage(change):
    poly, mise = copy.deepcopy(configuration())
    if change == "missing-hook":
        poly["hooks"]["builtin"]["fmt"]["exclude"].remove("/.ai-rulez/index.md")
    elif change == "missing-task":
        mise["tasks"]["lint"]["run"][1] = mise["tasks"]["lint"]["run"][1].replace(
            " --exclude '/.ai-rulez/index.md'", ""
        )
    else:
        poly["hooks"]["builtin"]["fmt"]["exclude"].append("/.ai-rulez/**")
    with pytest.raises(AssertionError):
        assert_ownership(poly, mise)


def test_release_preconditions_use_the_canonical_lint_task():
    skill = (ROOT / ".ai-rulez/skills/release-workflow/SKILL.md").read_text()
    preconditions = skill.split("### Preconditions", 1)[1].split("### 1.", 1)[0]
    assert "mise run lint" in preconditions
    assert "poly fmt --check ." not in preconditions


def test_real_formatter_still_rejects_authored_markdown_and_lints_all_indexes(tmp_path):
    poly, mise = configuration()
    assert_ownership(poly, mise)
    binary = shutil.which("poly")
    assert binary is not None, "the pinned Poly binary is required for the formatting contract"
    (tmp_path / "poly.toml").write_text((ROOT / "poly.toml").read_text())
    for path in INDEXES:
        target = tmp_path / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Concepts\n\n* Canonical generator bullet\n")
    authored = tmp_path / "README.md"
    authored.write_text("# Authored\n\n- Canonical source bullet\n")
    command = [binary, *formatter_command(mise)[1:]]
    clean = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "2 files checked" in clean.stdout
    assert "6 files excluded by config" in clean.stdout
    lint = subprocess.run(
        [binary, "lint", "--no-workspace", *sorted(path.lstrip("/") for path in INDEXES)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr
    assert "6 files linted" in lint.stdout
    authored.write_text("# Authored\n\n* Unformatted source bullet\n")
    failed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "would reformat ./README.md" in failed.stdout


def assert_pytest_tools(workflow):
    steps = workflow["jobs"]["pytest"]["steps"]
    setups = [(index, step) for index, step in enumerate(steps) if step.get("uses") == "./setup-mise"]
    assert len(setups) == 1
    position, setup = setups[0]
    tools = shlex.split(setup["with"]["install-args"])
    assert {"python", "uv", "github:Goldziher/poly"}.issubset(tools)
    runs = [index for index, step in enumerate(steps) if step.get("run") == "uv run pytest -v"]
    assert len(runs) == 1
    assert position < runs[0]
    assert "if" not in setup
    assert setup.get("continue-on-error", False) is False


def test_pytest_workflow_provisions_the_real_formatter_from_managed_tools():
    workflow = yaml.safe_load((ROOT / ".github/workflows/test-unit.yml").read_text())
    assert_pytest_tools(workflow)


def test_pytest_tool_contract_rejects_a_missing_formatter():
    workflow = yaml.safe_load((ROOT / ".github/workflows/test-unit.yml").read_text())
    setup = next(step for step in workflow["jobs"]["pytest"]["steps"] if step.get("uses") == "./setup-mise")
    setup["with"]["install-args"] = "python uv"
    with pytest.raises(AssertionError):
        assert_pytest_tools(workflow)
