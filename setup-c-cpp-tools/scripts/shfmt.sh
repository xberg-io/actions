#!/usr/bin/env bash
set -euo pipefail

# ~keep shfmt's output gates `poly fmt --check` and every shell file `alef generate` emits, and
# poly skips shell entirely when shfmt is absent rather than failing. That silence is how
# unformatted generated scripts reach main: html-to-markdown run 35080918605 regenerated
# e2e/c/download_ffi.sh without formatting and failed the drift check against a tree formatted by
# a local shfmt. Distro packages lag the release badly, so a pinned release binary is the only
# source that gives every platform the same formatter.
SHFMT_VERSION="${SHFMT_VERSION:?shfmt version required}"

if command -v shfmt >/dev/null 2>&1; then
  installed="$(shfmt --version 2>/dev/null | tr -d 'v')"
  if [[ "$installed" == "$SHFMT_VERSION" ]]; then
    echo "shfmt $SHFMT_VERSION already installed."
    exit 0
  fi
fi

case "$(uname -s)" in
Linux) shfmt_os="linux" ;;
Darwin) shfmt_os="darwin" ;;
*)
  echo "::error::unsupported operating system for shfmt: $(uname -s)" >&2
  exit 1
  ;;
esac

case "$(uname -m)" in
x86_64 | amd64) shfmt_arch="amd64" ;;
arm64 | aarch64) shfmt_arch="arm64" ;;
*)
  echo "::error::unsupported architecture for shfmt: $(uname -m)" >&2
  exit 1
  ;;
esac

install_dir="${RUNNER_TEMP:-/tmp}/shfmt"
mkdir -p "$install_dir"
curl -fsSL -o "$install_dir/shfmt" \
  "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_${shfmt_os}_${shfmt_arch}"
chmod +x "$install_dir/shfmt"

echo "$install_dir" >>"$GITHUB_PATH"
"$install_dir/shfmt" --version
