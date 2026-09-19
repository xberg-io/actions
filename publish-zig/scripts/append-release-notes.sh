#!/usr/bin/env bash
# Append the Zig fetch block to a GitHub Release's notes, once.
#
# Env: GH_TOKEN, GITHUB_REPOSITORY, RELEASE_ID, TAG, PKG_NAME, URL, HASH
set -euo pipefail

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
  gh api -X PATCH "repos/$GITHUB_REPOSITORY/releases/$RELEASE_ID" \
    -f body="$new_body" >/dev/null
  echo "Release notes updated with Zig fetch block"
else
  echo "Zig fetch block already present in release notes"
fi
