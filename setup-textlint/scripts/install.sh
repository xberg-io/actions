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

npm install --no-save "${packages[@]}"
