#!/usr/bin/env python3
"""Docker-based musl cross-compilation helper for cdylib Rust crates.

When targeting a musl triple (*-linux-musl), builds inside an Alpine container
with the proper toolchain to avoid host linker incompatibilities.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def is_musl_target(target: str) -> bool:
    """Check if target is a musl triple."""
    return "linux-musl" in target


def get_alpine_arch(target: str) -> str:
    """Map Rust target to Alpine architecture."""
    if "aarch64" in target or "arm64" in target:
        return "aarch64"
    if "x86_64" in target:
        return "x86_64"
    raise ValueError(f"Unsupported musl target for Alpine: {target}")


def build_in_docker(
    crate_name: str,
    target: str,
    env_vars: dict[str, str] | None = None,
) -> None:
    """Build a Rust cdylib crate inside Alpine container for musl target.

    Args:
        crate_name: Cargo package name (e.g., "kreuzberg-ffi")
        target: Rust target triple (e.g., "aarch64-unknown-linux-musl")
        env_vars: Optional dict of environment variables to pass to cargo

    Raises:
        subprocess.CalledProcessError: If build fails
    """
    if not is_musl_target(target):
        raise ValueError(f"Docker build is only for musl targets, got {target}")

    get_alpine_arch(target)  # Validates architecture is supported
    # rust:1-alpine3.21 ships with rustup + cargo pre-installed; plain
    # alpine:3.21 does not, so `rustup target add` fails with exit 127.
    image = "rust:1-alpine3.21"

    # Prepare build environment
    cwd = Path.cwd().resolve()

    # Build command inside container
    build_cmd = [
        "cargo",
        "build",
        "-p",
        crate_name,
        "--release",
        "--target",
        target,
    ]

    # Add environment variables to build command if provided
    env_flags = []
    if env_vars:
        for key, val in env_vars.items():
            env_flags.extend(["-e", f"{key}={val}"])

    # Docker command: mount repo, install toolchain, build
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{cwd}:/src",
        "-w",
        "/src",
        *env_flags,
        image,
        "sh",
        "-c",
        f"""
set -e
apk add --no-cache \\
  curl gcc musl-dev openssl-dev perl linux-headers
rustup target add {target}
{" ".join(build_cmd)}
""",
    ]

    print(f"[musl-builder] Building for {target} in Alpine container")
    print(f"[musl-builder] Running: docker run ... {' '.join(build_cmd)}")
    subprocess.run(docker_cmd, check=True)


def build_or_fallback(
    crate_name: str,
    target: str,
    manifest_path: Path | None = None,
    env_vars: dict[str, str] | None = None,
) -> None:
    """Build a cdylib crate, using Docker for musl targets if necessary.

    For musl targets: builds in Alpine container.
    For other targets: builds natively on the host.

    Args:
        crate_name: Cargo package name
        target: Rust target triple
        manifest_path: Optional path to Cargo.toml (used for native builds only)
        env_vars: Optional dict of environment variables to pass to cargo
    """
    if is_musl_target(target):
        build_in_docker(crate_name, target, env_vars)
    else:
        # Native build
        build_cmd = ["cargo", "build", "-p", crate_name, "--release", "--target", target]
        if manifest_path:
            build_cmd.extend(["--manifest-path", str(manifest_path)])

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        print(f"[musl-builder] Building for {target} natively on host")
        print(f"[musl-builder] Running: {' '.join(build_cmd)}")
        subprocess.run(build_cmd, check=True, env=env)
