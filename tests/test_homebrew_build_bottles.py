"""Regression tests for the Homebrew bottle build action."""

import os
import subprocess
from pathlib import Path

import yaml

_ACTION_DIR = Path(__file__).resolve().parents[1] / "homebrew-build-bottles"
_SCRIPT = _ACTION_DIR / "scripts" / "build-bottles.sh"
# The org macOS floor: the oldest macOS Apple still supports. Bottles are tagged for it so
# they install on every supported macOS, not only the runner's.
_MACOS_FLOOR_TAG = "sequoia"


def test_bottle_floor_defaults_to_the_org_macos_floor() -> None:
    action = yaml.safe_load((_ACTION_DIR / "action.yml").read_text())
    build = next(step for step in action["runs"]["steps"] if step["name"] == "Build bottles")

    assert action["inputs"]["bottle-floor"]["default"] == _MACOS_FLOOR_TAG
    assert build["env"]["BOTTLE_FLOOR"] == "${{ inputs.bottle-floor }}"
    assert f'bottle_floor="${{BOTTLE_FLOOR:-{_MACOS_FLOOR_TAG}}}"' in _SCRIPT.read_text()


def test_tap_clone_retries_transient_failure(tmp_path: Path) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    attempts_file = tmp_path / "tap-attempts"
    output_dir = tmp_path / "output"

    brew = binary_dir / "brew"
    brew.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --version) echo "Homebrew test" ;;
  config|update|trust|uninstall) ;;
  tap)
    attempts=$(cat "$TEST_TAP_ATTEMPTS" 2>/dev/null || echo 0)
    attempts=$((attempts + 1))
    echo "$attempts" > "$TEST_TAP_ATTEMPTS"
    [[ "$attempts" -gt 1 ]]
    ;;
  list) exit 1 ;;
  install) ;;
  bottle)
    touch "sample--${VERSION}.x86_64_linux.bottle.tar.gz"
    echo '{}' > "sample--${VERSION}.x86_64_linux.bottle.json"
    ;;
  *) echo "unexpected brew command: $*" >&2; exit 1 ;;
esac
"""
    )
    brew.chmod(0o755)

    sleep = binary_dir / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n")
    sleep.chmod(0o755)

    environment = os.environ | {
        "FORMULAS": "sample",
        "GITHUB_REPO": "example/project",
        "OUT_DIR": str(output_dir),
        "PATH": f"{binary_dir}:{os.environ['PATH']}",
        "RUNNER_OS": "macOS",
        "TAG": "v1.2.3",
        "TAP": "example/tap",
        "TEST_TAP_ATTEMPTS": str(attempts_file),
        "UPLOAD": "false",
        "VERSION": "1.2.3",
    }

    result = subprocess.run(["bash", str(_SCRIPT)], check=False, capture_output=True, text=True, env=environment)

    assert result.returncode == 0, result.stderr
    assert attempts_file.read_text().strip() == "2"
    assert (output_dir / "sample-1.2.3.x86_64_linux.bottle.tar.gz").is_file()
