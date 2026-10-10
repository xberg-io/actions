#!/usr/bin/env python3
"""Build a Rust FFI library via cargo and emit outputs to GITHUB_OUTPUT."""

import dataclasses
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_TAIL_LINES = 50
_NATIVE_STATIC_LIBS_FILENAME = "native-static-libs.txt"
_NATIVE_STATIC_LIBS_MARKER = "native-static-libs:"


@dataclasses.dataclass(frozen=True)
class BuildConfig:
    """All configuration for a single cargo FFI build."""

    crate_name: str
    features: str
    target: str
    build_profile: str
    verbose: bool
    additional_flags: str
    manifest_path: str
    disable_sccache: bool
    cargo_target_dir: str
    glibc_version: str
    require_static: bool = False

    @classmethod
    def from_env(cls) -> "BuildConfig":
        """Construct a BuildConfig by reading environment variables."""
        env = os.environ
        return cls(
            crate_name=env.get("CRATE_NAME", ""),
            features=env.get("FEATURES", ""),
            target=env.get("TARGET", ""),
            build_profile=env.get("BUILD_PROFILE", "release"),
            verbose=env.get("VERBOSE", "true").lower() == "true",
            additional_flags=env.get("ADDITIONAL_FLAGS", ""),
            manifest_path=env.get("MANIFEST_PATH", ""),
            disable_sccache=env.get("DISABLE_SCCACHE", "true").lower() == "true",
            cargo_target_dir=env.get("CARGO_TARGET_DIR", ""),
            glibc_version=env.get("GLIBC_VERSION", ""),
            require_static=env.get("REQUIRE_STATIC", "false").lower() == "true",
        )


def validate_inputs(crate_name: str, manifest_path: str) -> None:
    """Validate build inputs before invoking cargo.

    Raises SystemExit with a non-zero code on validation failure.
    """
    print("=== Validating FFI build inputs ===")
    print(f"Crate: {crate_name}")

    if manifest_path:
        if not Path(manifest_path).is_file():
            print(f"Error: manifest-path '{manifest_path}' does not exist", file=sys.stderr)
            raise SystemExit(1)
        print(f"Manifest: {manifest_path}")
    elif Path(f"crates/{crate_name}/Cargo.toml").is_file():
        print(f"Found crate at crates/{crate_name}/")
    else:
        print(
            f"Error: Crate '{crate_name}' not found at crates/{crate_name}/Cargo.toml",
            file=sys.stderr,
        )
        print("Hint: Use manifest-path input for non-standard crate locations", file=sys.stderr)
        raise SystemExit(1)

    print("Validation passed")


def build_cargo_args(
    *,
    crate_name: str,
    manifest_path: str,
    build_profile: str,
    features: str,
    target: str,
    verbose: bool,
    additional_flags: str,
    glibc_version: str = "",
) -> list[str]:
    """Construct the cargo build argument list from build parameters.

    `--locked` is always passed so the committed `Cargo.lock` is respected; a
    broken or stale upstream release on crates.io cannot silently substitute
    itself for a pinned dep at build time. Mirror this pattern in every action
    that wraps `cargo build`.

    For linux-gnu targets with glibc_version set, appends .<glibc_version> to
    the target triple for zigbuild to enforce a glibc floor.
    """
    args: list[str] = ["build", "--locked"]

    if manifest_path:
        args += ["--manifest-path", manifest_path]
    else:
        args += ["--package", crate_name]

    if build_profile == "release":
        args.append("--release")

    if features:
        args += ["--features", features]

    use_zigbuild = bool(target and "linux-gnu" in target and glibc_version)

    if target:
        if use_zigbuild:
            glibc_suffixed_target = f"{target}.{glibc_version}"
            args += ["--target", glibc_suffixed_target]
        else:
            args += ["--target", target]

    if verbose:
        args.append("-vv")

    if additional_flags:
        additional_args = shlex.split(additional_flags)
        args += [argument for argument in additional_args if argument != "--locked"]

    return args


