"""Every action that installs mise must pin the same exact mise version.

setup-mise and install-task can run in one job. Two different pins would install mise twice, and the
locks a repository generates with one mise would be read by another.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_MISE_ACTIONS = ("setup-mise", "install-task")
_EXACT_VERSION = re.compile(r"^\d{4}\.\d{1,2}\.\d+$")


def _mise_action_versions(action: str) -> list[str]:
    document = yaml.safe_load((_ROOT / action / "action.yml").read_text(encoding="utf-8"))
    return [
        str((step.get("with") or {}).get("version", ""))
        for step in document["runs"]["steps"]
        if str(step.get("uses", "")).startswith("jdx/mise-action@")
    ]


def test_each_mise_installing_action_pins_one_exact_version() -> None:
    for action in _MISE_ACTIONS:
        versions = _mise_action_versions(action)
        assert len(versions) == 1, f"{action}: expected one jdx/mise-action step, found {len(versions)}"
        assert _EXACT_VERSION.match(versions[0]), f"{action}: mise version {versions[0]!r} is not an exact release"


def test_setup_mise_and_install_task_pin_the_same_mise_version() -> None:
    pins = {action: _mise_action_versions(action) for action in _MISE_ACTIONS}
    assert len({version for versions in pins.values() for version in versions}) == 1, pins
