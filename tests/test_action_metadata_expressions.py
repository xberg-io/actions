"""Action, input and output descriptions must not hold `${{ }}` expressions.

GitHub evaluates expressions in an action's metadata when it loads the action, where workflow
contexts such as `needs` do not exist. One in a description fails every job that uses the action
before its first step, with "Unrecognized named-value".
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
# ~keep A floor, so a glob that matches nothing cannot pass the guard. The repository has well over this many.
MIN_ACTIONS = 80


def _descriptions(action):
    yield "description", action.get("description") or ""
    for section in ("inputs", "outputs"):
        for name, spec in (action.get(section) or {}).items():
            yield f"{section}.{name}.description", (spec or {}).get("description") or ""


def test_no_action_description_holds_an_expression():
    actions = [(path, yaml.safe_load(path.read_text())) for path in sorted(ROOT.glob("*/action.yml"))]
    assert len(actions) >= MIN_ACTIONS
    offenders = [
        f"{path.relative_to(ROOT)}: {field}"
        for path, action in actions
        for field, text in _descriptions(action)
        if "${{" in str(text)
    ]
    assert offenders == []
