#!/usr/bin/env bash
set -euo pipefail

# Resolve the alef version input to a concrete cache key and an install ref.
#
# Outputs (written to $GITHUB_OUTPUT):
#   resolved_version  Used as the cache key suffix. For "main" this is
#                     "main-<short-sha>" so the cache invalidates whenever the
#                     remote main commit changes; for tags it's the bare semver
#                     (e.g. "0.17.8").
#   install_ref       What the platform install script should consume.
#                     "main" for main-branch builds, otherwise the bare semver
#                     (no leading "v").
#   target            Host triple — included in the cache key so a Linux x86_64
#                     binary can't be served from a macOS arm64 cache.

version="${1:?version required}"

detect_target() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
  Linux)
    case "$arch" in
    x86_64) echo "x86_64-unknown-linux-gnu" ;;
    aarch64) echo "aarch64-unknown-linux-gnu" ;;
    *)
      echo "Error: unsupported Linux architecture: $arch" >&2
      return 1
      ;;
    esac
    ;;
  Darwin)
    case "$arch" in
    arm64) echo "aarch64-apple-darwin" ;;
    x86_64) echo "x86_64-apple-darwin" ;;
    *)
      echo "Error: unsupported macOS architecture: $arch" >&2
      return 1
      ;;
    esac
    ;;
  MINGW* | MSYS* | CYGWIN* | *NT*) echo "x86_64-pc-windows-gnu" ;;
  *)
    echo "Error: unsupported OS: $os" >&2
    return 1
    ;;
  esac
}

read_pinned_version() {
  if [[ -f "alef.toml" ]]; then
    local pinned
    pinned="$(sed -n '/^\[/q; s/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' alef.toml | head -1)"
    if [[ -n "$pinned" ]]; then
      echo "$pinned"
      return 0
    fi
    pinned="$(sed -n '/^\[workspace\]/,/^\[/ { s/^alef_version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p; }' alef.toml | head -1)"
    if [[ -n "$pinned" ]]; then
      echo "$pinned"
      return 0
    fi
  fi
  return 1
}

auth_args=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  auth_args=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
fi

resolved_version=""
install_ref=""

if [[ "$version" == "main" ]]; then
  install_ref="main"
  # Resolve a SHA-pinned cache key when possible, but tolerate API/network
  # failures: `set -euo pipefail` would otherwise abort the pipeline before
  # the fallback branch runs. Disable errexit/pipefail just around the lookup.
  set +e +o pipefail
  sha="$(curl --silent --fail "${auth_args[@]}" \
    "https://api.github.com/repos/kreuzberg-dev/alef/commits/main" |
    grep -m1 '"sha"' | sed -E 's/.*"([0-9a-f]+)".*/\1/')"
  set -eo pipefail
  if [[ -n "$sha" ]]; then
    resolved_version="main-${sha:0:12}"
  else
    # Fall back to a coarse key — cache will hit across all main commits
    # until the network comes back, which is acceptable for a degraded mode.
    resolved_version="main"
  fi
else
  if [[ "$version" == "latest" ]]; then
    if pinned="$(read_pinned_version)"; then
      echo "Using pinned version from alef.toml: $pinned" >&2
      resolved_version="$pinned"
    else
      set +e +o pipefail
      tag="$(curl --silent --fail "${auth_args[@]}" \
        "https://api.github.com/repos/kreuzberg-dev/alef/releases/latest" |
        grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')"
      set -eo pipefail
      if [[ -z "$tag" ]]; then
        echo "Error: could not resolve latest alef release" >&2
        exit 1
      fi
      resolved_version="$tag"
    fi
  else
    # Strip any leading 'v' so the cache key stays consistent regardless of
    # whether the caller passed "0.17.8" or "v0.17.8".
    resolved_version="${version#v}"
  fi
  install_ref="$resolved_version"
fi

target="$(detect_target)"

{
  echo "resolved_version=$resolved_version"
  echo "install_ref=$install_ref"
  echo "target=$target"
} >>"$GITHUB_OUTPUT"

echo "Resolved alef version: $resolved_version (install ref: $install_ref, target: $target)"
