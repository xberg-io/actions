"""Wiring tests for the build-elixir-hex action. The actual rewrite is alef's
(tested there) and mix hex.build is Hex's; here we assert the action installs
the rewrite, gates it on dry-run, falls back to cargo generate-lockfile for
the Hex files-list requirement, and invokes mix hex.build under the package
directory."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    path = _ROOT / "build-elixir-hex" / "action.yml"
    assert path.is_file(), f"missing {path}"
    return path.read_text()


def test_runs_rewrite_then_mix_hex_build() -> None:
    content = _read()
    assert "uses: kreuzberg-dev/actions/rewrite-native-deps@v1" in content
    assert "lang: elixir" in content
    assert "mix hex.build" in content


def test_rewrite_is_opt_outable_and_default_on() -> None:
    content = _read()
    assert "rewrite-native-deps:" in content
    assert "if: inputs.rewrite-native-deps == 'true' && inputs.dry-run != 'true'" in content
    assert 'default: "true"' in content


def test_dry_run_skips_rewrite_and_generates_lockfile() -> None:
    content = _read()
    assert "if: inputs.dry-run == 'true'" in content
    assert "cargo generate-lockfile" in content
    assert "Generate Cargo.lock for dry-run" in content


def test_installs_hex_and_rebar() -> None:
    content = _read()
    assert "mix local.hex --force" in content
    assert "mix local.rebar --force" in content


def test_prunes_native_target_dirs_before_packaging() -> None:
    content = _read()
    assert "-type d -name target -prune -exec rm -rf" in content


def test_exposes_archive_path_output() -> None:
    content = _read()
    assert "archive-path:" in content
    assert 'echo "archive-path=${archive}" >>"${GITHUB_OUTPUT}"' in content
