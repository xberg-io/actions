#!/usr/bin/env bash
#MISE description="Require the minimum ai-rulez version this checkout's governance needs"
#MISE hide=true
set -euo pipefail

AI_RULEZ_MIN_VERSION="5.9.2"

installed_version="$(ai-rulez --version)"
found="${installed_version#ai-rulez version }"
lowest="$(printf '%s\n%s\n' "$AI_RULEZ_MIN_VERSION" "$found" | sort -V | head -n 1)"
if [ "$found" = "$installed_version" ] || [ "$lowest" != "$AI_RULEZ_MIN_VERSION" ]; then
  printf '%s\n' "This checkout requires ai-rulez $AI_RULEZ_MIN_VERSION or newer; found $installed_version" >&2
  exit 1
fi
