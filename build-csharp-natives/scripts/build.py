#!/usr/bin/env python3
"""Build a Rust FFI crate for one target and stage the library under NuGet RID layout.

Stages at: {output-dir}/runtimes/{rid}/native/{lib-prefix}{lib-name}.{ext}

For musl targets (e.g., *-linux-musl), builds inside an Alpine container to avoid
host linker incompatibilities. For other targets, builds natively on the host.

Inputs (env vars):
    INPUT_TARGET: Rust target triple (required)
    INPUT_CRATE_NAME: cargo package name (default xberg-ffi)
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

from musl_builder import build_or_fallback


def library_filename(lib_name: str, target: str) -> str:
    if "windows" in target:
        return f"{lib_name}.dll"
    if "apple" in target or "darwin" in target:
        return f"lib{lib_name}.dylib"
    return f"lib{lib_name}.so"


def cargo_release_dir(target: str) -> Path:
    return Path("target") / target / "release"


def run_cargo_build(crate_name: str, target: str, glibc_version: str = "") -> None:
    """Build using musl Docker builder for musl targets, zigbuild for gnu targets, native otherwise."""
    build_or_fallback(crate_name, target, glibc_version=glibc_version)


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


def copy_macos_runtime_deps(dylib_path: Path, staging_dir: Path) -> None:
    """Copy runtime dependencies of a macOS dylib into the staging directory.

    Uses otool -L to extract dependencies with @rpath/ prefix and copies them
    from the build output directory to the staging directory so they can be
    bundled in the NuGet package alongside the main dylib.

    Args:
        dylib_path: Path to the built .dylib file
        staging_dir: Destination directory for dependencies
    """
    if dylib_path.suffix != ".dylib":
        return

    try:
        result = subprocess.run(
            ["otool", "-L", str(dylib_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # otool not available or dylib inspection failed; silently skip
        return

    for line in result.stdout.split("\n"):
        line = line.strip()
        # Extract dependencies with @rpath/ prefix (e.g., @rpath/libonnxruntime.1.24.2.dylib)
        if not line.startswith("@rpath/"):
            continue

        dep_filename = line.split("@rpath/")[1].split()[0]  # Extract just the filename
        # `dylib_path.parent` is the release dir for the resolved cargo target,
        # e.g. `target/aarch64-apple-darwin/release/`. The previous variant used
        # `dylib_path.parent.parent` (`target/<triple>/`) and `target/release/`,
        # neither of which is where build-script-emitted runtime deps land for
        # cross-target builds.
        release_dir = dylib_path.parent
        search_patterns: list[Path] = [
            release_dir / dep_filename,  # cargo stages runtime deps alongside the cdylib
            release_dir / "deps" / dep_filename,  # cdylib `deps/` subdir
        ]
        # Build scripts (e.g. `ort-sys`) drop the prebuilt dylib under
        # `release/build/<crate>-<hash>/out/{lib,}` — recursively glob the
        # build tree for the exact filename. Limit depth via specific suffixes
        # so we don't walk the entire workspace.
        for build_root in (release_dir / "build",):
            if build_root.is_dir():
                search_patterns.extend(build_root.rglob(dep_filename))

        # `ort` (pyke prebuilt) caches the downloaded ORT bundle at
        # `<XDG_CACHE_HOME>/ort.pyke.io/dfbin/<target>/<sha>/lib/`. cargo's
        # build-script link search may not copy the dylib into `out/`, so
        # search the cache as a last resort. `XDG_CACHE_HOME` defaults to
        # `~/.cache` on Linux and `~/Library/Caches` on macOS.
        cache_roots: list[Path] = []
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache:
            cache_roots.append(Path(xdg_cache) / "ort.pyke.io" / "dfbin")
        home = Path.home()
        cache_roots.extend(
            [
                home / ".cache" / "ort.pyke.io" / "dfbin",
                home / "Library" / "Caches" / "ort.pyke.io" / "dfbin",
            ]
        )
        for cache_root in cache_roots:
            if cache_root.is_dir():
                search_patterns.extend(cache_root.rglob(dep_filename))

        found = False
        for candidate in search_patterns:
            if candidate.is_file():
                dest = staging_dir / dep_filename
                shutil.copy2(candidate, dest)
                print(f"[build-csharp-natives] staged runtime dep: {dest.resolve()}")
                found = True
                break

        if not found:
            print(f"[build-csharp-natives] warning: runtime dep not found: {dep_filename}", file=sys.stderr)


def main() -> None:
    target = ensure_input("INPUT_TARGET", os.environ.get("INPUT_TARGET", ""))
    rid = ensure_input("INPUT_RID", os.environ.get("INPUT_RID", ""))
    crate_name = os.environ.get("INPUT_CRATE_NAME", "xberg-ffi") or "xberg-ffi"
    lib_name = os.environ.get("INPUT_LIB_NAME", "") or crate_name.replace("-", "_")
    output_dir = Path(os.environ.get("INPUT_OUTPUT_DIR", "") or "dist/csharp-natives")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    glibc_version = os.environ.get("INPUT_GLIBC_VERSION", "")

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
        if glibc_version:
            print(f"  glibc-version: {glibc_version}")
        write_github_output("library-path", str(staged_lib.resolve() if staged_lib.exists() else staged_lib))
        write_github_output("staging-dir", str(staging_dir.resolve() if staging_dir.exists() else staging_dir))
        return

    run_cargo_build(crate_name, target, glibc_version)

    release_dir = cargo_release_dir(target)
    source_lib = release_dir / lib_filename
    if not source_lib.is_file():
        print(f"Error: built library not found at {source_lib}", file=sys.stderr)
        sys.exit(1)

    staging_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_lib, staged_lib)

    print(f"[build-csharp-natives] staged: {staged_lib.resolve()}")

    # On macOS, copy runtime dependencies (@rpath/ references) into staging dir
    if "darwin" in target or "apple" in target:
        copy_macos_runtime_deps(source_lib, staging_dir)

    write_github_output("library-path", str(staged_lib.resolve()))
    write_github_output("staging-dir", str(staging_dir.resolve()))


if __name__ == "__main__":
    main()
