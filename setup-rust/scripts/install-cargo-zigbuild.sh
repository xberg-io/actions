#!/usr/bin/env bash
set -euo pipefail

revision="${1:-}"
if [ -z "$revision" ]; then
  exit 0
fi
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "cargo-zigbuild-revision must be a full lowercase 40-character commit SHA" >&2
  exit 1
fi

install_root=$(mktemp -d "${RUNNER_TEMP:?}/cargo-zigbuild.XXXXXX")
cargo install --locked --git https://github.com/rust-cross/cargo-zigbuild.git \
  --rev "$revision" --root "$install_root" cargo-zigbuild

# Version numbers also identify unreleased commits; Cargo records the complete source SHA. ~keep
source="git+https://github.com/rust-cross/cargo-zigbuild.git?rev=$revision#$revision)"
if ! grep -Fq "$source" "$install_root/.crates2.json"; then
  echo "cargo-zigbuild installed source revision does not match $revision" >&2
  exit 1
fi
binary="$install_root/bin/cargo-zigbuild"
if [ ! -x "$binary" ] && [ -x "$binary.exe" ]; then
  binary="$binary.exe"
fi
if [ ! -x "$binary" ]; then
  echo "cargo-zigbuild installation produced no executable" >&2
  exit 1
fi
printf '%s\n' "$install_root/bin" >>"${GITHUB_PATH:?}"
