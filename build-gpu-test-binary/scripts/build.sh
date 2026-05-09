#!/usr/bin/env bash
set -euo pipefail
set -o pipefail

package="${INPUT_PACKAGE:?INPUT_PACKAGE is required}"
test_name="${INPUT_TEST_NAME:?INPUT_TEST_NAME is required}"
features="${INPUT_FEATURES:-}"
output_name="${INPUT_OUTPUT_NAME:-gpu-test-binary}"

cargo_args=(test -p "$package")
if [[ -n "$features" ]]; then
  cargo_args+=(--features "$features")
fi
cargo_args+=(--test "$test_name" --no-run --message-format=json)

stderr_log=$(mktemp)
binary_path_file=$(mktemp)
trap 'rm -f "$stderr_log" "$binary_path_file"' EXIT

cargo "${cargo_args[@]}" 2>"$stderr_log" |
  jq -r 'select(.executable != null) | .executable' |
  head -1 >"$binary_path_file"

if [[ ! -s "$binary_path_file" ]]; then
  echo "::error::cargo test produced no executable; stderr below:" >&2
  cat "$stderr_log" >&2
  exit 1
fi

test_bin=$(cat "$binary_path_file")
echo "Test binary: $test_bin"
cp "$test_bin" "$output_name"
chmod +x "$output_name"
echo "Staged: $output_name"

abs_path=$(readlink -f "$output_name")
echo "binary-path=${abs_path}" >>"$GITHUB_OUTPUT"
