#!/usr/bin/env python3
"""Find and validate dist files for PyPI publishing, with version-level idempotency.

Usage (GitHub Actions via env vars):
    INPUT_PACKAGES_DIR=dist INPUT_DRY_RUN=false python3 publish.py

Outputs `version_published=true` to `$GITHUB_OUTPUT` when the discovered
version is already on the configured index, so the calling action can skip
the `uv publish` invocation (which would otherwise 400 with "File already
exists").
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

_WHEEL_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.\-]+?)-(?P<ver>[^-]+)(-\d.*)?-[^-]+-[^-]+-[^-]+\.whl$")
_SDIST_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.\-]+?)-(?P<ver>[^-]+)\.tar\.gz$")


def find_dist_files(directory: Path) -> list[Path]:
    """Return all .whl and .tar.gz files found directly in directory."""
    files: list[Path] = []
    files.extend(sorted(directory.glob("*.whl")))
    files.extend(sorted(directory.glob("*.tar.gz")))
    return files


def validate_dist_dir(directory: Path) -> list[Path]:
    """Validate the dist directory and return its dist files."""
    if not directory.exists():
        print(f"Error: packages directory does not exist: {directory}", file=sys.stderr)
        sys.exit(1)

    files = find_dist_files(directory)
    if not files:
        print(f"Error: no .whl or .tar.gz files found in {directory}", file=sys.stderr)
        sys.exit(1)

    return files


def parse_name_version(filename: str) -> tuple[str, str] | None:
    """Return (project-name, version) parsed from a wheel or sdist filename."""
    if match := _WHEEL_RE.match(filename):
        return _normalize(match["name"]), match["ver"]
    if match := _SDIST_RE.match(filename):
        return _normalize(match["name"]), match["ver"]
    return None


def _normalize(name: str) -> str:
    """PEP 503 normalization: lowercase, runs of `_.-` collapsed to single `-`."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _upload_url_to_json_base(upload_url: str) -> str:
    """Derive the JSON-API base URL (e.g. https://pypi.org) from an upload URL.

    `https://upload.pypi.org/legacy/`        -> `https://pypi.org`
    `https://test.pypi.org/legacy/`          -> `https://test.pypi.org`
    Anything else: best-effort by stripping leading `upload.` and trailing `/legacy/`.
    """
    base = upload_url.rstrip("/").removesuffix("/legacy")
    return re.sub(r"^([a-z]+://)upload\.", r"\1", base)


def version_already_published(name: str, version: str, upload_url: str) -> bool:
    """Return True when the project+version is already on the registry's JSON API.

    Best-effort: any network failure or non-200/404 response returns False so we
    fall through to the publish attempt rather than skipping incorrectly.
    """
    base = _upload_url_to_json_base(upload_url)
    url = f"{base}/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            return resp.status == 200 and bool(json.loads(resp.read().decode()))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        print(f"Warning: PyPI index check returned HTTP {exc.code} for {url}", file=sys.stderr)
        return False
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Warning: PyPI index check failed for {url}: {exc}", file=sys.stderr)
        return False


def _emit_output(key: str, value: str) -> None:
    """Write a `key=value` line to $GITHUB_OUTPUT (no-op when unset)."""
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def main() -> None:
    packages_dir = Path(os.environ.get("INPUT_PACKAGES_DIR", "dist"))
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    upload_url = os.environ.get("INPUT_REPOSITORY_URL", "https://upload.pypi.org/legacy/")

    files = validate_dist_dir(packages_dir)

    print(f"Found {len(files)} dist file(s) in {packages_dir}:")
    for f in files:
        print(f"  {f.name}")

    if dry_run:
        print("[dry-run] Skipping publish")
        _emit_output("version_published", "false")
        return

    versions: set[tuple[str, str]] = set()
    for f in files:
        if parsed := parse_name_version(f.name):
            versions.add(parsed)
        else:
            print(f"Warning: could not parse name/version from {f.name}", file=sys.stderr)

    if not versions:
        print("Warning: no parseable dist files; skipping idempotency check", file=sys.stderr)
        _emit_output("version_published", "false")
        return

    if len(versions) > 1:
        print(
            f"Warning: dist files span multiple versions ({sorted(versions)}); skipping idempotency check",
            file=sys.stderr,
        )
        _emit_output("version_published", "false")
        return

    name, version = next(iter(versions))
    if version_already_published(name, version, upload_url):
        print(f"Skipping publish: {name} {version} is already on the registry")
        _emit_output("version_published", "true")
        return

    print(f"Ready to publish {name} {version}")
    _emit_output("version_published", "false")


if __name__ == "__main__":
    main()
