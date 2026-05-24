#!/usr/bin/env python3
"""Verify a GitHub Release contains every expected asset.

Inputs (env vars):
    INPUT_TAG: release tag (required)
    INPUT_EXPECTED_ASSETS: newline-separated list of fnmatch patterns (required)
    INPUT_MIN_SIZE_BYTES: minimum size for any matched asset (default 0)
    INPUT_DRY_RUN: "true" to skip the failure exit (default false)
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def env_str(key: str, default: str = "") -> str:
    value = os.environ.get(key, default) or default
    return value.strip()


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "y", "on"}


def env_int(key: str, default: int = 0) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_expected(raw: str) -> list[str]:
    """Split on newlines, drop blanks and `#` comments."""
    patterns: list[str] = []
    for line in raw.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        patterns.append(entry)
    return patterns


def fetch_release_assets(tag: str) -> list[dict[str, Any]]:
    # Pass -R explicitly: this action does not check out the repo, so `gh`
    # cannot infer the remote from the working directory. GITHUB_REPOSITORY
    # is always set in GitHub Actions; falling back to GH_REPO covers the
    # rare local-test path where someone exports it manually.
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GH_REPO")
    argv = ["gh", "release", "view", tag, "--json", "assets"]
    if repo:
        argv.extend(["-R", repo])
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Error: gh release view failed for tag {tag}: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"Error: gh returned non-JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    assets = payload.get("assets") or []
    return [a for a in assets if isinstance(a, dict)]


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        if "\n" in value:
            delimiter = f"GH_DELIM_{name.upper().replace('-', '_')}"
            handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")
        else:
            handle.write(f"{name}={value}\n")


def main() -> None:
    tag = env_str("INPUT_TAG")
    expected_raw = env_str("INPUT_EXPECTED_ASSETS")
    min_size = env_int("INPUT_MIN_SIZE_BYTES", 0)
    dry_run = env_bool("INPUT_DRY_RUN", default=False)

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)
    if not expected_raw:
        print("Error: INPUT_EXPECTED_ASSETS is required", file=sys.stderr)
        sys.exit(1)

    patterns = parse_expected(expected_raw)
    if not patterns:
        print("Error: INPUT_EXPECTED_ASSETS contained no patterns after parsing", file=sys.stderr)
        sys.exit(1)

    assets = fetch_release_assets(tag)
    print(f"Release {tag} has {len(assets)} asset(s):")
    for asset in assets:
        print(f"  {asset.get('name')} ({asset.get('size', 0)} bytes)")

    missing: list[str] = []
    verified = 0
    for pattern in patterns:
        matches = [a for a in assets if fnmatch.fnmatch(str(a.get("name", "")), pattern)]
        if min_size > 0:
            matches = [a for a in matches if int(a.get("size", 0)) >= min_size]
        if matches:
            verified += 1
            print(f"  ✓ pattern matched: {pattern} ({len(matches)} asset(s))")
        else:
            missing.append(pattern)
            size_note = f" (size >= {min_size} bytes)" if min_size > 0 else ""
            print(f"  ✗ pattern NOT matched{size_note}: {pattern}", file=sys.stderr)

    write_output("verified-count", str(verified))
    write_output("missing", "\n".join(missing))

    if missing and not dry_run:
        print(f"Error: {len(missing)} expected pattern(s) had no matching asset", file=sys.stderr)
        sys.exit(1)

    if missing:
        print(f"[dry-run] would fail with {len(missing)} missing pattern(s)")


if __name__ == "__main__":
    main()
