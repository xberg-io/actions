#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ACTION_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	mkdir -p "$STUB_BIN" "$TEST_ROOT/work"
	ORIGINAL_PATH="$PATH"
	printf '%s\n' '#!/usr/bin/env bash' \
		'if [ "$2" = generate ]; then exit 0; fi' \
		'printf "suite failure\n" >&2' \
		'exit 3' >"$STUB_BIN/alef"
	chmod +x "$STUB_BIN/alef"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

@test "should_write_failed_result_and_log_when_test_apps_command_fails" {
	language="bats-contract-$(basename "$TEST_ROOT")"
	log_path="/tmp/test-apps-${language}.log"
	github_output="$TEST_ROOT/github-output"
	rm -f "$log_path"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" INPUT_LANGUAGE="$language" \
		INPUT_WORKING_DIRECTORY="$TEST_ROOT/work" GITHUB_OUTPUT="$github_output" \
		bash "$ACTION_DIR/scripts/run.sh"

	[ "$status" -eq 3 ]
	[ "$output" = "Generating test-apps for ${language}...
Running test-apps for ${language}...
suite failure
Test-apps for ${language}: exit_code=3, log=${log_path}" ]
	[ "$(cat "$github_output")" = "passed=false
exit-code=3
log-path=${log_path}" ]
	[ "$(cat "$log_path")" = "suite failure" ]
	rm -f "$log_path"
}
