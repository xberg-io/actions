#!/usr/bin/env bash
set -euo pipefail

echo "Checking sccache runtime..."
if [ -z "${RUSTC_WRAPPER:-}" ]; then
  echo "sccache is disabled, continuing with direct compilation"
  exit 0
fi

# --start-server checks cache storage; --show-stats can succeed without a server.
# Cache errors can contain signed URLs, so keep probe diagnostics out of logs. ~keep
if command -v "$RUSTC_WRAPPER" &>/dev/null && "$RUSTC_WRAPPER" --start-server &>/dev/null; then
  echo "sccache runtime is ready"
  exit 0
fi

echo "Warning: sccache runtime is unavailable, continuing with direct compilation"
{
  echo "SCCACHE_GHA_ENABLED=false"
  echo "RUSTC_WRAPPER="
} >>"$GITHUB_ENV"
