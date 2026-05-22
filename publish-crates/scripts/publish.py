#!/usr/bin/env python3
"""Publish Rust crates to crates.io.

Usage (GitHub Actions via env vars):
    INPUT_CRATES="crate-a crate-b" INPUT_VERSION="1.2.3" python3 publish.py

After publishing each crate, waits for the new version to appear in the
crates.io sparse index before proceeding. This is required because cargo
resolves intra-workspace path-dependencies via the index when packaging
downstream crates — without this wait the next ``cargo publish`` immediately
fails with ``failed to select a version for the requirement ...``.
"""

import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ALREADY_PUBLISHED_PATTERN = re.compile(
    r"already uploaded|already exists",
    re.IGNORECASE,
)

# cargo emits this when packaging a crate whose intra-workspace dependency is
# not yet resolvable through the index — i.e. the upstream crate was published
# but has not finished propagating. It is transient and clears on retry.
DEPENDENCY_NOT_READY_PATTERN = re.compile(
    r"failed to select a version for",
    re.IGNORECASE,
)

INDEX_POLL_TIMEOUT_SECONDS = 300
INDEX_POLL_INTERVAL_SECONDS = 5

# Retry budget for a downstream `cargo publish` that fails because an
# upstream crate has not propagated yet.
PUBLISH_RETRY_ATTEMPTS = 6
PUBLISH_RETRY_DELAY_SECONDS = 30


def is_already_published(output: str) -> bool:
    """Return True if cargo publish output indicates the crate was already published."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def is_dependency_not_ready(output: str) -> bool:
    """Return True if cargo publish failed because an upstream crate has not propagated."""
    return bool(DEPENDENCY_NOT_READY_PATTERN.search(output))


def build_manifest_args(manifest_path: str) -> list[str]:
    """Return --manifest-path flag list, or empty list if manifest_path is blank."""
    if not manifest_path:
        return []
    return ["--manifest-path", manifest_path]


def parse_crate_list(crates: str) -> list[str]:
    """Split a whitespace-separated crate list into individual names."""
    return crates.split()


def _run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def _sparse_index_url(crate: str) -> str:
    """Return the crates.io sparse-index URL for ``crate``.

    crates.io shards index entries by name length: ``1/``, ``2/``, ``3/<a>/``,
    then ``<ab>/<cd>/``.
    """
    name = crate.lower()
    if len(name) == 1:
        prefix = "1"
    elif len(name) == 2:
        prefix = "2"
    elif len(name) == 3:
        prefix = f"3/{name[0]}"
    else:
        prefix = f"{name[0:2]}/{name[2:4]}"
    return f"https://index.crates.io/{prefix}/{name}"


def wait_for_index(crate: str, version: str) -> None:
    """Poll the crates.io sparse index until ``crate@version`` is visible.

    Cargo resolves dependency versions through the index; immediately after
    ``cargo publish`` returns, the new version is uploaded but not yet present
    in the sparse index. Downstream crates that depend on it cannot be
    packaged until propagation completes (typically 5-30 seconds).
    """
    url = _sparse_index_url(crate)
    deadline = time.monotonic() + INDEX_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        # The sparse index is served through a CDN. A plain GET can keep
        # returning a stale cached body that never shows the just-published
        # version, so the poll must explicitly defeat any cached response.
        request = urllib.request.Request(  # noqa: S310 — fixed crates.io URL
            url,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 — fixed crates.io URL
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                print(f"  index poll for {crate}: HTTP {exc.code}", file=sys.stderr)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"  index poll for {crate}: transient {exc}", file=sys.stderr)
        else:
            if f'"vers":"{version}"' in body:
                print(f"  index has {crate}@{version}")
                return
        time.sleep(INDEX_POLL_INTERVAL_SECONDS)
    print(
        f"  WARNING: {crate}@{version} not visible in crates.io index after "
        f"{INDEX_POLL_TIMEOUT_SECONDS}s; proceeding anyway",
        file=sys.stderr,
    )


def publish_crate(crate: str, manifest_args: list[str]) -> tuple[int, str]:
    """Run ``cargo publish`` for ``crate``, retrying while an upstream crate is still propagating.

    Each retry re-invokes ``cargo publish``, which re-fetches the sparse index,
    so a dependency that finished propagating between attempts is picked up.
    """
    exit_code, output = 0, ""
    for attempt in range(1, PUBLISH_RETRY_ATTEMPTS + 1):
        exit_code, output = _run(["cargo", "publish", "-p", crate, *manifest_args])
        if exit_code == 0 or is_already_published(output) or not is_dependency_not_ready(output):
            return exit_code, output
        if attempt < PUBLISH_RETRY_ATTEMPTS:
            print(
                f"  {crate}: an upstream dependency is not yet resolvable on the index "
                f"(attempt {attempt}/{PUBLISH_RETRY_ATTEMPTS}); retrying in "
                f"{PUBLISH_RETRY_DELAY_SECONDS}s",
                file=sys.stderr,
            )
            time.sleep(PUBLISH_RETRY_DELAY_SECONDS)
    return exit_code, output


def main() -> None:
    crates_input = os.environ.get("INPUT_CRATES", "")
    version = os.environ.get("INPUT_VERSION", "")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    manifest_path = os.environ.get("INPUT_MANIFEST_PATH", "")

    if not crates_input:
        print("Error: INPUT_CRATES is required", file=sys.stderr)
        sys.exit(1)
    if not version:
        print("Error: INPUT_VERSION is required", file=sys.stderr)
        sys.exit(1)

    crate_list = parse_crate_list(crates_input)
    manifest_args = build_manifest_args(manifest_path)
    total = len(crate_list)

    for index, crate in enumerate(crate_list, start=1):
        print(f"Publishing {crate} ({index}/{total})...")

        if dry_run:
            print(f"  [dry-run] cargo publish -p {crate} --dry-run")
            _run(["cargo", "publish", "-p", crate, *manifest_args, "--dry-run"])
            continue

        exit_code, output = publish_crate(crate, manifest_args)

        if exit_code == 0:
            print(f"  Published {crate}@{version}")
            wait_for_index(crate, version)
        elif is_already_published(output):
            print(f"  {crate}@{version} already published, skipping")
            wait_for_index(crate, version)
        else:
            print(f"  Error publishing {crate}:", file=sys.stderr)
            print(output, file=sys.stderr)
            sys.exit(1)

    print("All crates published successfully")


if __name__ == "__main__":
    main()
