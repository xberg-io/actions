"""Draft-aware release lookup shared by this action's scripts.

`GET /repos/{owner}/{repo}/releases/tags/{tag}` resolves only *published* releases: a draft has
no published git tag, so the endpoint answers 404 for it no matter how long you retry. This
action deliberately creates releases as drafts (the caller promotes them once its asset checks
pass), which made every by-tag consumer fail against the very release this action had just
created.

Listing `GET /repos/{owner}/{repo}/releases` returns drafts and published releases uniformly for
a token with push access -- the GitHub App tokens the xberg-io publish workflows use qualify --
so the listing is tried first and the by-tag lookup is kept as a fallback for tokens that can
only see published releases.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

RELEASES_PER_PAGE = 100
# ~keep A repository with many releases would otherwise page forever; the target release is
# ordered newest-first, so the tag being looked up is realistically on the first page or two.
MAX_RELEASE_PAGES = 20


def get_github_api_headers(token: str) -> dict[str, str]:
    """Return headers for GitHub REST API v2022-11-28."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "xberg-io-actions-publish-github-release",
    }


def _get_json(url: str, token: str) -> object | None:
    """GET `url` and decode JSON, returning None for any HTTP or decode failure.

    Typed as `object` so every caller has to narrow the payload with `isinstance` before
    trusting its shape -- the API can answer with a list, a dict or an error body.
    """
    req = urllib.request.Request(url, headers=get_github_api_headers(token), method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(req) as response:  # noqa: S310
            payload: object = json.loads(response.read().decode("utf-8"))
            return payload
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def find_release_in_listing(owner: str, repo: str, tag: str, token: str) -> dict[str, Any] | None:
    """Find the release whose `tag_name` is `tag` by paging the releases listing.

    Sees drafts, which `GET /releases/tags/{tag}` cannot. Returns None when no page holds it.
    """
    for page in range(1, MAX_RELEASE_PAGES + 1):
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={RELEASES_PER_PAGE}&page={page}"
        releases = _get_json(url, token)
        if not isinstance(releases, list) or not releases:
            return None

        for release in releases:
            if isinstance(release, dict) and release.get("tag_name") == tag:
                return release

        if len(releases) < RELEASES_PER_PAGE:
            return None

    return None


def find_release_by_tag(owner: str, repo: str, tag: str, token: str) -> dict[str, Any] | None:
    """Find the release for `tag`, drafts included. Returns None when it does not exist."""
    release = find_release_in_listing(owner, repo, tag, token)
    if release is not None:
        return release

    published = _get_json(f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}", token)
    return published if isinstance(published, dict) else None
