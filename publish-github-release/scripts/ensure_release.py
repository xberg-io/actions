#!/usr/bin/env python3
"""Ensure a GitHub release exists for a given tag, creating or publishing as needed.

Usage (GitHub Actions via env vars):
    INPUT_TAG=v1.2.3 INPUT_DRY_RUN=false python3 ensure_release.py
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def get_github_api_headers(token: str) -> dict[str, str]:
    """Return headers for GitHub REST API v2022-11-28."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "kreuzberg-dev-actions-publish-github-release",
    }


def github_request(method: str, url: str, token: str, data: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Make a GitHub REST API request and return (status_code, response_json).

    Raises SystemExit on non-2xx responses (except 404 for GETs).
    """
    headers = get_github_api_headers(token)

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310

    try:
        with urllib.request.urlopen(req) as response:  # noqa: S310
            response_data = json.loads(response.read().decode("utf-8"))
            return response.status, response_data
    except urllib.error.HTTPError as e:
        # For GET requests checking existence (404), return gracefully
        if method == "GET" and e.code == 404:
            return 404, {}
        # For all other errors, print and exit
        error_body = e.read().decode("utf-8")
        print(
            f"Error: HTTP {e.code} {e.reason} from {url}",
            file=sys.stderr,
        )
        print(error_body, file=sys.stderr)
        sys.exit(1)


def get_release_by_tag(owner: str, repo: str, tag: str, token: str) -> dict[str, Any] | None:
    """Get release info for a tag. Returns dict if found, None if 404."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    status, data = github_request("GET", url, token)
    return data if status == 200 else None


def create_release(
    owner: str,
    repo: str,
    tag: str,
    title: str,
    generate_notes: bool,
    draft: bool,
    prerelease: bool,
    notes: str = "",
    target: str = "",
    token: str = "",
) -> dict[str, Any]:
    """Create a release via POST /repos/{owner}/{repo}/releases."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"

    body_dict = {
        "tag_name": tag,
        "name": title,
        "draft": draft,
        "prerelease": prerelease,
    }

    # notes takes precedence over generate_notes
    if notes:
        body_dict["body"] = notes
    elif generate_notes:
        body_dict["generate_release_notes"] = True

    if target:
        body_dict["target_commitish"] = target

    _status, data = github_request("POST", url, token, body_dict)
    return data


def update_release(owner: str, repo: str, release_id: int, draft: bool, token: str) -> dict[str, Any]:
    """Update a release via PATCH /repos/{owner}/{repo}/releases/{id}."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}"

    body_dict = {"draft": draft}

    _status, data = github_request("PATCH", url, token, body_dict)
    return data


def main() -> None:
    tag = os.environ.get("INPUT_TAG", "")
    title = os.environ.get("INPUT_TITLE", "") or tag
    generate_notes = os.environ.get("INPUT_GENERATE_NOTES", "true").lower() == "true"
    draft = os.environ.get("INPUT_DRAFT", "false").lower() == "true"
    prerelease = os.environ.get("INPUT_PRERELEASE", "false").lower() == "true"
    notes = os.environ.get("INPUT_NOTES", "")
    target = os.environ.get("INPUT_TARGET", "").strip()
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)

    if not title:
        title = tag

    if not token:
        print("Error: GH_TOKEN is required", file=sys.stderr)
        sys.exit(1)

    if not repository:
        print("Error: GITHUB_REPOSITORY is required", file=sys.stderr)
        sys.exit(1)

    owner, repo = repository.split("/", 1)

    if dry_run:
        print(f"[dry-run] Would create/ensure release for tag: {tag}")
        print(f"  Title: {title}")
        print(f"  Generate notes: {generate_notes}")
        print(f"  Draft: {draft}")
        print(f"  Pre-release: {prerelease}")
        if target:
            print(f"  Target: {target}")
        sys.exit(0)

    # Check if release already exists
    existing = get_release_by_tag(owner, repo, tag, token)

    if existing:
        print(f"Release {tag} already exists")
        is_draft = existing.get("draft", False)
        if is_draft and not draft:
            print(f"Publishing draft release {tag}...")
            release_id: int = existing.get("id", 0)
            update_release(owner, repo, release_id, False, token)
    else:
        print(f"Creating release {tag}...")
        create_release(
            owner,
            repo,
            tag,
            title,
            generate_notes,
            draft,
            prerelease,
            notes=notes,
            target=target,
            token=token,
        )

    print(f"Release {tag} ready")


if __name__ == "__main__":
    main()
