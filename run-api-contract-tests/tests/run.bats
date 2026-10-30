#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ACTION_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	TRACE="$TEST_ROOT/trace"
	mkdir -p "$STUB_BIN"
	ORIGINAL_PATH="$PATH"
	printf '%s\n' '#!/usr/bin/env bash' 'printf "pip3 %s\n" "$*" >>"$TRACE"' >"$STUB_BIN/pip3"
	printf '%s\n' '#!/usr/bin/env bash' \
		'printf "docker %s\n" "$*" >>"$TRACE"' \
		'if [ "$1" = run ]; then printf abcdef1234567890; fi' >"$STUB_BIN/docker"
	printf '%s\n' '#!/usr/bin/env bash' 'printf "sleep %s\n" "$*" >>"$TRACE"' >"$STUB_BIN/sleep"
	printf '%s\n' '#!/usr/bin/env bash' 'printf "schemathesis %s\n" "$*" >>"$TRACE"' \
		'exit "${SCHEMATHESIS_STATUS:-0}"' >"$STUB_BIN/schemathesis"
	chmod +x "$STUB_BIN/pip3" "$STUB_BIN/docker" "$STUB_BIN/sleep" "$STUB_BIN/schemathesis"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

@test "should_run_schemathesis_with_seconds_timeout_extra_arguments_and_cleanup" {
	run env PATH="$STUB_BIN:$ORIGINAL_PATH" TRACE="$TRACE" INPUT_IMAGE=api:test INPUT_PORT=8080 \
		INPUT_SPEC_PATH=/schema.json INPUT_STARTUP_WAIT_SECONDS=0 INPUT_MAX_EXAMPLES=4 \
		INPUT_REQUEST_TIMEOUT_MS=1250 INPUT_CHECKS=not_a_server_error INPUT_SCHEMATHESIS_VERSION='schemathesis==4.2.0' \
		INPUT_EXTRA_ARGS='--seed 42' bash "$ACTION_DIR/scripts/run.sh"

	[ "$status" -eq 0 ]
	[ "$output" = "Started container abcdef123456 (image=api:test, port=8080)" ]
	run cat "$TRACE"
	[ "$status" -eq 0 ]
	[ "$output" = $'pip3 install --quiet schemathesis==4.2.0\ndocker run -d -p 8080:8080 api:test\nsleep 0\nschemathesis run http://localhost:8080/schema.json --max-examples=4 --request-timeout=1.25 --checks not_a_server_error --seed 42\ndocker stop abcdef1234567890' ]
}

@test "should_return_schemathesis_failure_status_and_stop_container" {
	run env PATH="$STUB_BIN:$ORIGINAL_PATH" TRACE="$TRACE" INPUT_IMAGE=api:test \
		INPUT_STARTUP_WAIT_SECONDS=0 SCHEMATHESIS_STATUS=7 bash "$ACTION_DIR/scripts/run.sh"

	[ "$status" -eq 7 ]
	[ "$output" = "Started container abcdef123456 (image=api:test, port=8000)" ]
	[ "$(tail -n 1 "$TRACE")" = "docker stop abcdef1234567890" ]
}
