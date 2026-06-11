#!/usr/bin/env bash
set -euo pipefail

# Install Homebrew (linuxbrew) on a Linux runner so we can build bottles.
# No-op if brew is already on PATH.

if command -v brew >/dev/null 2>&1; then
  echo "brew already on PATH: $(command -v brew)"
  exit 0
fi

# Recent Homebrew requires bubblewrap (bwrap) on PATH for the Linux build
# sandbox. ubuntu-latest runners don't ship it, and brew cannot install it
# from formula because the sandbox must exist before any `brew install` runs.
if ! command -v bwrap >/dev/null 2>&1; then
  echo "Installing bubblewrap for Homebrew Linux sandbox..."
  sudo apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends bubblewrap
fi

echo "Installing Homebrew..."
NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew_prefix=""
for candidate in /home/linuxbrew/.linuxbrew /opt/homebrew /usr/local; do
  if [[ -x "${candidate}/bin/brew" ]]; then
    brew_prefix="$candidate"
    break
  fi
done

if [[ -z "$brew_prefix" ]]; then
  echo "Could not locate brew prefix after install" >&2
  exit 1
fi

echo "${brew_prefix}/bin" >>"${GITHUB_PATH:-/dev/null}"
eval "$(${brew_prefix}/bin/brew shellenv)"

brew --version
