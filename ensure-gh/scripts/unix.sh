#!/usr/bin/env bash
set -euo pipefail

version="${1:?version required}"

if command -v gh >/dev/null 2>&1; then
  echo "gh already installed: $(command -v gh) ($(gh --version | head -1))"
  exit 0
fi

bin_dir="${HOME}/.local/bin"
mkdir -p "$bin_dir"

detect_target() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
  Linux)
    case "$arch" in
    x86_64) echo "linux_amd64" ;;
    aarch64 | arm64) echo "linux_arm64" ;;
    *)
      echo "Error: unsupported Linux architecture: $arch" >&2
      return 1
      ;;
    esac
    ;;
  Darwin)
    case "$arch" in
    arm64) echo "macOS_arm64" ;;
    x86_64) echo "macOS_amd64" ;;
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

resolve_version() {
  if [[ "$version" != "latest" ]]; then
    echo "${version#v}"
    return 0
  fi
  local tag auth_args=()
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    auth_args=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  tag="$(curl --silent --fail "${auth_args[@]}" \
    "https://api.github.com/repos/cli/cli/releases/latest" |
    grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')"
  if [[ -z "$tag" ]]; then
    echo "Error: could not resolve latest gh release" >&2
    return 1
  fi
  echo "$tag"
}

resolved_version="$(resolve_version)"
target="$(detect_target)"

case "$target" in
linux_*) ext="tar.gz" ;;
macOS_*) ext="zip" ;;
esac

archive_name="gh_${resolved_version}_${target}.${ext}"
url="https://github.com/cli/cli/releases/download/v${resolved_version}/${archive_name}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

echo "Downloading gh v${resolved_version} (${target})..."
curl --location --silent --show-error --fail \
  --connect-timeout 10 --max-time 120 \
  --retry 3 --retry-delay 2 \
  --output "${tmp_dir}/${archive_name}" \
  "$url"

case "$ext" in
tar.gz)
  tar -xzf "${tmp_dir}/${archive_name}" -C "$tmp_dir"
  ;;
zip)
  unzip -q "${tmp_dir}/${archive_name}" -d "$tmp_dir"
  ;;
esac

extracted_gh="${tmp_dir}/gh_${resolved_version}_${target}/bin/gh"
if [[ ! -x "$extracted_gh" ]]; then
  echo "Error: gh binary not found at expected path ${extracted_gh}" >&2
  ls -la "$tmp_dir" >&2
  exit 1
fi

mv "$extracted_gh" "$bin_dir/gh"
chmod +x "$bin_dir/gh"

echo "gh v${resolved_version} installed at $bin_dir/gh"
echo "$bin_dir" >>"$GITHUB_PATH"
