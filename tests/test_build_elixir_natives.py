"""Tests for build-elixir-natives/scripts/build.py."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "build-elixir-natives" / "scripts"


def _import_script(name: str, path: Path):
    # build.py does `from musl_builder import ...`, so its scripts dir must be importable.
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_mod = _import_script("build_elixir_natives", _SCRIPTS_DIR / "build.py")


def test_run_cargo_build_uses_provided_crate_name() -> None:
    """run_cargo_build builds the configured NIF crate, never a hardcoded consumer name."""
    with patch.object(build_mod, "build_or_fallback") as mock_build:
        build_mod.run_cargo_build(
            "my_app_nif",
            Path("packages/elixir/native/my_app_nif"),
            "x86_64-unknown-linux-gnu",
        )

    mock_build.assert_called_once()
    # The first positional arg is the cargo package name passed to `cargo build -p`.
    assert mock_build.call_args.args[0] == "my_app_nif"
