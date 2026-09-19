#!/usr/bin/env python3
"""Find and validate dist files for PyPI publishing, with file-level idempotency.

Usage (GitHub Actions via env vars):
    INPUT_PACKAGES_DIR=dist INPUT_DRY_RUN=false python3 publish.py

Outputs `version_published=true` to `$GITHUB_OUTPUT` only when every local dist
file is already on the configured index, so the calling action can skip the
`uv publish` invocation. A partially published version falls through to
`uv publish --check-url`, which skips the files that are present.
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


def published_filenames(name: str, version: str, upload_url: str) -> set[str] | None:
    """Return the dist filenames the registry already holds for project+version.

    `None` means the version is not on the registry at all (404). A 200 whose body lists no
    files yields an empty set, so the caller falls through to publishing.

    ~keep Presence is decided per FILE, never per version. xberg v1.2.5 uploaded 2 of 8 wheels
    before PyPI's project quota returned 400; the rerun found the version on the registry,
    skipped the whole publish and reported success having uploaded nothing (xberg GH#1699).
    `uv publish --check-url` skips the files that are present, so publishing a partial set is
    safe and the skip is only ever legitimate when nothing at all is left to upload.

    Best-effort: any network failure or non-200/404 response returns `None` so we fall through
    to the publish attempt rather than skipping incorrectly.
    """
    base = _upload_url_to_json_base(upload_url)
    url = f"{base}/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            if resp.status != 200:
                return None
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"Warning: PyPI index check returned HTTP {exc.code} for {url}", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Warning: PyPI index check failed for {url}: {exc}", file=sys.stderr)
        return None
    if not isinstance(body, dict):
        return None
    return {entry["filename"] for entry in body.get("urls", []) if isinstance(entry, dict) and "filename" in entry}


def _emit_output(key: str, value: str) -> None:
    """Write a `key=value` line to $GITHUB_OUTPUT (no-op when unset)."""
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


DRY_RUN_TAG_MARKER = "-dryrun-"


def normalize_release_version(version: str) -> str:
    """Strip whitespace and a leading `v` so a tag (`v1.19.0`) compares to a dist version.

    ~keep A dry run synthesizes its tag as `<version>-dryrun-<sha>` (see the
    prepare-release-metadata action), a version no manifest will ever declare. Stripping the
    suffix keeps the release-version assertion running on dry runs -- which is the point of a
    dry run -- instead of failing every one of them on a correct checkout. Only the literal
    `-dryrun-` marker is stripped, so a prerelease such as `1.2.3-rc.1` is compared in full.
    """
    normalized = version.strip().removeprefix("v")
    marker_index = normalized.find(DRY_RUN_TAG_MARKER)
    return normalized[:marker_index] if marker_index != -1 else normalized


def assert_dists_match_release(versions: set[tuple[str, str]], expected_version: str) -> None:
    """Fail when any dist file carries a version other than the release being published.

    ~keep This guard is what makes the idempotency check below safe, and the two must not be
    collapsed. Skipping a version that is already on the registry is legitimate ONLY when that
    version is the one being released. liter-llm v1.19.0 rebuilt a 1.18.4 wheel, matched the
    already-published check on 1.18.4, and reported success having published nothing for the
    tag. A stale artifact is a build failure and must fail loudly — never resolve to a skip.
    """
    if not versions:
        print(
            f"Error: expected-version {expected_version} was supplied but no dist filename could be "
            f"parsed, so the artifacts cannot be verified against the release",
            file=sys.stderr,
        )
        sys.exit(1)

    mismatched = sorted(
        f"{name} {version}" for name, version in versions if normalize_release_version(version) != expected_version
    )
    if mismatched:
        print(
            f"Error: dist files carry version(s) that differ from the release version "
            f"{expected_version}: {', '.join(mismatched)}",
            file=sys.stderr,
        )
        print(
            "The built artifacts are stale. Publishing them would ship the wrong version, or be "
            "silently swallowed as an 'already published' skip.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Verified all dist files carry the release version {expected_version}")


def main() -> None:
    packages_dir = Path(os.environ.get("INPUT_PACKAGES_DIR", "dist"))
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    upload_url = os.environ.get("INPUT_REPOSITORY_URL", "https://upload.pypi.org/legacy/")
    expected_version = normalize_release_version(os.environ.get("INPUT_EXPECTED_VERSION", ""))

    files = validate_dist_dir(packages_dir)

    print(f"Found {len(files)} dist file(s) in {packages_dir}:")
    for f in files:
        print(f"  {f.name}")

    versions: set[tuple[str, str]] = set()
    for f in files:
        if parsed := parse_name_version(f.name):
            versions.add(parsed)
        else:
            print(f"Warning: could not parse name/version from {f.name}", file=sys.stderr)

    # ~keep Runs before the dry-run bail on purpose: a dry run exists to catch a stale build
    # before the real release, so it must apply the same version assertion.
    if expected_version:
        assert_dists_match_release(versions, expected_version)
    else:
        print(
            "::warning::publish-pypi was invoked without `expected-version`; a stale artifact "
            "cannot be detected and an 'already published' registry hit will be treated as an "
            "idempotent skip. Pass the release version from the caller to close this gap."
        )

    if dry_run:
        print("[dry-run] Skipping publish")
        _emit_output("version_published", "false")
        return

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
    on_registry = published_filenames(name, version, upload_url)
    local_names = {f.name for f in files}
    missing = sorted(local_names - (on_registry or set()))
    if on_registry is not None and not missing:
        print(f"Skipping publish: every dist file of {name} {version} is already on the registry")
        _emit_output("version_published", "true")
        return

    if on_registry:
        print(
            f"{name} {version} is on the registry with {len(on_registry)} file(s); "
            f"{len(missing)} of {len(local_names)} local file(s) still missing:"
        )
        for filename in missing:
            print(f"  {filename}")
    print(f"Ready to publish {name} {version}")
    _emit_output("version_published", "false")


if __name__ == "__main__":
    main()
