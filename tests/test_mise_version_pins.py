"""Every action that installs mise must pin the same exact mise version.

Two actions with different pins in one job would install mise twice, and the locks a repository
generates with one mise would be read by another. setup-mise is the only one today; the scan keeps a
new one from drifting.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_EXACT_VERSION = re.compile(r"^\d{4}\.\d{1,2}\.\d+$")


def _mise_action_versions(action_file: Path) -> list[str]:
    document = yaml.safe_load(action_file.read_text(encoding="utf-8"))
    return [
        str((step.get("with") or {}).get("version", ""))
        for step in document["runs"].get("steps", [])
        if str(step.get("uses", "")).startswith("jdx/mise-action@")
    ]


def _mise_installing_actions() -> dict[str, list[str]]:
    pins = {path.parent.name: _mise_action_versions(path) for path in sorted(_ROOT.glob("*/action.yml"))}
    return {action: versions for action, versions in pins.items() if versions}


def test_setup_mise_is_found_by_the_scan() -> None:
    assert "setup-mise" in _mise_installing_actions()


def test_each_mise_installing_action_pins_one_exact_version() -> None:
    for action, versions in _mise_installing_actions().items():
        assert len(versions) == 1, f"{action}: expected one jdx/mise-action step, found {len(versions)}"
        assert _EXACT_VERSION.match(versions[0]), f"{action}: mise version {versions[0]!r} is not an exact release"


def test_every_mise_installing_action_pins_the_same_version() -> None:
    pins = _mise_installing_actions()
    assert len({version for versions in pins.values() for version in versions}) == 1, pins
