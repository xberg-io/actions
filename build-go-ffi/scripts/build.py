#!/usr/bin/env python3
"""Build a Rust FFI crate for one target and package it for the Go cgo binding.

Reads inputs from INPUT_* environment variables (GitHub Actions composite-action
convention), invokes ``cargo build`` for the requested Rust target triple,
locates the resulting shared library, copies it together with the C header into
a staging directory, and emits a deterministic tar.gz archive plus its SHA256
digest.

Usage (GitHub Actions via env vars):
    INPUT_TARGET=x86_64-unknown-linux-gnu \
    INPUT_CRATE_NAME=xberg-ffi \
    INPUT_HEADER_PATH=crates/xberg-ffi/include/xberg.h \
    INPUT_OUTPUT_DIR=dist/go-ffi \
    python3 build.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

CHUNK_SIZE = 1 << 20


def library_filename(lib_name: str, target: str) -> str:
    """Return the platform-conventional shared library filename for ``target``."""
    if "windows" in target:
        return f"{lib_name}.dll"
    if "apple" in target or "darwin" in target:
        return f"lib{lib_name}.dylib"
    return f"lib{lib_name}.so"


def cargo_release_dir(target: str) -> Path:
    """Return ``target/<triple>/release`` for the requested target triple."""
    return Path("target") / target / "release"


def run_cargo_build(crate_name: str, target: str, glibc_version: str = "") -> None:
    """Invoke cargo build (or cargo zigbuild for linux-gnu with glibc floor).

    For linux-gnu targets with glibc_version set, uses cargo zigbuild with
    --target <triple>.<glibc_version> for glibc floor lowering. Artifacts
    are still emitted to target/<base-triple>/release.
    """
    use_zigbuild = "linux-gnu" in target and glibc_version
    glibc_suffixed_target = f"{target}.{glibc_version}" if use_zigbuild else target

    if use_zigbuild:
        cmd = ["cargo", "zigbuild", "--locked", "-p", crate_name, "--release", "--target", glibc_suffixed_target]
        print(f"[build-go-ffi] glibc floor: {glibc_version} (target: {glibc_suffixed_target})")
    else:
        cmd = ["cargo", "build", "--locked", "-p", crate_name, "--release", "--target", target]

    print(f"[build-go-ffi] Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def compute_sha256(path: Path) -> str:
    """Return the hex-encoded SHA256 digest of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_github_output(name: str, value: str) -> None:
    """Append ``name=value`` to ``$GITHUB_OUTPUT`` (or stdout when unset)."""
    sink = os.environ.get("GITHUB_OUTPUT", "")
    line = f"{name}={value}\n"
    if sink:
        with Path(sink).open("a", encoding="utf-8") as handle:
            handle.write(line)
    else:
        sys.stdout.write(line)


def ensure_input(name: str, value: str) -> str:
    """Validate that a required INPUT_* variable is non-empty."""
    if not value:
        print(f"Error: {name} is required", file=sys.stderr)
        sys.exit(1)
    return value


def stage_artifacts(library: Path, header: Path, staging_dir: Path) -> None:
    """Copy the library and header into ``staging_dir`` (created fresh)."""
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)
    shutil.copy2(library, staging_dir / library.name)
    shutil.copy2(header, staging_dir / header.name)


def create_archive(archive_path: Path, staging_dir: Path) -> None:
    """Create a gzip tar archive containing the staging directory tree."""
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(staging_dir, arcname=staging_dir.name)


def main() -> None:
    target = ensure_input("INPUT_TARGET", os.environ.get("INPUT_TARGET", ""))
    crate_name = os.environ.get("INPUT_CRATE_NAME", "xberg-ffi") or "xberg-ffi"
    lib_name = os.environ.get("INPUT_LIB_NAME", "") or crate_name.replace("-", "_")
    header_path = Path(os.environ.get("INPUT_HEADER_PATH", "") or "crates/xberg-ffi/include/xberg.h")
    output_dir = Path(os.environ.get("INPUT_OUTPUT_DIR", "") or "dist/go-ffi")
    archive_name = os.environ.get("INPUT_ARCHIVE_NAME", "") or f"{lib_name}-{target}.tar.gz"
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    glibc_version = os.environ.get("INPUT_GLIBC_VERSION", "")

    archive_path = (output_dir / archive_name).resolve()
    staging_dir = output_dir / f"{lib_name}-{target}"

    if dry_run:
        print("[build-go-ffi] dry-run: skipping cargo build")
        print(f"  target:       {target}")
        print(f"  crate:        {crate_name}")
        print(f"  lib-name:     {lib_name}")
        print(f"  header-path:  {header_path}")
        print(f"  archive-path: {archive_path}")
        if glibc_version:
            print(f"  glibc-version: {glibc_version}")
        write_github_output("archive-path", str(archive_path))
        write_github_output("archive-sha256", "")
        return

    if not header_path.is_file():
        print(f"Error: header not found at {header_path}", file=sys.stderr)
        sys.exit(1)

    run_cargo_build(crate_name, target, glibc_version)

    release_dir = cargo_release_dir(target)
    library = release_dir / library_filename(lib_name, target)
    if not library.is_file():
        print(f"Error: built library not found at {library}", file=sys.stderr)
        sys.exit(1)

    stage_artifacts(library, header_path, staging_dir)
    create_archive(archive_path, staging_dir)
    digest = compute_sha256(archive_path)

    print(f"[build-go-ffi] archive: {archive_path}")
    print(f"[build-go-ffi] sha256:  {digest}")

    write_github_output("archive-path", str(archive_path))
    write_github_output("archive-sha256", digest)


if __name__ == "__main__":
    main()
