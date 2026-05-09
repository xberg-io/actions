#!/usr/bin/env python3
"""Build a Rust FFI crate for one target and stage the library under NuGet RID layout.

Stages at: {output-dir}/runtimes/{rid}/native/{lib-prefix}{lib-name}.{ext}

Inputs (env vars):
    INPUT_TARGET: Rust target triple (required)
    INPUT_CRATE_NAME: cargo package name (default kreuzberg-ffi)
    INPUT_LIB_NAME: library base name (default = crate-name with - → _)
    INPUT_RID: .NET runtime identifier (required), e.g. linux-x64
    INPUT_OUTPUT_DIR: staging root (default dist/csharp-natives)
    INPUT_DRY_RUN: "true" to skip cargo build (default false)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def library_filename(lib_name: str, target: str) -> str:
    if "windows" in target:
        return f"{lib_name}.dll"
    if "apple" in target or "darwin" in target:
        return f"lib{lib_name}.dylib"
    return f"lib{lib_name}.so"


def cargo_release_dir(target: str) -> Path:
    return Path("target") / target / "release"


def run_cargo_build(crate_name: str, target: str) -> None:
    cmd = ["cargo", "build", "-p", crate_name, "--release", "--target", target]
    print(f"[build-csharp-natives] Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def write_github_output(name: str, value: str) -> None:
    sink = os.environ.get("GITHUB_OUTPUT", "")
    line = f"{name}={value}\n"
    if sink:
        with Path(sink).open("a", encoding="utf-8") as handle:
            handle.write(line)
    else:
        sys.stdout.write(line)


def ensure_input(name: str, value: str) -> str:
    if not value:
        print(f"Error: {name} is required", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    target = ensure_input("INPUT_TARGET", os.environ.get("INPUT_TARGET", ""))
    rid = ensure_input("INPUT_RID", os.environ.get("INPUT_RID", ""))
    crate_name = os.environ.get("INPUT_CRATE_NAME", "kreuzberg-ffi") or "kreuzberg-ffi"
    lib_name = os.environ.get("INPUT_LIB_NAME", "") or crate_name.replace("-", "_")
    output_dir = Path(os.environ.get("INPUT_OUTPUT_DIR", "") or "dist/csharp-natives")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    lib_filename = library_filename(lib_name, target)
    staging_dir = output_dir / "runtimes" / rid / "native"
    staged_lib = staging_dir / lib_filename

    if dry_run:
        print("[build-csharp-natives] dry-run: skipping cargo build")
        print(f"  target:      {target}")
        print(f"  rid:         {rid}")
        print(f"  lib:         {lib_filename}")
        print(f"  staging-dir: {staging_dir}")
        print(f"  library:     {staged_lib}")
        write_github_output("library-path", str(staged_lib.resolve() if staged_lib.exists() else staged_lib))
        write_github_output("staging-dir", str(staging_dir.resolve() if staging_dir.exists() else staging_dir))
        return

    run_cargo_build(crate_name, target)

    release_dir = cargo_release_dir(target)
    source_lib = release_dir / lib_filename
    if not source_lib.is_file():
        print(f"Error: built library not found at {source_lib}", file=sys.stderr)
        sys.exit(1)

    staging_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_lib, staged_lib)

    print(f"[build-csharp-natives] staged: {staged_lib.resolve()}")

    write_github_output("library-path", str(staged_lib.resolve()))
    write_github_output("staging-dir", str(staging_dir.resolve()))


if __name__ == "__main__":
    main()
