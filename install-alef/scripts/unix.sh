#!/usr/bin/env bash
set -euo pipefail

version="${1:?version required}"

alef_bin_dir="${HOME}/.local/bin"
mkdir -p "$alef_bin_dir"

# Determine platform triple from OS and architecture
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
  *)
    echo "Error: unsupported OS: $os" >&2
    return 1
    ;;
  esac
}

# Read pinned version from alef.toml.
# Accepts either:
#   - top-level `version = "..."` (alef's own repo convention)
#   - `alef_version = "..."` (consumer-repo convention; may live under [workspace])
read_pinned_version() {
  if [[ -f "alef.toml" ]]; then
    local pinned
    # Try top-level `version = "..."` (must appear before first [section] header)
    pinned="$(sed -n '/^\[/q; s/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' alef.toml | head -1)"
    if [[ -n "$pinned" ]]; then
      echo "$pinned"
      return 0
    fi
    # Try `alef_version = "..."` (may appear anywhere, e.g. under [workspace])
    pinned="$(sed -n 's/^alef_version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' alef.toml | head -1)"
    if [[ -n "$pinned" ]]; then
      echo "$pinned"
      return 0
    fi
  fi
  return 1
}

# Resolve "latest" to a concrete version.
# Order: alef.toml pin > GitHub "latest" release tag.
# Hard-fails if the resolved tag has no binary uploaded — callers should
# retry the workflow after the alef publish run finishes uploading
# binaries, not silently fall back to an older release.
resolve_version() {
  if [[ "$version" == "latest" ]]; then
    local pinned
    if pinned="$(read_pinned_version)"; then
      echo "Using pinned version from alef.toml: $pinned" >&2
      echo "$pinned"
      return 0
    fi

    local tag auth_args=()
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
      auth_args=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
    fi
    tag="$(curl --silent --fail "${auth_args[@]}" \
      "https://api.github.com/repos/kreuzberg-dev/alef/releases/latest" |
      grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')"
    if [[ -z "$tag" ]]; then
      echo "Error: could not resolve latest alef release" >&2
      return 1
    fi
    echo "$tag"
  else
    echo "$version"
  fi
}

# Install from a GitHub release binary
install_from_release() {
  local resolved_version target max_attempts=3 attempt=1 wait_time=2
  resolved_version="$(resolve_version)"
  # Strip leading 'v' if present so we don't form vv-tagged URLs when callers
  # pass an already-prefixed tag like "v0.16.23".
  resolved_version="${resolved_version#v}"
  target="$(detect_target)"
  local url="https://github.com/kreuzberg-dev/alef/releases/download/v${resolved_version}/alef-${target}.tar.gz"

  while [[ $attempt -le $max_attempts ]]; do
    echo "Installing alef v${resolved_version} for ${target} (attempt ${attempt}/${max_attempts})..."

    if curl --location \
      --connect-timeout 10 \
      --max-time 60 \
      --retry 2 \
      --retry-delay 1 \
      --fail \
      "$url" | tar xz --strip-components=1 -C "$alef_bin_dir"; then

      if [[ -x "$alef_bin_dir/alef" ]]; then
        echo "Alef v${resolved_version} installed successfully"
        return 0
      else
        echo "Error: alef binary not found at $alef_bin_dir/alef"
        rm -f "$alef_bin_dir/alef"
      fi
    else
      echo "Download failed from $url"
    fi

    attempt=$((attempt + 1))
    if [[ $attempt -le $max_attempts ]]; then
      echo "Retrying in ${wait_time}s..."
      sleep "$wait_time"
      wait_time=$((wait_time * 2))
    fi
  done

  echo "Error: Failed to install alef after ${max_attempts} attempts" >&2
  return 1
}

# Bootstrap a minimal Rust toolchain via rustup when cargo is missing on the
# runner. Required for source installs (main branch or tag fallback) when the
# host doesn't ship Rust by default (e.g. minimal Linux runners). PATH is
# updated for the current shell only — callers append $HOME/.cargo/bin to
# $GITHUB_PATH separately if they need it for later steps.
ensure_cargo() {
  if command -v cargo >/dev/null 2>&1; then
    return 0
  fi
  echo "cargo not found — bootstrapping minimal Rust toolchain via rustup..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs |
    sh -s -- -y --default-toolchain stable --profile minimal --no-modify-path
  # shellcheck source=/dev/null
  . "$HOME/.cargo/env"
}

# Install from main branch via cargo install
install_from_main() {
  echo "Installing alef from main branch via cargo install..."
  ensure_cargo
  CARGO_INSTALL_ROOT="$alef_bin_dir/.." \
    cargo install --git https://github.com/kreuzberg-dev/alef --locked alef-cli
  echo "Alef installed from main branch"
}

if ! command -v alef >/dev/null 2>&1; then
  if [[ "$version" == "main" ]]; then
    install_from_main
  else
    # Try the released binary first. If the pinned tag has no published
    # binary yet (the polyglot repo bumped to an unreleased alef version),
    # fall back to building the matching git tag from source, then to main
    # if even the tag is not yet present (alef workspace bumped locally
    # but neither published nor tagged).
    if ! install_from_release; then
      resolved_version="$(resolve_version)"
      echo "Falling back to cargo install --git --tag v${resolved_version} alef-cli ..."
      ensure_cargo
      CARGO_INSTALL_ROOT="$alef_bin_dir/.." \
        cargo install \
        --git https://github.com/kreuzberg-dev/alef \
        --tag "v${resolved_version}" \
        --locked \
        alef-cli ||
        CARGO_INSTALL_ROOT="$alef_bin_dir/.." \
          cargo install \
          --git https://github.com/kreuzberg-dev/alef \
          --branch main \
          --locked \
          alef-cli
    fi
  fi
else
  echo "Alef already installed: $(command -v alef)"
fi

if [[ ! -x "$alef_bin_dir/alef" ]] && ! command -v alef >/dev/null 2>&1; then
  echo "Error: alef binary not found or not executable" >&2
  exit 1
fi

echo "Alef is ready"
echo "$alef_bin_dir" >>"$GITHUB_PATH"
