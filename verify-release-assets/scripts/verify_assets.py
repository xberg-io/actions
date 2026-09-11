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
import time
from pathlib import Path
from typing import Any

# The GitHub release replica can answer 404/502 for a short window right after
# `gh release create` returns, so lookups retry for ~3 minutes before failing. ~keep
MAX_LOOKUP_ATTEMPTS = 20
LOOKUP_SLEEP_SECONDS = 10

# Assets are uploaded by many jobs in parallel, and the release replica can still serve a
# partial asset list seconds after the last upload job reports success. Retrying only the
# *lookup* does not cover that: a release found holding 1 of 68 assets is indistinguishable
# from a complete one, so a single evaluation fails every pattern whose asset is still in
# flight -- a false negative on an otherwise good release. Re-evaluate until every pattern
# matches or the budget is spent. Observed on html-to-markdown v3.12.1, where this ran three
# seconds after the final upload job, saw one asset, and reported 21 missing patterns that
# were all present moments later. ~keep
MAX_SETTLE_ATTEMPTS = 15
SETTLE_SLEEP_SECONDS = 20


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


def _run_gh(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _only_dicts(values: Any) -> list[dict[str, Any]]:
    return [value for value in values if isinstance(value, dict)]


def _parse_release_list(payload_raw: str) -> list[Any]:
    """Parse `gh api --paginate` output, which is either one array or one array per line.

    Multi-page output is several arrays separated by newlines, and it still starts with
    `[` -- so dispatching on the first character alone sends it into a whole-payload
    json.loads that raises "Extra data". That made every repo with more than one page of
    releases fall back to `gh release view`, which cannot see drafts at all, which is the
    only reason this listing path exists. Try the whole payload first, then per line. ~keep
    """
    payload_raw = payload_raw.strip()
    try:
        parsed: list[Any] = json.loads(payload_raw)
    except json.JSONDecodeError:
        releases: list[Any] = []
        for line in payload_raw.splitlines():
            chunk = line.strip()
            if chunk.startswith("["):
                releases.extend(json.loads(chunk))
        return releases
    return parsed


def _describe_release(release: dict[str, Any]) -> str:
    state = "draft" if release.get("draft") else "published"
    asset_count = len(_only_dicts(release.get("assets") or []))
    return f"id={release.get('id')} {state} {asset_count} asset(s)"


def _select_release_for_tag(releases: list[Any], tag: str) -> dict[str, Any] | None:
    """Return the release `tag` resolves to, preferring a published one over a draft.

    Deleting a Git tag converts its release into a draft, so a tag that was deleted and
    re-created -- what `retag-for-republish` does -- can carry two releases: the orphaned
    draft holding the failed attempt's asset list, and the live release holding the real
    one. Matching on `tag_name` alone returned whichever the API listed first, and a stale
    draft made every asset uploaded by the republish look missing while it was provably on
    the release, with no way to tell that apart from uploads still in flight. Prefer the
    published release and name the ambiguity when more than one matches. See #64. ~keep
    """
    matches = [release for release in _only_dicts(releases) if release.get("tag_name") == tag]
    if not matches:
        return None
    chosen = next((release for release in matches if not release.get("draft")), matches[0])
    if len(matches) > 1:
        print(
            f"Warning: {len(matches)} releases match tag {tag}; verifying the "
            f"{'published' if not chosen.get('draft') else 'draft'} one.",
            file=sys.stderr,
        )
        for release in matches:
            marker = "->" if release is chosen else "  "
            print(f"  {marker} {_describe_release(release)}", file=sys.stderr)
        print(
            "Deleting a tag turns its release into a draft; an orphaned draft on this tag makes "
            "republished assets look missing. Delete it once the published release is a superset.",
            file=sys.stderr,
        )
    return chosen


def _assets_for_tag(releases: list[Any], tag: str) -> list[dict[str, Any]] | None:
    """Return the assets of the release `tag` resolves to, else None."""
    release = _select_release_for_tag(releases, tag)
    if release is None:
        return None
    return _only_dicts(release.get("assets") or [])


def _lookup_via_api(repo: str, tag: str) -> tuple[list[dict[str, Any]] | None, str]:
    """List every release and match on tag_name. Returns (assets, error)."""
    result = _run_gh(["gh", "api", "--paginate", f"repos/{repo}/releases?per_page=100"])
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip()
    try:
        releases = _parse_release_list(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"non-JSON release list: {exc}"
    return _assets_for_tag(releases, tag), ""


def _lookup_via_view(repo: str, tag: str) -> tuple[list[dict[str, Any]] | None, str]:
    """Resolve the release by published tag. Returns (assets, error)."""
    result = _run_gh(["gh", "release", "view", tag, "--json", "assets", "-R", repo])
    if result.returncode != 0:
        return None, result.stderr.strip()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"gh release view returned non-JSON: {exc}"
    return _only_dicts(payload.get("assets") or []), ""


def fetch_release_assets(tag: str) -> list[dict[str, Any]]:
    """Return the asset list for the release matching `tag`.

    Resolves draft releases first via the GitHub API
    `/repos/{owner}/{repo}/releases?per_page=100` (paginated), filtered by
    `tag_name`. Drafts have no published Git tag, so the conventional
    `GET /releases/tags/<tag>` lookup that `gh release view <tag>` performs
    always returns 404 for them. Listing all releases (which the same
    endpoint surfaces when the token grants `contents:read` plus draft
    visibility, e.g. the GitHub App tokens used in the xberg-io
    publish workflows) reaches draft and published releases uniformly.

    Falls back to `gh release view <tag>` if the API listing returns no
    matching release (covers the case where only the published-tag lookup
    works for the calling token). Both paths retry on transient API
    failures with backoff: the GitHub release replica can briefly answer
    404/502 right after `gh release create` returns.
    """
    repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("Error: GITHUB_REPOSITORY (or GH_REPO) must be set", file=sys.stderr)
        sys.exit(1)

    last_err = ""
    for attempt in range(1, MAX_LOOKUP_ATTEMPTS + 1):
        for lookup in (_lookup_via_api, _lookup_via_view):
            assets, err = lookup(repo, tag)
            if assets is not None:
                return assets
            last_err = err or last_err

        if attempt < MAX_LOOKUP_ATTEMPTS:
            print(
                f"release lookup attempt {attempt}/{MAX_LOOKUP_ATTEMPTS} did not find {tag}; "
                f"release may not be propagated yet, retrying in {LOOKUP_SLEEP_SECONDS}s...",
                file=sys.stderr,
            )
            if last_err:
                print(last_err, file=sys.stderr)
            time.sleep(LOOKUP_SLEEP_SECONDS)

    print(f"Error: release {tag} not found after {MAX_LOOKUP_ATTEMPTS} attempts: {last_err}", file=sys.stderr)
    sys.exit(1)


def match_patterns(
    assets: list[dict[str, Any]], patterns: list[str], min_size: int
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Match every pattern against `assets`, preserving the caller's pattern order.

    Returns `(pattern, matching_assets)` pairs; a pair with an empty list is a miss.
    """
    results: list[tuple[str, list[dict[str, Any]]]] = []
    for pattern in patterns:
        matches = [a for a in assets if fnmatch.fnmatch(str(a.get("name", "")), pattern)]
        if min_size > 0:
            matches = [a for a in matches if int(a.get("size", 0)) >= min_size]
        results.append((pattern, matches))
    return results


def settle_assets(
    tag: str, patterns: list[str], min_size: int, single_pass: bool = False
) -> tuple[list[dict[str, Any]], list[tuple[str, list[dict[str, Any]]]]]:
    """Fetch and re-evaluate until every pattern matches or the retry budget is spent.

    Returns the final `(assets, results)`. `single_pass` evaluates once, for dry runs, which
    are informational and should not spend the whole settle budget.
    """
    assets: list[dict[str, Any]] = []
    results: list[tuple[str, list[dict[str, Any]]]] = []
    attempts = 1 if single_pass else MAX_SETTLE_ATTEMPTS
    for attempt in range(1, attempts + 1):
        assets = fetch_release_assets(tag)
        results = match_patterns(assets, patterns, min_size)
        missing = [pattern for pattern, matches in results if not matches]
        if not missing or attempt == attempts:
            return assets, results
        print(
            f"settle attempt {attempt}/{attempts}: {len(assets)} asset(s) present, "
            f"{len(missing)} pattern(s) still unmatched -- uploads may be in flight, "
            f"retrying in {SETTLE_SLEEP_SECONDS}s...",
            file=sys.stderr,
        )
        time.sleep(SETTLE_SLEEP_SECONDS)
    return assets, results


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

    assets, results = settle_assets(tag, patterns, min_size, single_pass=dry_run)
    print(f"Release {tag} has {len(assets)} asset(s):")
    for asset in assets:
        print(f"  {asset.get('name')} ({asset.get('size', 0)} bytes)")

    missing = [pattern for pattern, matches in results if not matches]
    verified = len(results) - len(missing)
    for pattern, matches in results:
        if matches:
            print(f"  ✓ pattern matched: {pattern} ({len(matches)} asset(s))")
        else:
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
