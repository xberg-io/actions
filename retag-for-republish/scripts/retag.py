#!/usr/bin/env python3
"""Delete and recreate a Git tag on HEAD using the GitHub API.

Usage (GitHub Actions via env vars):
    INPUT_TAG=v1.2.3 python3 retag.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def build_delete_url(repo: str, tag: str) -> str:
    """Return the GitHub API path to delete a tag ref."""
    return f"repos/{repo}/git/refs/tags/{tag}"


def build_create_payload(tag: str, sha: str) -> dict[str, str]:
    """Return the JSON payload for creating a tag ref."""
    return {"ref": f"refs/tags/{tag}", "sha": sha}


def find_orphaned_drafts(repo: str, tag: str) -> list[dict[str, Any]]:
    """Return the draft releases sitting on `tag`.

    Deleting a tag converts its release into a draft, and re-creating the tag lets the
    workflow open a second release on the same tag. The orphan is invisible until something
    resolves the tag by name and picks it, so name it here. See xberg-io/actions#64. ~keep
    """
    result = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repo}/releases?per_page=100"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    releases: list[Any] = []
    for chunk in result.stdout.strip().splitlines() or [""]:
        line = chunk.strip()
        if not line.startswith("["):
            continue
        try:
            releases.extend(json.loads(line))
        except json.JSONDecodeError:
            return []
    return [
        release
        for release in releases
        if isinstance(release, dict) and release.get("tag_name") == tag and release.get("draft")
    ]


def report_orphaned_drafts(repo: str, tag: str) -> None:
    """Warn about any draft release left behind on `tag` by the delete/recreate."""
    drafts = find_orphaned_drafts(repo, tag)
    if not drafts:
        return
    print(
        f"::warning::{len(drafts)} draft release(s) remain on tag {tag} after retagging. "
        "A stale draft shadows the published release for anything resolving the tag by name "
        "(verify-release-assets reports its assets as missing). Delete it once the published "
        "release is a superset.",
    )
    for draft in drafts:
        assets = draft.get("assets") or []
        asset_count = len(assets) if isinstance(assets, list) else 0
        print(f"  draft id={draft.get('id')} with {asset_count} asset(s)")


def main() -> None:
    tag = os.environ.get("INPUT_TAG", "")
    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("Error: GITHUB_REPOSITORY is required", file=sys.stderr)
        sys.exit(1)

    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    sha = sha_result.stdout.strip()

    delete_url = build_delete_url(repo, tag)
    subprocess.run(
        ["gh", "api", "--method", "DELETE", delete_url],
        capture_output=True,
        check=False,
    )

    payload = build_create_payload(tag, sha)
    subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{repo}/git/refs", "--input", "-"],
        input=json.dumps(payload),
        text=True,
        check=True,
    )

    subprocess.run(["git", "tag", "-d", tag], capture_output=True, check=False)
    subprocess.run(["git", "tag", tag], check=True)

    print(f"Tag {tag} moved to {sha}")
    report_orphaned_drafts(repo, tag)

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a") as fh:
            fh.write(f"sha={sha}\n")


if __name__ == "__main__":
    main()
