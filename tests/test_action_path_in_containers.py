"""Composite steps must reach their own files through $GITHUB_ACTION_PATH, not ${{ github.action_path }}.

Inside a `container:` job the expression expands to the runner host's path, which the container does not
mount; the runner translates only the GITHUB_ACTION_PATH environment variable to the container's path.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPRESSION = "github.action_path"
# ~keep A floor, so a glob that matches nothing cannot pass the guard. The repository has well over this many.
MIN_COMPOSITES = 80


def _composites():
    for path in sorted(ROOT.glob("*/action.yml")):
        action = yaml.safe_load(path.read_text())
        if action.get("runs", {}).get("using") == "composite":
            yield path, action["runs"]["steps"]


def _expression_uses(steps):
    for step in steps:
        for key, value in step.items():
            if EXPRESSION in yaml.safe_dump(value):
                yield step.get("name", step.get("id", "?")), key


def test_no_composite_step_uses_the_host_action_path_expression():
    composites = list(_composites())
    assert len(composites) >= MIN_COMPOSITES
    offenders = [
        f"{path.relative_to(ROOT)}: {name} ({key})"
        for path, steps in composites
        for name, key in _expression_uses(steps)
    ]
    assert offenders == []


def test_guard_flags_the_expression_in_run_and_env():
    steps = yaml.safe_load(
        """
        - name: script
          shell: bash
          run: bash "${{ github.action_path }}/scripts/x.sh"
        - name: fallback
          shell: bash
          env:
            ROOT: ${{ github.action_path }}/..
          run: echo "$ROOT"
        - name: clean
          shell: bash
          run: bash "$GITHUB_ACTION_PATH/scripts/x.sh"
        """
    )
    assert list(_expression_uses(steps)) == [("script", "run"), ("fallback", "env")]
