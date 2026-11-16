#!/usr/bin/env bash
# Resolve the use-sccache input to "true" or "false" and write it to GITHUB_OUTPUT as `enabled`.
#
# ~keep "true" leaves sccache off on Windows. sccache expands cargo's @argfile and spawns rustc with
# the full command line, which exceeds the Windows limit (os error 206) for crates with many
# dependencies once Cargo 1.100 puts every rmeta under build/<pkg>/<hash>/out. Without a wrapper
# cargo retries with an argfile itself. "force" keeps sccache on Windows too.
set -euo pipefail

requested="${1:-true}"
runner_os="${RUNNER_OS:-}"

case "$requested" in
false) enabled=false ;;
force) enabled=true ;;
true)
  if [[ "$runner_os" == "Windows" ]]; then
    enabled=false
    echo "sccache off on Windows; set use-sccache: force to keep it"
  else
    enabled=true
  fi
  ;;
*)
  echo "::error::use-sccache must be true, force or false, got '$requested'" >&2
  exit 1
  ;;
esac

echo "enabled=$enabled" >>"$GITHUB_OUTPUT"
