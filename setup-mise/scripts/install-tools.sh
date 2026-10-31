#!/usr/bin/env bash
# Install tools through mise and put the selected versions on PATH for the steps after this one.
#
# usage: install-tools.sh <working-directory> <tool>[=<version>]...
#
# A tool without a version installs what the mise config in <working-directory> selects: mise.toml, the active
# MISE_ENV profiles, or a MISE_<TOOL>_VERSION the job exports. A tool the config does not declare fails. A
# version is matched against the active locks first, so "3.13" selects a locked 3.13.x and keeps the locked
# install; a version no lock covers installs unlocked, with a notice.
#
# INSTALL_TOOLS_FALLBACK_ROOT, when set, is a directory whose mise.lock pins a tool without a version that the
# config does not declare: the composites pass this repository's root, so such a tool installs the version this
# repository locks, --locked against its lock, with a notice. A runner platform that lock does not cover installs
# that pinned version unlocked.
set -euo pipefail

if (($# < 2)); then
  echo "usage: install-tools.sh <working-directory> <tool>[=<version>]..." >&2
  exit 2
fi
working_directory="$1"
shift
cd "$working_directory"

# Variables mise sets for an active tool that other build tools read: Maven and Gradle find the JDK by
# JAVA_HOME. Only the requested tools' variables are exported. ~keep
tool_variables() {
  case "$(short_name "$1")" in
  java) printf '%s\n' JAVA_HOME ;;
  go) printf '%s\n' GOROOT GOBIN ;;
  esac
}

short_name() {
  local id="${1##*:}"
  printf '%s' "${id##*/}"
}

is_true() {
  case "${1:-}" in
  1 | true | yes | on) return 0 ;;
  *) return 1 ;;
  esac
}

# "v1.2" -> "1.2", "3.x" -> "3"; a value outside a version's character set is rejected, not passed on. ~keep
normalize_version() {
  local version="$1"
  [[ "$version" =~ ^v[0-9] ]] && version="${version#v}"
  while [[ "$version" == *.x || "$version" == *.X || "$version" == *.\* ]]; do
    version="${version%.*}"
  done
  if [[ -n "$version" && ! "$version" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]]; then
    # Newlines are dropped so the input cannot start a workflow command of its own. ~keep
    echo "::error::'$(tr -d '\r\n' <<<"$1")' is not a version mise can install" >&2
    return 1
  fi
  printf '%s' "$version"
}

current_tools="$(mise current)"
configured=()
while read -r id _; do
  [[ -n "$id" ]] && configured+=("$id")
done < <(tr -d '\r' <<<"$current_tools")

