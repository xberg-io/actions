"""Wiring tests for the build-python-wheels action.

The macOS Rust setup is the load-bearing part: macos-latest runner images
preinstall a Rust toolchain whose `bin/cargo-clippy` is not tracked by rustup's
component manifest, so the consumer rust-toolchain.toml-driven `1.95` install
aborts with `detected conflict: 'bin/cargo-clippy'`. The fix wipes ~/.cargo and
~/.rustup so the in-cibw rustup owns the whole toolchain state. A prior
non-wiping pre-install (ac2ae06) regressed this; these tests guard against that
regression returning."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    path = _ROOT / "build-python-wheels" / "action.yml"
    assert path.is_file(), f"missing {path}"
    return path.read_text()


def _macos_before_all(content: str) -> str:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("CIBW_BEFORE_ALL_MACOS:"):
            value = stripped.split(":", 1)[1].strip()
            if value != ">":
                return value

            block_lines = []
            for block_line in lines[index + 1 :]:
                if block_line.startswith("        ") and block_line.strip():
                    block_lines.append(block_line.strip())
                    continue
                break
            return "\n".join(block_lines)
    raise AssertionError("CIBW_BEFORE_ALL_MACOS not found in action.yml")


def test_macos_wipes_rustup_state_before_install():
    macos = _macos_before_all(_read())
    assert "rm -rf ~/.cargo ~/.rustup" in macos
    assert "sh.rustup.rs" in macos


def test_macos_does_not_regress_to_non_wiping_preinstall():
    macos = _macos_before_all(_read())
    if "--component" in macos:
        assert "rm -rf ~/.cargo ~/.rustup" in macos, (
            "component pre-install present without the rustup-state wipe (regresses ac2ae06's clippy conflict)"
        )


def test_installs_cibuildwheel_and_uploads_wheels():
    content = _read()
    assert "pip install cibuildwheel==" in content
    assert "./wheelhouse/*.whl" in content
