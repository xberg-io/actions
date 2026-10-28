#!/usr/bin/env bash
set -euo pipefail

working_directory="${1:-.}"
mise_env="${2:-}"
cache="${3:-auto}"

export_default() {
  if [[ -z "${!1:-}" ]]; then
    echo "$1=$2" >>"$GITHUB_ENV"
  fi
}

if [[ -n "$mise_env" ]]; then
  echo "MISE_ENV=$mise_env" >>"$GITHUB_ENV"
else
  mise_env="${MISE_ENV:-}"
fi

export_default MISE_RUBY_COMPILE false
# mise's 30s default connect/read timeout fails repeatedly on loaded runners. ~keep
export_default MISE_HTTP_TIMEOUT 5m

lockfiles=("$working_directory/mise.lock")
IFS=',' read -r -a profiles <<<"$mise_env"
for profile in ${profiles[@]+"${profiles[@]}"}; do
  profile="${profile#"${profile%%[![:space:]]*}"}"
  profile="${profile%"${profile##*[![:space:]]}"}"
  if [[ -n "$profile" ]]; then
    lockfiles+=("$working_directory/mise.${profile}.lock")
  fi
done
for lockfile in "${lockfiles[@]}"; do
  if [[ -f "$lockfile" ]]; then
    if [[ -n "${MISE_LOCKED:-}" ]]; then
      echo "Found $lockfile; keeping the caller's MISE_LOCKED=$MISE_LOCKED"
    else
      echo "Found $lockfile; installing with MISE_LOCKED=1"
      echo "MISE_LOCKED=1" >>"$GITHUB_ENV"
    fi
    break
  fi
done

# A preset MISE_DATA_DIR is a runner image's baked toolchain. Caching it would key the whole directory on this
# repository's mise files alone, so an old cache could overlay a newer image. ~keep
case "$cache" in
auto)
  if [[ -n "${MISE_DATA_DIR:-}" ]]; then
    echo "MISE_DATA_DIR is preset ($MISE_DATA_DIR); not caching it"
    cache=false
  else
    cache=true
  fi
  ;;
true | false) ;;
*)
  echo "::error::cache must be auto, true or false, got '$cache'" >&2
  exit 1
  ;;
esac
echo "cache=$cache" >>"$GITHUB_OUTPUT"
