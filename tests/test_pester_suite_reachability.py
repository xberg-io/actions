"""Every Pester suite in the tree must actually be run by a workflow.

`bats --recursive .` discovers suites, so a new Bats file cannot go unrun. Pester's reachability
depends on how the workflow invokes it, and this repo has used two shapes: `run-pester` steps
naming one `path:` each, and a pwsh step setting `$config.Run.Path` and letting Pester discover
recursively. The first can leave a new suite unnamed; the second cannot, but can still be pointed
at a subtree that misses one.

Both are understood here on purpose. A gate that only knew the shape in use on the day it was
written would go quietly vacuous the moment the workflow was rewritten -- which is exactly what
happened: the recursive rewrite left this file asserting that a workflow with no `run-pester`
steps covered nothing, and the honest reading of that is "the gate no longer knows how the suites
are run", not "the suites are unreachable".

A suite nobody runs is worse than no suite: it reads as coverage.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "test-pester.yml"

# `$config.Run.Path = '.'` / "..." / `@('a','b')`, and `Invoke-Pester -Path <x>`.
_RUN_PATH = re.compile(r"\$config\.Run\.Path\s*=\s*(?P<value>.+)")
_INVOKE_PATH = re.compile(r"Invoke-Pester\b[^\n]*?-Path\s+(?P<value>[^\s;]+)")
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")


def _tracked_pester_suites() -> list[str]:
    """Suites as git sees them, so an untracked scratch file never fails the gate."""
    completed = subprocess.run(
        ["git", "ls-files", "*.Tests.ps1"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(line for line in completed.stdout.splitlines() if line.strip())


def _steps() -> list[dict]:
    document = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return [
        step
        for job in (document.get("jobs") or {}).values()
        if isinstance(job, dict)
        for step in job.get("steps") or []
        if isinstance(step, dict)
    ]


def _run_scripts() -> list[str]:
    return [str(step["run"]) for step in _steps() if step.get("run")]


def _discovery_roots() -> list[str]:
    """Every tree the workflow hands to Pester, normalised to a repo-relative prefix.

    The repo root is returned as `""` so the containment test below is a plain prefix match for
    both shapes.
    """
    roots = [
        str(step["with"]["path"]).strip("/")
        for step in _steps()
        if str(step.get("uses", "")).endswith("run-pester") and (step.get("with") or {}).get("path")
    ]
    for script in _run_scripts():
        for pattern in (_RUN_PATH, _INVOKE_PATH):
            for match in pattern.finditer(script):
                value = match.group("value").strip()
                quoted = _QUOTED.findall(value)
                roots.extend(quoted or [value])
    return [("" if root in {".", "./"} else root.strip("/")) for root in roots]


def test_every_pester_suite_is_reached_by_the_workflow() -> None:
    roots = _discovery_roots()
    assert roots, (
        "test-pester.yml hands Pester no path: no run-pester step with a `path:`, and no "
        "`$config.Run.Path` or `Invoke-Pester -Path` in any run script. Either the workflow "
        "stopped running Pester, or it grew a third invocation shape this gate cannot read."
    )

    unreached = [
        suite
        for suite in _tracked_pester_suites()
        if not any(root in {"", suite} or suite.startswith(f"{root}/") for root in roots)
    ]
    assert unreached == [], (
        "these Pester suites are committed but no workflow step runs them:\n"
        + "\n".join(f"  {suite}" for suite in unreached)
        + f"\ndiscovery roots: {roots}"
    )


def test_every_discovery_root_still_contains_a_suite() -> None:
    """The other direction: a stale path naming a subtree with no suites.

    Without this the gate above stays green while silently covering nothing, which is how an
    allowance file becomes a graveyard. The repo root is exempt -- it contains every suite by
    definition, and an empty tree is the zero-discovery case the next test covers.
    """
    suites = _tracked_pester_suites()
    stale = [
        root
        for root in _discovery_roots()
        if root != "" and not any(suite == root or suite.startswith(f"{root}/") for suite in suites)
    ]
    assert stale == [], f"test-pester.yml names paths that hold no *.Tests.ps1 suites: {stale}"


def test_a_run_that_discovers_nothing_fails_the_job() -> None:
    """Recursive discovery moves the risk rather than removing it.

    Naming paths could leave a suite unlisted; discovering from a root instead makes that
    impossible, but a run that matches zero files exits 0 and reports the job green -- proving
    nothing, and indistinguishable from a full pass. Pester spells the guard `Run.Throw`; the
    `run-pester` action asserts a non-zero `FailedCount` itself, so a workflow built only from
    those steps needs no run script to carry it.
    """
    if not any(str(step.get("uses", "")).endswith("run-pester") for step in _steps()):
        scripts = "\n".join(_run_scripts())
        assert re.search(r"\$config\.Run\.Throw\s*=\s*\$true", scripts), (
            "test-pester.yml discovers recursively but does not set `$config.Run.Throw = $true`, "
            "so a run that discovers zero tests would exit 0 and report the job green."
        )


@pytest.mark.parametrize("suite", _tracked_pester_suites())
def test_every_pester_suite_is_tracked_under_a_tests_directory(suite: str) -> None:
    """Keeps discovery predictable: suites live in `<action>/tests/`, like the Bats ones."""
    assert "/tests/" in suite, f"{suite} is not under a tests/ directory"


def test_workflow_uses_checksum_verified_pinned_pester_installation() -> None:
    installers = [step for step in _steps() if step.get("uses") == "./install-pester"]
    assert len(installers) == 1, "workflow must use the verified installer, with bounded download retries"
    version = installers[0]["with"]["version"]
    checksums = (_ROOT / "install-pester" / "checksums.tsv").read_text().splitlines()
    assert any(line.split()[0] == version for line in checksums), "requested Pester must have a reviewed checksum"
    assert f"Import-Module Pester -RequiredVersion {version} -Force" in "\n".join(_run_scripts())
