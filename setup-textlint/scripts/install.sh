#!/usr/bin/env bash
set -euo pipefail

packages=(
  textlint
  textlint-rule-no-todo
  textlint-rule-no-start-duplicated-conjunction
  textlint-rule-no-empty-section
  textlint-rule-terminology
  textlint-rule-no-zero-width-spaces
  '@textlint-rule/textlint-rule-no-invalid-control-character'
  textlint-rule-no-surrogate-pair
  '@textlint-rule/textlint-rule-no-unmatched-pair'
  textlint-rule-alex
  textlint-rule-write-good
  textlint-rule-common-misspellings
  textlint-rule-stop-words
  textlint-rule-en-capitalization
  textlint-filter-rule-comments
  textlint-filter-rule-node-types
)

if [[ -n "${INPUT_EXTRA_PACKAGES:-}" ]]; then
  read -r -a extras <<<"$INPUT_EXTRA_PACKAGES"
  packages+=("${extras[@]}")
fi

# A project directory, not `pnpm add -g`: pnpm 12 puts each global install in its own hashed directory, where
# textlint cannot load the rules installed beside it ("Failed to load packages").
install_dir="${TEXTLINT_DIR:-${RUNNER_TEMP:?RUNNER_TEMP or TEXTLINT_DIR must be set}/textlint}"
mkdir -p "$install_dir"
printf '%s\n' '{ "name": "textlint-installer", "private": true }' >"$install_dir/package.json"

pnpm add --dir "$install_dir" --ignore-scripts --config.strict-peer-dependencies=false "${packages[@]}"

echo "$install_dir/node_modules/.bin" >>"$GITHUB_PATH"
echo "NODE_PATH=$install_dir/node_modules" >>"$GITHUB_ENV"