# The configured tool id a requested tool refers to: the same id, or one with the same short name, so a
# composite asking for "wasm-pack" finds the caller's "github:rustwasm/wasm-pack".
configured_id() {
  local tool="$1" want id matches=()
  want="$(short_name "$tool")"
  for id in ${configured[@]+"${configured[@]}"}; do
    if [[ "$id" == "$tool" ]]; then
      printf '%s' "$id"
      return 0
    fi
    [[ "$(short_name "$id")" == "$want" ]] && matches+=("$id")
  done
  if ((${#matches[@]} > 1)); then
    echo "::error::$tool matches more than one configured tool (${matches[*]}); configure only one" >&2
    return 1
  fi
  printf '%s' "${matches[0]:-}"
}

lockfiles=(mise.lock)
IFS=',' read -r -a profiles <<<"${MISE_ENV:-}"
for profile in ${profiles[@]+"${profiles[@]}"}; do
  profile="${profile#"${profile%%[![:space:]]*}"}"
  profile="${profile%"${profile##*[![:space:]]}"}"
  [[ -n "$profile" ]] && lockfiles+=("mise.${profile}.lock")
done

# The versions <id> has in each lock file named after it, or in the active locks when none is named.
locked_versions() {
  local id="$1" lockfile
  shift
  (($#)) || set -- "${lockfiles[@]}"
  for lockfile in "$@"; do
    [[ -f "$lockfile" ]] || continue
    # A lock checked out with CRLF line endings would otherwise match no tool header. ~keep
    tr -d '\r' <"$lockfile" | awk -v id="$id" '
      /^\[\[tools\./ {
        name = $0
        sub(/^\[\[tools\./, "", name)
        sub(/\]\]$/, "", name)
        gsub(/^"|"$/, "", name)
        current = (name == id)
        next
      }
      /^\[/ { current = 0; next }
      current && /^version = "/ {
        version = $0
        sub(/^version = "/, "", version)
        sub(/".*$/, "", version)
        print version
        current = 0
      }
    '
  done
}

lock_ids() {
  tr -d '\r' <"$1" | awk '/^\[\[tools\./ { name = $0; sub(/^\[\[tools\./, "", name); sub(/\]\]$/, "", name)
    gsub(/^"|"$/, "", name); print name }' | sort -u
}

# mise's name for this runner's platform, as lock files key their per-platform entries.
runner_platform() {
  local os arch
  case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=macos ;;
  MINGW* | MSYS* | CYGWIN*) os=windows ;;
  *) os="$(uname -s)" ;;
  esac
  case "$(uname -m)" in
  x86_64 | amd64) arch=x64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) arch="$(uname -m)" ;;
  esac
  printf '%s-%s' "$os" "$arch"
}

# Whether <lock> has an entry for <id> on <platform>; mise quotes an id holding ':' or '/'.
lock_covers_platform() {
  local lock="$1" id="$2" platform="$3"
  tr -d '\r' <"$lock" | grep -Fxq -e "[tools.$id.\"platforms.$platform\"]" -e "[tools.\"$id\".\"platforms.$platform\"]"
}

# The fallback lock's id for a requested tool: the same id, or the one id with the same short name.
fallback_id() {
  local tool="$1" want id matches=()
  want="$(short_name "$tool")"
  while read -r id; do
    if [[ "$id" == "$tool" ]]; then
      printf '%s' "$id"
      return 0
    fi
    [[ "$(short_name "$id")" == "$want" ]] && matches+=("$id")
  done < <(lock_ids "$fallback_lock")
  ((${#matches[@]} == 1)) && printf '%s' "${matches[0]}"
  return 0
}

# The newest locked version equal to the request or under it as a prefix ("3.13" -> "3.13.18").
locked_match() {
  local id="$1" requested="$2" version
  locked_versions "$id" | while read -r version; do
    if [[ "$version" == "$requested" || "$version" == "$requested".* || "$version" == "$requested"+* ]]; then
      printf '%s\n' "$version"
    fi
  done | sort -V | tail -n 1
}

fallback_lock=""
if [[ -n "${INSTALL_TOOLS_FALLBACK_ROOT:-}" ]]; then
  fallback_root="$(cd "$INSTALL_TOOLS_FALLBACK_ROOT" && pwd)"
  fallback_lock="$fallback_root/mise.lock"
  if [[ ! -f "$fallback_lock" ]]; then
    echo "::error::INSTALL_TOOLS_FALLBACK_ROOT $fallback_root has no mise.lock" >&2
    exit 1
  fi
fi
locked_specs=()
unlocked_specs=()
fallback_specs=()
for request in "$@"; do
  tool="${request%%=*}"
  requested=""
  [[ "$request" == *=* ]] && requested="${request#*=}"
  if [[ -z "$tool" ]]; then
    echo "::error::empty tool name in '$request'" >&2
    exit 1
  fi
  requested="$(normalize_version "$requested")"
  id="$(configured_id "$tool")"

  if [[ -z "$requested" && -z "$id" && -n "$fallback_lock" ]]; then
    pinned_id="$(fallback_id "$tool")"
    pinned="$([[ -z "$pinned_id" ]] || locked_versions "$pinned_id" "$fallback_lock" | sort -V | tail -n 1)"
    if [[ -n "$pinned" ]]; then
      echo "::notice::$tool is not declared in the mise config for $PWD, so it installs $pinned_id@$pinned," \
        "the version $fallback_lock pins. Add it to mise.toml (then run mise lock) to choose its version."
      if lock_covers_platform "$fallback_lock" "$pinned_id" "$(runner_platform)"; then
        fallback_specs+=("$pinned_id@$pinned")
      else
        echo "::notice::$fallback_lock has no $(runner_platform) entry for $pinned_id," \
          "so $pinned installs unlocked."
        unlocked_specs+=("$pinned_id@$pinned")
      fi
      continue
    fi
  fi

  if [[ -z "$requested" ]]; then
    if [[ -z "$id" ]]; then
      echo "::error::$tool is not declared in the mise config for $PWD and no version was passed." \
        "Add it to mise.toml (then run mise lock) or pass the action's version input." >&2
      exit 1
    fi
    locked_specs+=("$id")
    continue
  fi

  target="${id:-$tool}"
  match="$(locked_match "$target" "$requested")"
  if [[ -n "$match" ]]; then
    locked_specs+=("$target@$match")
  else
    unlocked_specs+=("$target@$requested")
    if is_true "${MISE_LOCKED:-}"; then
      echo "::notice::$target@$requested is not in the active mise lock, so it installs unlocked." \
        "Declare it in a profile such as mise.ci.toml and lock it to verify its checksums."
    fi
  fi
done

if ((${#locked_specs[@]})); then
  mise install "${locked_specs[@]}"
fi
if ((${#unlocked_specs[@]})); then
  MISE_LOCKED=false mise install "${unlocked_specs[@]}"
fi
# ~keep From the fallback root, so mise verifies the install against that lock; its config is this repository's,
# ~keep trusted like the caller's, and the caller's profiles do not apply to it.
if ((${#fallback_specs[@]})); then
  (
    cd "$fallback_root"
    mise trust --quiet "$fallback_root"
    env -u MISE_ENV MISE_LOCKED=1 mise install "${fallback_specs[@]}"
  )
fi

all_specs=(${locked_specs[@]+"${locked_specs[@]}"} ${unlocked_specs[@]+"${unlocked_specs[@]}"}
  ${fallback_specs[@]+"${fallback_specs[@]}"})
paths=()
for spec in "${all_specs[@]}"; do
  spec_paths=()
  while IFS= read -r path; do
    [[ -n "$path" ]] && spec_paths+=("$path")
  done < <(MISE_LOCKED=false mise bin-paths "$spec" | tr -d '\r')
  if ((${#spec_paths[@]} == 0)); then
    echo "::error::mise resolved no bin directory for $spec" >&2
    exit 1
  fi
  echo "$spec: ${spec_paths[0]}"
  paths+=("${spec_paths[@]}")
done

# Each GITHUB_PATH line is prepended to PATH, so the last one written comes first. Write in reverse to keep
# mise's order, the first version of a tool ahead of its others. ~keep
for ((index = ${#paths[@]} - 1; index >= 0; index--)); do
  printf '%s\n' "${paths[index]}" >>"$GITHUB_PATH"
done

# `mise env` also prints the config's [env] values, which can hold secrets; only the allowed tool variables are
# kept, and nothing it prints is echoed. ~keep
variables=()
for spec in "${all_specs[@]}"; do
  while IFS= read -r variable; do
    variables+=("$variable")
  done < <(tool_variables "${spec%@*}")
done
if ((${#variables[@]})); then
  tool_env="$(MISE_LOCKED=false mise env --dotenv "${all_specs[@]}")"
  pattern="^($(IFS='|' && echo "${variables[*]}"))="
  { tr -d '\r' <<<"$tool_env" | grep -E "$pattern" || true; } |
    sed -E "s/^([A-Z_]+)=[\"']?([^\"']*)[\"']?\$/\\1=\\2/" >>"$GITHUB_ENV"
fi
