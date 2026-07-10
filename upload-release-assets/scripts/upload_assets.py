#!/usr/bin/env python3
"""Upload a list of files (literal paths or globs) to a GitHub Release.

Inputs (env vars):
    INPUT_TAG: release tag (required)
    INPUT_ASSETS: newline- or comma-separated list of paths / glob patterns (required)
    INPUT_CLOBBER: "true" to pass --clobber to gh (default true)
    INPUT_FAIL_IF_EMPTY: "true" to exit 1 if no files matched (default true)
    INPUT_WORKING_DIRECTORY: base directory for relative globs (default ".")
    INPUT_DRY_RUN: "true" to skip the actual upload (default false)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def env_str(key: str, default: str = "") -> str:
    value = os.environ.get(key, default) or default
    return value.strip()


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "y", "on"}


def parse_assets(raw: str) -> list[str]:
    """Split on commas and newlines, drop blanks and `#` comments."""
    normalized = raw.replace(",", "\n")
    patterns: list[str] = []
    for line in normalized.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        patterns.append(entry)
    return patterns


def expand_patterns(patterns: list[str], base: Path) -> list[Path]:
    """Expand each pattern relative to `base`, keep only existing files, dedup, sort."""
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in patterns:
        candidate = base / pattern
        if candidate.is_file():
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(candidate)
            continue
        for match in sorted(base.glob(pattern)):
            if not match.is_file():
                continue
            resolved = match.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(match)
    return files


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        if "\n" in value:
            delimiter = f"GH_DELIM_{name.upper()}"
            handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")
        else:
            handle.write(f"{name}={value}\n")


def upload_one(tag: str, file: Path, clobber: bool) -> None:
    cmd = ["gh", "release", "upload", tag, str(file)]
    if clobber:
        cmd.append("--clobber")
    env = os.environ.copy()
    if not env.get("GH_TOKEN"):
        token = env.get("GITHUB_TOKEN") or env.get("INPUT_TOKEN") or ""
        if token:
            env["GH_TOKEN"] = token
    subprocess.run(cmd, check=True, env=env)


def main() -> None:
    tag = env_str("INPUT_TAG")
    assets_raw = env_str("INPUT_ASSETS")
    clobber = env_bool("INPUT_CLOBBER", default=True)
    fail_if_empty = env_bool("INPUT_FAIL_IF_EMPTY", default=True)
    working_directory = env_str("INPUT_WORKING_DIRECTORY", ".") or "."
    dry_run = env_bool("INPUT_DRY_RUN", default=False)

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)
    if not assets_raw:
        print("Error: INPUT_ASSETS is required", file=sys.stderr)
        sys.exit(1)

    base = Path(working_directory).resolve()
    if not base.is_dir():
        print(f"Error: working-directory does not exist: {base}", file=sys.stderr)
        sys.exit(1)

    patterns = parse_assets(assets_raw)
    if not patterns:
        print("Error: INPUT_ASSETS contained no patterns after parsing", file=sys.stderr)
        sys.exit(1)

    files = expand_patterns(patterns, base)

    if not files:
        message = f"No files matched the asset patterns under {base}"
        if fail_if_empty and not dry_run:
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)
        print(f"::warning::{message}")
        write_output("uploaded-count", "0")
        write_output("uploaded-paths", "")
        return

    if dry_run:
        print(f"[dry-run] Would upload {len(files)} file(s) to release {tag}:")
        for file in files:
            print(f"  {file}")
        write_output("uploaded-count", "0")
        write_output("uploaded-paths", "\n".join(str(file) for file in files))
        return

    print(f"Uploading {len(files)} file(s) to release {tag}...")
    uploaded: list[Path] = []
    for file in files:
        print(f"  uploading {file}")
        upload_one(tag, file, clobber)
        uploaded.append(file)

    print(f"Uploaded {len(uploaded)} file(s) to release {tag}")
    write_output("uploaded-count", str(len(uploaded)))
    write_output("uploaded-paths", "\n".join(str(file) for file in uploaded))


if __name__ == "__main__":
    main()
