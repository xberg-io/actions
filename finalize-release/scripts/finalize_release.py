#!/usr/bin/env python3
"""Finalize a GitHub Release: publish from draft, set prerelease flag, optionally tag Go module.

Inputs (env vars):
    INPUT_TAG: release tag (required)
    INPUT_IS_PRERELEASE: "true"/"false" to force, "auto" to derive (default "auto")
    INPUT_GO_MODULE_PATH: optional path like "packages/go/v5"; creates tag {path}/{tag}
    INPUT_DRY_RUN: "true" to skip mutations (default false)
    INPUT_REPO: GitHub owner/repo (required for Go module tag creation)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PRERELEASE_PATTERN = re.compile(r"-(rc|alpha|beta|pre)\b")


def env_str(key: str, default: str = "") -> str:
    value = os.environ.get(key, default) or default
    return value.strip()


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "y", "on"}


def resolve_prerelease(raw: str, tag: str) -> bool:
    raw = raw.strip().lower()
    if raw == "true":
        return True
    if raw == "false":
        return False
    return bool(PRERELEASE_PATTERN.search(tag))


def gh_release_view(tag: str) -> dict[str, Any] | None:
    """View a release, retrying up to 6 times with 5s sleep between attempts.

    Handles race where the release was just created and the API hasn't caught up.
    """
    import time

    max_attempts = 6
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            ["gh", "release", "view", tag, "--json", "isDraft,isPrerelease,name,url"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
                return payload if isinstance(payload, dict) else None
            except json.JSONDecodeError:
                return None

        if attempt < max_attempts:
            print(f"Release {tag} not found (attempt {attempt}/{max_attempts}), retrying in 5s...", file=sys.stderr)
            time.sleep(5)
        else:
            print(f"Release {tag} not found after {max_attempts} attempts", file=sys.stderr)
            return None

    return None


def gh_release_edit(tag: str, *, draft: bool, prerelease: bool) -> None:
    cmd = [
        "gh",
        "release",
        "edit",
        tag,
        f"--draft={'true' if draft else 'false'}",
        f"--prerelease={'true' if prerelease else 'false'}",
    ]
    subprocess.run(cmd, check=True)


def gh_get_tag_sha(tag: str) -> str:
    result = subprocess.run(
        ["gh", "api", f"repos/{os.environ.get('INPUT_REPO', '')}/git/refs/tags/{tag}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to resolve sha for tag {tag}: {result.stderr}")
    payload = json.loads(result.stdout)
    sha = payload.get("object", {}).get("sha")
    if not sha:
        raise RuntimeError(f"no sha in api response for tag {tag}")
    return str(sha)


def gh_create_tag(repo: str, tag: str, sha: str) -> bool:
    """Create tag via the API. Returns True if created, False if it already exists (422)."""
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/git/refs",
            "-f",
            f"ref=refs/tags/{tag}",
            "-f",
            f"sha={sha}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    if "Reference already exists" in result.stderr or "422" in result.stderr:
        return False
    raise RuntimeError(f"failed to create tag {tag}: {result.stderr}")


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def write_summary(lines: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    tag = env_str("INPUT_TAG")
    is_prerelease_raw = env_str("INPUT_IS_PRERELEASE", "auto") or "auto"
    go_module_path = env_str("INPUT_GO_MODULE_PATH")
    dry_run = env_bool("INPUT_DRY_RUN", default=False)
    repo = env_str("INPUT_REPO") or env_str("GITHUB_REPOSITORY")

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)

    prerelease = resolve_prerelease(is_prerelease_raw, tag)
    print(f"Resolved prerelease flag: {prerelease} (input={is_prerelease_raw}, tag={tag})")

    if dry_run:
        print(f"[dry-run] Would edit release {tag} → draft=false, prerelease={prerelease}")
        if go_module_path:
            print(f"[dry-run] Would create Go module tag: {go_module_path}/{tag}")
        write_output("finalized", "false")
        write_output("prerelease-flag", "true" if prerelease else "false")
        return

    release = gh_release_view(tag)
    if release is None:
        print(f"Error: release {tag} not found", file=sys.stderr)
        sys.exit(1)

    is_draft = bool(release.get("isDraft", False))
    current_prerelease = bool(release.get("isPrerelease", False))

    summary = [f"## Release finalize: `{tag}`"]
    finalized_status = "already-finalized"

    if is_draft or current_prerelease != prerelease:
        gh_release_edit(tag, draft=False, prerelease=prerelease)
        finalized_status = "true"
        summary.append(f"- Edited release: draft=false, prerelease={prerelease}")
    else:
        summary.append("- Release already published with correct prerelease flag")

    if go_module_path and repo:
        try:
            sha = gh_get_tag_sha(tag)
            module_tag = f"{go_module_path}/{tag}"
            created = gh_create_tag(repo, module_tag, sha)
            if created:
                summary.append(f"- Created Go module tag: `{module_tag}` → `{sha[:8]}`")
            else:
                summary.append(f"- Go module tag already exists: `{module_tag}`")
        except RuntimeError as exc:
            print(f"Warning: Go module tag creation failed: {exc}", file=sys.stderr)
            summary.append(f"- ⚠ Go module tag creation failed: {exc}")

    write_summary(summary)
    write_output("finalized", finalized_status)
    write_output("prerelease-flag", "true" if prerelease else "false")
    print(f"Finalized status: {finalized_status}")


if __name__ == "__main__":
    main()
