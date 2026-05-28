#!/usr/bin/env python3
"""Fix macOS dylib install_name to use @rpath instead of absolute build-host path.

When a dylib is linked on macOS, it embeds the full absolute path as LC_ID_DYLIB.
Consumers downloading the tarball cannot load it via dlopen because the path is
specific to the build host. This script rewrites the install_name to use @rpath,
allowing consumers to load it relative to their rpath entries.

Reads LIBRARY_PATH and CRATE_NAME from environment variables (GitHub Actions convention).
If LIBRARY_PATH is not set, falls back to positional args.
"""

import os
import subprocess
import sys
from pathlib import Path


def _get_library_path() -> Path | None:
    """Get library path from env or positional args."""
    library_path_str = os.environ.get("LIBRARY_PATH", "")

    if not library_path_str and len(sys.argv) >= 2:
        library_path_str = sys.argv[1]

    return Path(library_path_str) if library_path_str else None


def _get_crate_name() -> str | None:
    """Get crate name from env or positional args."""
    crate_name = os.environ.get("CRATE_NAME", "")

    if not crate_name and len(sys.argv) >= 3:
        crate_name = sys.argv[2]

    return crate_name or None


def _is_macos() -> bool:
    """Check if running on macOS."""
    runner_os = os.environ.get("RUNNER_OS", "").lower()
    if runner_os:
        return runner_os == "macos"

    import platform

    return platform.system() == "Darwin"


def _is_dylib(library_path: Path) -> bool:
    """Check if the file is a macOS dylib."""
    return str(library_path).endswith(".dylib")


def _get_dylib_name_from_crate(crate_name: str) -> str:
    """Derive the dylib name pattern.

    The pattern is lib{crate_name_underscored}.dylib, e.g., libts_pack_core_ffi.dylib.
    """
    lib_stem = crate_name.replace("-", "_")
    return f"lib{lib_stem}.dylib"


def _print_dylib_info(library_path: Path) -> None:
    """Print current install_name and other metadata using otool."""
    print("\n=== Dylib Metadata ===")
    print(f"Path: {library_path}")

    # Print all load commands (current install_name is in LC_ID_DYLIB)
    result = subprocess.run(
        ["otool", "-L", str(library_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print("\nAll load commands (otool -L):")
        for line in result.stdout.splitlines():
            print(f"  {line}")

    # Print just the install_name (LC_ID_DYLIB)
    result = subprocess.run(
        ["otool", "-D", str(library_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print("\nCurrent install_name (otool -D):")
        for line in result.stdout.splitlines():
            print(f"  {line}")


def _fix_install_name(library_path: Path, dylib_name: str) -> None:
    """Rewrite the dylib install_name to use @rpath."""
    new_install_name = f"@rpath/{dylib_name}"

    print("\n=== Rewriting install_name ===")
    print(f"Target install_name: {new_install_name}")

    cmd = ["install_name_tool", "-id", new_install_name, str(library_path)]
    print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print("Error rewriting install_name:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(1)

    print("Install_name successfully rewritten")


def main() -> None:
    """Main entry point: fix dylib install_name on macOS."""
    if not _is_macos():
        print("Not running on macOS; skipping install_name fix")
        return

    library_path = _get_library_path()
    crate_name = _get_crate_name()

    if not library_path:
        print("Error: LIBRARY_PATH is required", file=sys.stderr)
        raise SystemExit(1)

    if not crate_name:
        print("Error: CRATE_NAME is required", file=sys.stderr)
        raise SystemExit(1)

    if not library_path.is_file():
        print(f"Error: library not found at {library_path}", file=sys.stderr)
        raise SystemExit(1)

    if not _is_dylib(library_path):
        print(f"Not a .dylib file; skipping install_name fix: {library_path}")
        return

    dylib_name = _get_dylib_name_from_crate(crate_name)

    print("=== Fixing macOS dylib install_name ===")
    _print_dylib_info(library_path)
    _fix_install_name(library_path, dylib_name)
    _print_dylib_info(library_path)


if __name__ == "__main__":
    main()
