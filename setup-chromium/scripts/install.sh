#!/usr/bin/env bash
set -euo pipefail

workdir="${RUNNER_TEMP:-/tmp}/setup-chromium-$$"
mkdir -p "$workdir"
cd "$workdir"

printf '%s\n' '{ "name": "chromium-installer", "version": "1.0.0", "private": true }' >package.json

# npm and npx ship with every Node.js release; pnpm does not, and setup-node does not install it.
npm install --no-audit --no-fund --silent "playwright@${PLAYWRIGHT_VERSION:-^1.49.0}"

install_args=(install)
if [ "${RUNNER_OS:-}" = "Linux" ]; then
  install_args+=(--with-deps)
fi
npx --no-install playwright "${install_args[@]}" chromium

chromium_path="$(node -e "console.log(require('playwright').chromium.executablePath())")"
if [ -z "$chromium_path" ] || [ ! -x "$chromium_path" ]; then
  echo "ERROR: Chromium binary not found at: $chromium_path" >&2
  exit 1
fi

echo "Chromium binary: $chromium_path"
echo "chromium-path=$chromium_path" >>"$GITHUB_OUTPUT"
