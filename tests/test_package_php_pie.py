"""Wiring tests for the package-php-pie composite action.

The heavy lifting (the actual `alef publish package --lang php` execution and
PIE archive layout) is tested by the alef CLI's own suite; here we only assert
the action surface and that the dry-run knob is correctly plumbed through to
alef's `--dry-run` flag (which short-circuits before the path-dep validation).
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    path = _ROOT / "package-php-pie" / "action.yml"
    assert path.is_file(), f"missing {path}"
    return path.read_text()


def test_action_calls_alef_publish_package_for_php():
    content = _read()
    assert "alef publish package --lang php" in content


def test_action_exposes_dry_run_input():
    content = _read()
    assert "dry-run:" in content
    assert "DRY_RUN: ${{ inputs.dry-run }}" in content


def test_action_appends_alef_dry_run_flag_when_input_is_true():
    content = _read()
    assert 'if [[ "${DRY_RUN}" == "true" ]]; then' in content
    assert "cmd+=(--dry-run)" in content


def test_action_skips_archive_check_in_dry_run():
    content = _read()
    assert "alef publish package short-circuited; creating placeholder outputs" in content
    assert 'touch "${dummy_archive}"' in content
