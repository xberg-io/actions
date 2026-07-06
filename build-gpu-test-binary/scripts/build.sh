#!/usr/bin/env bash
set -euo pipefail
set -o pipefail

package="${INPUT_PACKAGE:?INPUT_PACKAGE is required}"
test_name="${INPUT_TEST_NAME:?INPUT_TEST_NAME is required}"
features="${INPUT_FEATURES:-}"
output_name="${INPUT_OUTPUT_NAME:-gpu-test-binary}"
working_directory="${INPUT_WORKING_DIRECTORY:-.}"

if [[ "$working_directory" != "." ]]; then
	cd "$working_directory"
fi

cargo_args=(test --locked -p "$package")
if [[ -n "$features" ]]; then
	cargo_args+=(--features "$features")
fi
cargo_args+=(--test "$test_name" --no-run --message-format=json)

json_log=$(mktemp)
stderr_log=$(mktemp)
binary_path_file=$(mktemp)
trap 'rm -f "$json_log" "$stderr_log" "$binary_path_file"' EXIT

# Run cargo separately from the jq parse. Piped directly under `set -o pipefail`,
# a compile failure aborts the script at the pipeline before the diagnostic block
# below can print stderr, so every real error surfaced only as a bare "exit 101".
set +e
cargo "${cargo_args[@]}" >"$json_log" 2>"$stderr_log"
cargo_status=$?
set -e

if [[ "$cargo_status" -ne 0 ]]; then
	echo "::error::cargo ${cargo_args[*]} failed (exit ${cargo_status}); stderr below:" >&2
	cat "$stderr_log" >&2
	exit "$cargo_status"
fi

jq -r 'select(.executable != null) | .executable' <"$json_log" |
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
