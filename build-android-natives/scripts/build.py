#!/usr/bin/env python3
"""Build a Rust crate for Android ABIs using cargo-ndk and stage the libraries.

Stages at: {output-dir}/{abi}/lib{lib-name}.so

Inputs (env vars):
    INPUT_CRATE_NAME: cargo package name (required)
    INPUT_LIB_NAME: library base name (default = crate-name with - → _)
    INPUT_ABIS: comma-separated Android ABIs (default arm64-v8a,x86_64)
    INPUT_API_LEVEL: Android API level (default 21)
    INPUT_OUTPUT_DIR: staging root (default dist/android-natives)
    INPUT_DRY_RUN: "true" to skip cargo build (default false)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ABI_TO_RUST_TARGET = {
    "arm64-v8a": "aarch64-linux-android",
    "x86_64": "x86_64-linux-android",
    "x86": "i686-linux-android",
    "armeabi-v7a": "armv7-linux-androideabi",
}


def cargo_release_dir(target: str) -> Path:
    return Path("target") / target / "release"


def run_command(cmd: list[str]) -> None:
    print(f"[build-android-natives] Running: {' '.join(cmd)}")
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
    crate_name = ensure_input("INPUT_CRATE_NAME", os.environ.get("INPUT_CRATE_NAME", ""))
    lib_name = os.environ.get("INPUT_LIB_NAME", "") or crate_name.replace("-", "_")
    abis_str = os.environ.get("INPUT_ABIS", "arm64-v8a,x86_64")
    api_level = os.environ.get("INPUT_API_LEVEL", "21")
    output_dir = Path(os.environ.get("INPUT_OUTPUT_DIR", "") or "dist/android-natives")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    abis = [a.strip() for a in abis_str.split(",") if a.strip()]
    if not abis:
        print("Error: no ABIs specified", file=sys.stderr)
        sys.exit(1)

    rust_targets_with_none: list[str | None] = [ABI_TO_RUST_TARGET.get(abi) for abi in abis]
    if None in rust_targets_with_none:
        invalid = [abis[i] for i, t in enumerate(rust_targets_with_none) if t is None]
        print(f"Error: unknown ABIs: {', '.join(invalid)}", file=sys.stderr)
        sys.exit(1)
    rust_targets: list[str] = [t for t in rust_targets_with_none if t is not None]

    if dry_run:
        print("[build-android-natives] dry-run: skipping cargo-ndk build")
        print(f"  crate:     {crate_name}")
        print(f"  lib:       {lib_name}")
        print(f"  abis:      {', '.join(abis)}")
        print(f"  api-level: {api_level}")
        print(f"  output:    {output_dir}")
        for abi, _target in zip(abis, rust_targets, strict=True):
            lib_path = output_dir / abi / f"lib{lib_name}.so"
            print(f"    {abi:12} -> {lib_path}")
        write_github_output("output-dir", str(output_dir.resolve() if output_dir.exists() else output_dir))
        return

    # Add all targets needed
    unique_targets = list(dict.fromkeys(rust_targets))
    for target in unique_targets:
        run_command(["rustup", "target", "add", target])

    # Check if cargo-ndk is already installed
    try:
        subprocess.run(["which", "cargo-ndk"], check=True, capture_output=True)
        print("[build-android-natives] cargo-ndk already installed")
    except subprocess.CalledProcessError:
        print("[build-android-natives] Installing cargo-ndk...")
        run_command(["cargo", "install", "cargo-ndk", "--locked"])

    # Build for each ABI
    for abi, _target in zip(abis, rust_targets, strict=True):
        cmd = [
            "cargo",
            "ndk",
            "--target",
            abi,
            "--platform",
            api_level,
            "-o",
            str(output_dir),
            "build",
            "-p",
            crate_name,
            "--release",
        ]
        run_command(cmd)

    print(f"[build-android-natives] staged libraries under: {output_dir.resolve()}")

    write_github_output("output-dir", str(output_dir.resolve()))


if __name__ == "__main__":
    main()
