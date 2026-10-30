#!/usr/bin/env bash
# Write the npm registry auth that actions/setup-node's registry-url wrote: an .npmrc in RUNNER_TEMP whose
# token is read from NODE_AUTH_TOKEN when npm or pnpm runs, exported as NPM_CONFIG_USERCONFIG.
#
# usage: configure-registry.sh <registry-url>
set -euo pipefail

registry_url="${1:?registry url required}"
if [[ ! "$registry_url" =~ ^https?://[^[:space:]]+$ ]]; then
  echo "::error::registry-url must be an http(s) URL, got '$registry_url'" >&2
  exit 1
fi
[[ "$registry_url" == */ ]] || registry_url="$registry_url/"

# setup-node scopes the GitHub Packages registry to the repository owner. ~keep
scope=""
if [[ "$registry_url" == *npm.pkg.github.com* && -n "${GITHUB_REPOSITORY_OWNER:-}" ]]; then
  scope="@$(tr '[:upper:]' '[:lower:]' <<<"$GITHUB_REPOSITORY_OWNER"):"
fi

npmrc="${RUNNER_TEMP:?RUNNER_TEMP is not set}/.npmrc"
contents=""
if [[ -f "$npmrc" ]]; then
  contents="$(grep -viE "^${scope}registry" "$npmrc" || true)"
  [[ -z "$contents" ]] || contents+=$'\n'
fi
# The literal ${NODE_AUTH_TOKEN} is expanded by npm and pnpm at read time; the token never lands in the file. ~keep
# shellcheck disable=SC2016
contents+="${registry_url#*:}:_authToken=\${NODE_AUTH_TOKEN}"$'\n'"${scope}registry=${registry_url}"
printf '%s\n' "$contents" >"$npmrc"
echo "NPM_CONFIG_USERCONFIG=$npmrc" >>"$GITHUB_ENV"

# Like setup-node: npm fails on an unset variable in .npmrc, so an unset token is exported as setup-node's
# placeholder, which publish-npm treats as unset. A set token is never written to GITHUB_ENV, so a token the
# caller scoped to this step does not reach later steps. ~keep
if [[ -z "${NODE_AUTH_TOKEN:-}" ]]; then
  echo "NODE_AUTH_TOKEN=XXXXX-XXXXX-XXXXX-XXXXX" >>"$GITHUB_ENV"
fi
echo "Wrote ${scope}registry=${registry_url} to $npmrc"
