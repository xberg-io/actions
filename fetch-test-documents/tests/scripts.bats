#!/usr/bin/env bats

setup() {
	ACTION_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$TEST_ROOT/bin"
	mkdir -p "$STUB_BIN"
	ORIGINAL_PATH="$PATH"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

@test "should_emit_stable_cache_key_when_patterns_are_trimmed_and_sorted" {
	manifest="$TEST_ROOT/corpus.lock.json"
	output_file="$TEST_ROOT/github-output"
	printf '{"objects":{}}' >"$manifest"

	run env INCLUDE_PATTERNS=$' z/** \n a/** ' GITHUB_OUTPUT="$output_file" \
		bash "$ACTION_DIR/scripts/compute-cache-key.sh" "$manifest"

	[ "$status" -eq 0 ]
	[ "$output" = "" ]
	[ "$(cat "$output_file")" = $'key=fetch-test-documents-v1-897f5efad0c721d1e46f7d5f92a35be445c3d037a85ad0316e41ceb3b361b27a-1caf50ed4e802dbe3704314335f75d9e33a2c93c951c4c7f0988c4867c910f41\nrestore-prefix=fetch-test-documents-v1-897f5efad0c721d1e46f7d5f92a35be445c3d037a85ad0316e41ceb3b361b27a-' ]
}

@test "should_return_cached_object_without_calling_curl" {
	sha="a4d26868017c0ccffe2efe50944ef4211834660cca834c6e9f86dec6a88246fa"
	cache_dir="$TEST_ROOT/cache"
	mkdir -p "$cache_dir/objects"
	printf 'shared' >"$cache_dir/objects/$sha"
	printf '#!/usr/bin/env bash\nexit 99\n' >"$STUB_BIN/curl"
	chmod +x "$STUB_BIN/curl"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" \
		bash "$ACTION_DIR/scripts/download-object.sh" "$sha" fixtures "$cache_dir"

	[ "$status" -eq 0 ]
	[ "$output" = "cached: $sha" ]
	[ "$(cat "$cache_dir/objects/$sha")" = "shared" ]
}

@test "should_retry_curl_on_every_transport_error" {
	# curl's --retry only covers transient HTTP codes and timeouts; a reset connection (exit 35)
	# is retried only with --retry-all-errors, which is what a GCS download needs on a flaky runner.
	sha="cea23dd4b87e8b00d19fb9ccaaef93e97353c7353e2070f3baf05aeb3995dff4"
	cache_dir="$TEST_ROOT/cache"
	printf '%s\n' '#!/usr/bin/env bash' 'printf "%s\n" "$@" > "$TEST_ROOT/curl-args"' 'exit 35' >"$STUB_BIN/curl"
	chmod +x "$STUB_BIN/curl"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" TEST_ROOT="$TEST_ROOT" \
		bash "$ACTION_DIR/scripts/download-object.sh" "$sha" fixtures "$cache_dir"

	[ "$status" -eq 35 ]
	grep -qx -- '--retry-all-errors' "$TEST_ROOT/curl-args"
	grep -qx -- '--retry' "$TEST_ROOT/curl-args"
}

@test "should_return_checksum_error_when_downloaded_object_is_corrupt" {
	expected_sha="cea23dd4b87e8b00d19fb9ccaaef93e97353c7353e2070f3baf05aeb3995dff4"
	cache_dir="$TEST_ROOT/cache"
	printf '%s\n' '#!/usr/bin/env bash' 'printf wrong > "${@: -1}"' >"$STUB_BIN/curl"
	chmod +x "$STUB_BIN/curl"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" \
		bash "$ACTION_DIR/scripts/download-object.sh" "$expected_sha" fixtures "$cache_dir"

	[ "$status" -eq 1 ]
	[ "$output" = $'downloading: https://storage.googleapis.com/fixtures/objects/cea23dd4b87e8b00d19fb9ccaaef93e97353c7353e2070f3baf05aeb3995dff4\n::error::checksum mismatch downloading https://storage.googleapis.com/fixtures/objects/cea23dd4b87e8b00d19fb9ccaaef93e97353c7353e2070f3baf05aeb3995dff4: expected cea23dd4b87e8b00d19fb9ccaaef93e97353c7353e2070f3baf05aeb3995dff4, got 8810ad581e59f2bc3928b261707a71308f7e139eb04820366dc4d5c18d980225' ]
	[ ! -e "$cache_dir/objects/$expected_sha" ]
}

@test "should_materialise_selected_cached_object_without_downloading" {
	sha="a4d26868017c0ccffe2efe50944ef4211834660cca834c6e9f86dec6a88246fa"
	manifest="$TEST_ROOT/corpus.lock.json"
	cache_dir="$TEST_ROOT/cache"
	target_dir="$TEST_ROOT/target"
	output_file="$TEST_ROOT/github-output"
	mkdir -p "$cache_dir/objects"
	printf '{"objects":{}}' >"$manifest"
	printf 'shared' >"$cache_dir/objects/$sha"
	printf '%s\n' '#!/usr/bin/env bash' \
		'printf "nested/example.txt\ta4d26868017c0ccffe2efe50944ef4211834660cca834c6e9f86dec6a88246fa\t6\n"' \
		>"$STUB_BIN/jq"
	printf '#!/usr/bin/env bash\nexit 99\n' >"$STUB_BIN/curl"
	chmod +x "$STUB_BIN/jq" "$STUB_BIN/curl"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" BUCKET=fixtures CACHE_DIR="$cache_dir" \
		CONCURRENCY=2 INCLUDE_PATTERNS='nested/**' GITHUB_OUTPUT="$output_file" \
		bash "$ACTION_DIR/scripts/fetch.sh" "$manifest" "$target_dir"

	[ "$status" -eq 0 ]
	[ "$output" = $'All selected objects already cached and verified; nothing to download.\nMatched 1 path(s) across 1 unique object(s); downloaded 0 object(s), 0 byte(s).' ]
	[ "$(cat "$target_dir/nested/example.txt")" = "shared" ]
	[ "$(cat "$output_file")" = $'objects-fetched=0\nbytes-fetched=0' ]
}

@test "should_return_error_when_concurrency_is_zero" {
	run env BUCKET=fixtures CACHE_DIR="$TEST_ROOT/cache" CONCURRENCY=0 \
		bash "$ACTION_DIR/scripts/fetch.sh" "$TEST_ROOT/missing.json" "$TEST_ROOT/target"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::concurrency must be a positive integer, got '0'" ]
}

@test "should_convert_windows_path_when_cygpath_is_available" {
	printf '%s\n' '#!/usr/bin/env bash' 'printf "/posix/%s" "$2"' >"$STUB_BIN/cygpath"
	chmod +x "$STUB_BIN/cygpath"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" bash -c \
		'source "$1"; to_posix_path "D:\a\_temp"' -- "$ACTION_DIR/scripts/lib.sh"

	[ "$status" -eq 0 ]
	[ "$output" = "/posix/D:\a\_temp" ]
}