def find_shared_library(target_dir: Path, crate_name: str) -> Path | None:
    """Search for the compiled shared-library artifact in ``target_dir``."""
    lib_stem = crate_name.replace("-", "_")
    candidates = [
        target_dir / f"lib{lib_stem}.so",
        target_dir / f"lib{lib_stem}.dylib",
        target_dir / f"{lib_stem}.dll",
        target_dir / f"lib{lib_stem}.dll",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    for extension in [".so", ".dylib", ".dll"]:
        matches = [path for path in target_dir.glob(f"*{extension}") if not path.name.endswith(".dll.lib")]
        if matches:
            return matches[0]

    return None


def find_static_library(target_dir: Path, crate_name: str) -> Path | None:
    """Search for the compiled static-library artifact in ``target_dir``."""
    lib_stem = crate_name.replace("-", "_")
    candidates = [
        target_dir / f"lib{lib_stem}.a",
        target_dir / f"{lib_stem}.lib",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def find_library(target_dir: Path, crate_name: str) -> Path | None:
    """Search for the preferred backward-compatible library artifact.

    Shared libraries remain preferred so the long-standing ``library-path``
    output retains its meaning. Static-only targets fall back to the archive.
    """
    return find_shared_library(target_dir, crate_name) or find_static_library(target_dir, crate_name)


def parse_native_static_libs(output: str) -> str | None:
    """Extract the final native-static-libs record from cargo/rustc output."""
    found = None
    for line in output.splitlines():
        if _NATIVE_STATIC_LIBS_MARKER not in line:
            continue
        flags = line.split(_NATIVE_STATIC_LIBS_MARKER, 1)[1].strip()
        if flags:
            found = flags
    return found


def write_native_static_libs(target_dir: Path, flags: str) -> Path:
    """Write the native libraries needed when linking the static archive."""
    path = target_dir / _NATIVE_STATIC_LIBS_FILENAME
    path.write_text(f"{flags}\n", encoding="utf-8")
    return path


def diagnose_build_failure(log_content: str) -> None:
    """Print diagnostic information extracted from a failed build log."""
    lines = log_content.splitlines()
    tail = lines[-_TAIL_LINES:] if len(lines) > _TAIL_LINES else lines
    print("Last 50 lines of build output:")
    print("\n".join(tail))
    print()
    print("Checking for common errors:")

    link_errors = [line for line in lines if "link" in line.lower() and "error" in line.lower()]
    if link_errors:
        for line in link_errors[:5]:
            print(line)
        print("Linking errors detected. Check library paths and dependencies.")

    missing_dep_lines = [line for line in lines if "could not find" in line.lower()]
    if missing_dep_lines:
        for line in missing_dep_lines[:5]:
            print(line)
        print("Missing dependencies detected.")


def _print_build_environment(config: BuildConfig) -> None:
    """Print build tool versions and relevant environment settings."""
    rust_ver = subprocess.run(
        ["rustc", "--version"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    cargo_ver = subprocess.run(
        ["cargo", "--version"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    print(f"Rust version: {rust_ver}")
    print(f"Cargo version: {cargo_ver}")
    print(f"Working directory: {Path.cwd()}")
    print(f"CARGO_TARGET_DIR: {config.cargo_target_dir or '<not set>'}")
    if config.target:
        print(f"Target: {config.target}")


def _build_env(config: BuildConfig) -> dict[str, str]:
    """Return a modified copy of the environment with sccache disabled if requested."""
    env = dict(os.environ)
    if config.disable_sccache:
        env["RUSTC_WRAPPER"] = ""
        env["CARGO_BUILD_RUSTC_WRAPPER"] = ""
        env["SCCACHE_GHA_ENABLED"] = "false"
    return env


def assemble_cargo_cmd(
    cargo_args: list[str],
    use_zigbuild: bool,
    capture_static_metadata: bool = False,
) -> list[str]:
    """Build the argv list for the cargo invocation.

    `cargo zigbuild` REPLACES the `build` subcommand, so the leading "build"
    in ``cargo_args`` (which always starts with it) is dropped when zigbuilding —
    ``cargo zigbuild build ...`` errors with "unexpected argument 'build'".
    """
    if use_zigbuild:
        return ["cargo", "zigbuild", *cargo_args[1:]]
    if capture_static_metadata:
        return [
            "cargo",
            "rustc",
            *cargo_args[1:],
            "--lib",
            "--",
            "--print",
            "native-static-libs",
        ]
    return ["cargo", *cargo_args]


def _run_cargo_build(
    cargo_args: list[str],
    build_env: dict[str, str],
    use_zigbuild: bool = False,
    capture_static_metadata: bool = False,
) -> str:
    """Run cargo (or cargo zigbuild) with the given args, streaming output to stdout.

    Raises SystemExit(1) on build failure.
    """
    log_lines: list[str] = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as log_file:
        log_path = Path(log_file.name)

    try:
        cmd = assemble_cargo_cmd(cargo_args, use_zigbuild, capture_static_metadata)

        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=build_env,
        ) as proc:
            assert proc.stdout is not None  # noqa: S101
            for line in proc.stdout:
                print(line, end="")
                log_lines.append(line)

        log_content = "".join(log_lines)
        log_path.write_text(log_content, encoding="utf-8")
    finally:
        log_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        print()
        print("=== Build Failed ===")
        print(f"Command: {' '.join(cmd)}")
        print()
        diagnose_build_failure(log_content)
        raise SystemExit(1)

    return log_content


def _full_target_dir(config: BuildConfig) -> Path:
    """Compute the cargo output directory for the given build configuration.

    If CARGO_TARGET_DIR is set, use it as the base. Otherwise, if manifest_path
    is provided, anchor the target dir at manifest_path.parent / target.
    Otherwise, use ./target as the base.
    """
    if config.cargo_target_dir:
        base = config.cargo_target_dir
    elif config.manifest_path:
        manifest = Path(config.manifest_path)
        base = str(manifest.parent / "target")
    else:
        base = "target"

    target_subdir = f"{config.target}/" if config.target else ""
    profile_dir = "release" if config.build_profile == "release" else "debug"
    return Path(base) / f"{target_subdir}{profile_dir}"


def _report_library(found_lib: Path | None, target_dir: Path) -> None:
    """Print the found library path and size, or list fallback candidates."""
    if found_lib is not None:
        print(f"Found library: {found_lib}")
        size_kb = found_lib.stat().st_size / 1024
        print(f"  size: {size_kb:.1f}K")
        return

    print(f"Could not find expected library artifact. Listing library files in {target_dir}:")
    if not target_dir.is_dir():
        print(f"Directory does not exist: {target_dir}")
        return

    all_libs: list[Path] = []
    for extension in [".so", ".dylib", ".dll", ".a"]:
        all_libs.extend(target_dir.glob(f"*{extension}"))

    if all_libs:
        for lib in all_libs:
            print(f"  {lib}")
    else:
        print(f"No library files found in {target_dir}")


def _write_github_output(
    shared_library: Path | None,
    static_library: Path | None,
    native_static_libs: Path | None,
    target_dir: Path,
) -> None:
    """Write all artifact paths to GITHUB_OUTPUT (or stdout if unset)."""
    preferred_library = shared_library or static_library
    outputs = {
        "library-path": str(preferred_library) if preferred_library is not None else "",
        "shared-library-path": str(shared_library) if shared_library is not None else "",
        "static-library-path": str(static_library) if static_library is not None else "",
        "native-static-libs-path": str(native_static_libs) if native_static_libs is not None else "",
        "target-dir": str(target_dir),
    }
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a") as output_file:
            output_file.writelines(f"{name}={value}\n" for name, value in outputs.items())
    else:
        for name, value in outputs.items():
            print(f"{name}={value}")


def main() -> None:
    """Orchestrate validation, cargo build, artifact discovery, and output writing."""
    validate_only = "--validate-only" in sys.argv

    config = BuildConfig.from_env()

    if not config.crate_name:
        print("Error: CRATE_NAME is required", file=sys.stderr)
        raise SystemExit(1)

    validate_inputs(config.crate_name, config.manifest_path)

    if validate_only:
        return

    print("=== Building Rust FFI library ===")

    cargo_args = build_cargo_args(
        crate_name=config.crate_name,
        manifest_path=config.manifest_path,
        build_profile=config.build_profile,
        features=config.features,
        target=config.target,
        verbose=config.verbose,
        additional_flags=config.additional_flags,
        glibc_version=config.glibc_version,
    )

    use_zigbuild = bool("linux-gnu" in config.target and config.glibc_version)
    if use_zigbuild:
        print(f"[build-rust-ffi] glibc floor: {config.glibc_version}")

    capture_static_metadata = config.require_static and not use_zigbuild
    target_dir = _full_target_dir(config)
    (target_dir / _NATIVE_STATIC_LIBS_FILENAME).unlink(missing_ok=True)
    print(f"Build command: {' '.join(assemble_cargo_cmd(cargo_args, use_zigbuild, capture_static_metadata))}")
    print()
    print("=== Build Environment ===")
    _print_build_environment(config)
    print()

    build_log = _run_cargo_build(
        cargo_args,
        _build_env(config),
        use_zigbuild=use_zigbuild,
        capture_static_metadata=capture_static_metadata,
    )

    print()
    print("=== Build Successful ===")
    print(f"Target directory: {target_dir}")
    print()

    shared_library = find_shared_library(target_dir, config.crate_name)
    static_library = find_static_library(target_dir, config.crate_name)
    if config.require_static and static_library is None:
        print(f"Error: required static library not found in {target_dir}", file=sys.stderr)
        raise SystemExit(1)

    native_static_libs = None
    if capture_static_metadata:
        native_flags = parse_native_static_libs(build_log)
        if native_flags is None:
            print("Error: rustc did not report native-static-libs", file=sys.stderr)
            raise SystemExit(1)
        native_static_libs = write_native_static_libs(target_dir, native_flags)

    _report_library(shared_library or static_library, target_dir)
    if static_library is not None:
        print(f"Static library: {static_library}")
    if native_static_libs is not None:
        print(f"Native static-link metadata: {native_static_libs}")
    elif config.require_static and use_zigbuild:
        print("Native static-link metadata unavailable: cargo-zigbuild cannot forward rustc --print")
    _write_github_output(shared_library, static_library, native_static_libs, target_dir)

    print()
    print("=== FFI Build Complete ===")


if __name__ == "__main__":
    main()
