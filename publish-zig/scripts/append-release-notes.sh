#!/usr/bin/env bash
# Append the Zig fetch block to a GitHub Release's notes, once.
#
# Env: GH_TOKEN, GITHUB_REPOSITORY, RELEASE_ID, TAG, PKG_NAME, URL, HASH
set -euo pipefail

if [[ -z "${TAG:-}" ]]; then
  echo "Error: TAG is required" >&2
  exit 1
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "GH_TOKEN not set; skipping release-notes update"
  exit 0
fi

# Address the release by id, not tag — `gh release view <tag>` and
# `gh release edit <tag>` resolve via /releases/tags/<tag>, which
# 404s on drafts. The Resolve-release-id step ran first and gave us
# an id that works for both draft and published releases.
body=$(gh api "repos/$GITHUB_REPOSITORY/releases/$RELEASE_ID" \
  --jq '.body // ""' 2>/dev/null || echo "")
# Append a Zig fetch block (idempotent: only append once).
if ! echo "$body" | grep -q "<!-- zig-fetch -->"; then
  # ~keep printf, not $'...' spliced around the variables: the previous one-liner left the
  # ANSI-C quoting at the first variable, so everything after the package name reached the
  # release page as literal \n and \" -- visible on every published Zig block.
  zig_block=$(printf '<!-- zig-fetch -->\n## Zig\n\nAdd to your `build.zig.zon`:\n\n```\n.dependencies = .{\n    .%s = .{\n        .url = "%s",\n        .hash = "%s",\n    },\n},\n```' \
    "$PKG_NAME" "$URL" "$HASH")
  new_body="$body"$'\n\n'"$zig_block"$'\n'
  # ~keep tag_name travels with every PATCH even though only the body changes. On a release
  # that is a draft before and after the request, PATCH /releases/{id} without tag_name
  # resets it to a placeholder untagged-* (reproduced against the live API; gh's own
  # `release edit` re-sends it for the same reason). Every publish workflow runs this step
  # against the draft `prepare` created, and each orphaned untagged-* draft in the org carried
  # this Zig block. The release was resolved by $TAG, so re-sending it is a no-op on a
  # healthy release and the repair on one already detached. xberg-io/actions#68
  gh api -X PATCH "repos/$GITHUB_REPOSITORY/releases/$RELEASE_ID" \
    -f tag_name="$TAG" \
    -f body="$new_body" >/dev/null
  echo "Release notes updated with Zig fetch block"
else
  echo "Zig fetch block already present in release notes"
fi
