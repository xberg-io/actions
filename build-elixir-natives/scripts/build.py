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
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from musl_builder import build_or_fallback

CHUNK_SIZE = 1 << 20


def lib_extension(target: str) -> str:
    if "windows" in target:
        return "dll"
    if "apple" in target or "darwin" in target:
        return "dylib"
    return "so"


def cargo_release_dir(target: str) -> Path:
    return Path("target") / target / "release"


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


def run_cargo_build(crate_name: str, crate_path: Path, target: str) -> None:
    """Build using musl Docker builder for musl targets, native build otherwise."""
    build_or_fallback(crate_name, target, manifest_path=crate_path / "Cargo.toml")


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

    nif_api_version = os.environ.get("INPUT_NIF_API_VERSION", "").strip()
    if not nif_api_version and not dry_run:
        nif_api_version = detect_nif_api_version()
    elif not nif_api_version:
        nif_api_version = "<auto>"

    ext = lib_extension(target)
    archive_name = f"lib{nif_crate_name}-v{nif_version}-nif-{nif_api_version}-{target}.{ext}.tar.gz"
    archive_path = (output_dir / archive_name).resolve()

    if dry_run:
        print("[build-elixir-natives] dry-run: skipping cargo build")
        print(f"  target:          {target}")
        print(f"  nif-crate:       {nif_crate_name}")
        print(f"  nif-version:     {nif_version}")
        print(f"  nif-api-version: {nif_api_version}")
        print(f"  archive-path:    {archive_path}")
        write_github_output("archive-path", str(archive_path))
        write_github_output("archive-sha256", "")
        write_github_output("archive-name", archive_name)
        return

    run_cargo_build(nif_crate_name, nif_crate_path, target)

    # The Rust crate produces the lib with platform-conventional name.
    # Cargo cdylib for `<nif_crate_name>` produces `lib<nif_crate_name>.{ext}` on unix, `<nif_crate_name>.dll` on windows.
    release_dir = cargo_release_dir(target)
    source_lib = release_dir / (f"{nif_crate_name}.dll" if ext == "dll" else f"lib{nif_crate_name}.{ext}")
    if not source_lib.is_file():
        print(f"Error: built NIF library not found at {source_lib}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # The tar.gz contains the library file under its renamed RustlerPrecompiled name.
    # RustlerPrecompiled expects the archive's interior file to be the lib (not a subdir).
    renamed_lib_name = f"lib{nif_crate_name}-v{nif_version}-nif-{nif_api_version}-{target}.{ext}"
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
