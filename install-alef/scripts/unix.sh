#!/usr/bin/env bash
set -euo pipefail

# Install alef under $HOME/.local/bin on Linux/macOS. The composite action
# resolves "latest" / "main" / a tag to a concrete install ref before invoking
# this script and handles caching + PATH wiring itself, so this script only
# deals with the actual download + (optional) source build.
#
# Argument:
#   install_ref  "main" to build the current main commit, otherwise a bare
#                semver (e.g. "0.17.8") to install — first via the GitHub
#                Releases tarball, then by `cargo install --git --tag` as a
#                fallback when the release binary is missing/late.

install_ref="${1:?install ref required}"

alef_bin_dir="${HOME}/.local/bin"
mkdir -p "$alef_bin_dir"

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

install_from_release() {
  local version="$1" target max_attempts=3 attempt=1 wait_time=2
  target="$(detect_target)"
  local url="https://github.com/kreuzberg-dev/alef/releases/download/v${version}/alef-${target}.tar.gz"

  while [[ $attempt -le $max_attempts ]]; do
    echo "Installing alef v${version} for ${target} (attempt ${attempt}/${max_attempts})..."

    if curl --location \
      --connect-timeout 10 \
      --max-time 60 \
      --retry 2 \
      --retry-delay 1 \
      --fail \
      "$url" | tar xz --strip-components=1 -C "$alef_bin_dir"; then

      if [[ -x "$alef_bin_dir/alef" ]]; then
        echo "Alef v${version} installed successfully"
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

  echo "Failed to download alef release binary after ${max_attempts} attempts" >&2
  return 1
}

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

build_from_source() {
  local ref="$1"
  ensure_cargo
  if [[ "$ref" == "main" ]]; then
    echo "Building alef from main branch via cargo install..."
    CARGO_INSTALL_ROOT="$alef_bin_dir/.." \
      cargo install \
      --git https://github.com/kreuzberg-dev/alef \
      --branch main \
      --locked \
      alef
  else
    echo "Building alef v${ref} from source via cargo install --tag..."
    if ! CARGO_INSTALL_ROOT="$alef_bin_dir/.." \
      cargo install \
      --git https://github.com/kreuzberg-dev/alef \
      --tag "v${ref}" \
      --locked \
      alef; then
      echo "Tag build failed; falling back to main branch..." >&2
      CARGO_INSTALL_ROOT="$alef_bin_dir/.." \
        cargo install \
        --git https://github.com/kreuzberg-dev/alef \
        --branch main \
        --locked \
        alef
    fi
  fi
}

if [[ "$install_ref" == "main" ]]; then
  build_from_source main
else
  install_from_release "$install_ref" || build_from_source "$install_ref"
fi

if [[ ! -x "$alef_bin_dir/alef" ]]; then
  echo "Error: alef binary not found at $alef_bin_dir/alef after install" >&2
  exit 1
fi

echo "Alef is ready at $alef_bin_dir/alef"
