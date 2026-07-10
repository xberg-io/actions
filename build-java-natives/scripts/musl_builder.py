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
        crate_name: Cargo package name (e.g., "xberg-ffi")
        target: Rust target triple (e.g., "aarch64-unknown-linux-musl")
        env_vars: Optional dict of environment variables to pass to cargo

    Raises:
        subprocess.CalledProcessError: If build fails
    """
    if not is_musl_target(target):
        raise ValueError(f"Docker build is only for musl targets, got {target}")

    get_alpine_arch(target)
    image = "rust:1-alpine3.21"

    cwd = Path.cwd().resolve()

    build_cmd = [
        "cargo",
        "build",
        "--locked",
        "-p",
        crate_name,
        "--release",
        "--target",
        target,
    ]

    merged_env: dict[str, str] = {"RUSTFLAGS": "-C target-feature=-crt-static"}
    if env_vars:
        merged_env.update(env_vars)
    env_flags: list[str] = []
    for key, val in merged_env.items():
        env_flags.extend(["-e", f"{key}={val}"])

    linker_env_var = f"CARGO_TARGET_{target.upper().replace('-', '_')}_LINKER=gcc"
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
  curl gcc musl-dev perl linux-headers
rustup target add {target}
{linker_env_var} {" ".join(build_cmd)}
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
    glibc_version: str = "",
) -> None:
    """Build a cdylib crate, using Docker for musl targets or zigbuild for glibc targets.

    For musl targets: builds in Alpine container.
    For gnu targets: builds with cargo zigbuild (glibc floor lowering).
    For other targets: builds natively on the host.

    Args:
        crate_name: Cargo package name
        target: Rust target triple
        manifest_path: Optional path to Cargo.toml (used for native builds only)
        env_vars: Optional dict of environment variables to pass to cargo
        glibc_version: glibc version for gnu targets (e.g. "2.28"); empty = native cargo build
    """
    if is_musl_target(target):
        build_in_docker(crate_name, target, env_vars)
    else:
        use_zigbuild = "linux-gnu" in target and glibc_version
        glibc_suffixed_target = f"{target}.{glibc_version}" if use_zigbuild else target

        if use_zigbuild:
            build_cmd = [
                "cargo",
                "zigbuild",
                "--locked",
                "-p",
                crate_name,
                "--release",
                "--target",
                glibc_suffixed_target,
            ]
            builder = "cargo zigbuild"
        else:
            build_cmd = ["cargo", "build", "--locked", "-p", crate_name, "--release", "--target", target]
            builder = "cargo build"

        if manifest_path:
            build_cmd.extend(["--manifest-path", str(manifest_path)])

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        print(f"[musl-builder] Building for {target} natively on host ({builder})")
        if use_zigbuild:
            print(f"[musl-builder] glibc floor: {glibc_version} (target: {glibc_suffixed_target})")
        print(f"[musl-builder] Running: {' '.join(build_cmd)}")
        subprocess.run(build_cmd, check=True, env=env)
