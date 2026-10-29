#!/usr/bin/env bash
set -euo pipefail

working_directory="${1:-.}"
mise_env="${2:-}"
cache="${3:-auto}"
install="${4:-true}"
install_args="${5:-}"

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
# mise runs inline task `run` strings under `cmd /c` on Windows, where go-task used a POSIX shell and the
# org's tasks are written for one. Point it at Git Bash; mise reads this setting from the environment only. ~keep
if [[ "${RUNNER_OS:-}" == "Windows" ]]; then
  export_default MISE_WINDOWS_DEFAULT_INLINE_SHELL_ARGS "\"$(cygpath -m "$(command -v bash)")\" -o errexit -c"
fi

# A job that installs only some tools (or none) runs `mise run` with exactly those; mise would otherwise
# install every tool in mise.toml before the first task. ~keep
case "$install" in
true) [[ -z "$install_args" ]] || export_default MISE_TASK_RUN_AUTO_INSTALL false ;;
false) export_default MISE_TASK_RUN_AUTO_INSTALL false ;;
*)
  echo "::error::install must be true or false, got '$install'" >&2
  exit 1
  ;;
esac

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
