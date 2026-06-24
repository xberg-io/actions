#!/usr/bin/env python3
"""Cross-compile a Rustler NIF and package it as RustlerPrecompiled-compatible tar.gz.

Output filename: lib{nif-crate-name}-v{version}-nif-{api-version}-{target}.{so|dylib|dll}.tar.gz

For musl targets (e.g., *-linux-musl), builds inside an Alpine container to avoid
host linker incompatibilities. For other targets, builds natively on the host.

Inputs (env vars):
    INPUT_TARGET: Rust target triple (required)
    INPUT_NIF_CRATE_NAME: cargo package name of NIF crate (default kreuzberg_nif)
    INPUT_NIF_CRATE_PATH: path to NIF crate dir (default packages/elixir/native/kreuzberg_nif)
    INPUT_PACKAGE_DIR: Elixir package dir (default packages/elixir)
    INPUT_NIF_VERSION: package version (required)
    INPUT_NIF_API_VERSION: Erlang NIF API version (default "" = auto-detect)
    INPUT_OUTPUT_DIR: staging root (default dist/elixir-natives)
    INPUT_DRY_RUN: "true" to skip cargo build (default false)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from musl_builder import build_or_fallback

CHUNK_SIZE = 1 << 20


def cargo_lib_extension(target: str) -> str:
    """Filesystem extension Cargo writes the cdylib to in `target/<triple>/release/`."""
    if "windows" in target:
        return "dll"
    if "apple" in target or "darwin" in target:
        return "dylib"
    return "so"


def asset_extension(target: str) -> str:
    """Extension RustlerPrecompiled embeds in the download URL.

    `rustler_precompiled 0.9.0`'s `lib_name_with_ext/2` hardcodes `.so` for
    every non-Windows consumer download URL and has no `.dylib` branch.
    Renaming the macOS `.dylib` to `.so` inside the tarball is the only way
    to keep `lib_name-vN-nif-X.Y-<triple>.so.tar.gz` resolvable on macOS;
    Erlang loads NIFs by file contents, not extension.
    See: kreuzberg-dev/actions/generate-elixir-checksums/scripts/generate.py.
    """
    return "dll" if "windows" in target else "so"


def cargo_target_dir(manifest_path: Path) -> Path:
    """Resolve the manifest's actual cargo target directory.

    The NIF crate builds into its own `target/` when its Cargo.toml is a
    standalone workspace, but into the *parent* workspace's `target/` when its
    path-deps (or the `rewrite-native-deps` prepublish step) make it a member of
    the parent workspace; `CARGO_TARGET_DIR` / `.cargo/config.toml` can redirect
    it too. Rather than assume a layout, ask cargo so the built lib is found
    wherever cargo actually wrote it.
    """
    result = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1", "--manifest-path", str(manifest_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(json.loads(result.stdout)["target_directory"])


def cargo_release_dir(crate_path: Path, target: str) -> Path:
    try:
        base = cargo_target_dir(crate_path / "Cargo.toml")
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        # Fall back to the crate-local target dir if `cargo metadata` is unavailable.
        base = crate_path / "target"
    return base / target / "release"


def detect_nif_api_version() -> str:
    """Run `erl -noshell -eval ...` to print the NIF API version."""
    cmd = [
        "erl",
        "-noshell",
        "-eval",
        'io:format("~s", [erlang:system_info(nif_version)]), halt().',
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Error: failed to auto-detect NIF API version via erl: {exc}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def run_cargo_build(crate_name: str, crate_path: Path, target: str, glibc_version: str = "") -> None:
    """Build using musl Docker builder for musl targets, zigbuild for gnu targets, native otherwise."""
    build_or_fallback(
        crate_name,
        target,
        manifest_path=crate_path / "Cargo.toml",
        glibc_version=glibc_version,
    )


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    nif_version = ensure_input("INPUT_NIF_VERSION", os.environ.get("INPUT_NIF_VERSION", ""))
    nif_crate_name = os.environ.get("INPUT_NIF_CRATE_NAME", "kreuzberg_nif") or "kreuzberg_nif"
    nif_crate_path = Path(os.environ.get("INPUT_NIF_CRATE_PATH", "") or "packages/elixir/native/kreuzberg_nif")
    output_dir = Path(os.environ.get("INPUT_OUTPUT_DIR", "") or "dist/elixir-natives")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    glibc_version = os.environ.get("INPUT_GLIBC_VERSION", "")

    nif_api_version = os.environ.get("INPUT_NIF_API_VERSION", "").strip()
    if not nif_api_version and not dry_run:
        nif_api_version = detect_nif_api_version()
    elif not nif_api_version:
        nif_api_version = "<auto>"

    cargo_ext = cargo_lib_extension(target)
    asset_ext = asset_extension(target)
    archive_name = f"lib{nif_crate_name}-v{nif_version}-nif-{nif_api_version}-{target}.{asset_ext}.tar.gz"
    archive_path = (output_dir / archive_name).resolve()

    if dry_run:
        print("[build-elixir-natives] dry-run: skipping cargo build")
        print(f"  target:          {target}")
        print(f"  nif-crate:       {nif_crate_name}")
        print(f"  nif-version:     {nif_version}")
        print(f"  nif-api-version: {nif_api_version}")
        print(f"  archive-path:    {archive_path}")
        if glibc_version:
            print(f"  glibc-version:   {glibc_version}")
        write_github_output("archive-path", str(archive_path))
        write_github_output("archive-sha256", "")
        write_github_output("archive-name", archive_name)
        return

    run_cargo_build(nif_crate_name, nif_crate_path, target, glibc_version)

    # The Rust crate produces the lib with platform-conventional name.
    # Cargo cdylib for `<nif_crate_name>` produces `lib<nif_crate_name>.{ext}` on unix, `<nif_crate_name>.dll` on windows.
    release_dir = cargo_release_dir(nif_crate_path, target)
    source_lib = release_dir / (f"{nif_crate_name}.dll" if cargo_ext == "dll" else f"lib{nif_crate_name}.{cargo_ext}")
    if not source_lib.is_file():
        print(f"Error: built NIF library not found at {source_lib}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # The tar.gz contains the library file under its renamed RustlerPrecompiled name.
    # RustlerPrecompiled expects the archive's interior file to be the lib (not a subdir).
    # macOS `.dylib` is renamed to `.so` for rustler_precompiled URL compatibility.
    renamed_lib_name = f"lib{nif_crate_name}-v{nif_version}-nif-{nif_api_version}-{target}.{asset_ext}"
    staging_lib = output_dir / renamed_lib_name
    shutil.copy2(source_lib, staging_lib)

    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(staging_lib, arcname=renamed_lib_name)

    digest = compute_sha256(archive_path)

    print(f"[build-elixir-natives] archive: {archive_path}")
    print(f"[build-elixir-natives] sha256:  {digest}")

    # Clean up the loose lib file (the .tar.gz is the deliverable).
    staging_lib.unlink(missing_ok=True)

    write_github_output("archive-path", str(archive_path))
    write_github_output("archive-sha256", digest)
    write_github_output("archive-name", archive_name)


if __name__ == "__main__":
    main()
