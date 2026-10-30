#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	mkdir -p "$STUB_BIN"
	export TEST_ROOT STUB_BIN
}

teardown() {
	rm -rf "$TEST_ROOT"
}

verify_script() {
	env PATH="$STUB_BIN:$PATH" \
		INPUT_LANGUAGE="$1" \
		INPUT_VERSION="1.2.3" \
		INPUT_PACKAGE_NAME="xberg" \
		INPUT_ARTIFACT_SOURCE="${2:-registry}" \
		INPUT_LOCAL_PATH="${3:-}" \
		INPUT_TEST_APPS_DIR="$TEST_ROOT/test_apps" \
		INPUT_SMOKE_ONLY="${4:-true}" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/verify.sh"
}

@test "verify should_return_error_when_language_test_application_is_missing" {
	run verify_script python

	[ "$status" -eq 1 ]
	[ "$output" = "::error::test_app directory not found: $TEST_ROOT/test_apps/python"$'\n'"Did you commit test_apps/, or set regenerate=true?" ]
}

@test "verify should_install_python_local_artifact_and_run_only_smoke_test" {
	mkdir -p "$TEST_ROOT/test_apps/python" "$TEST_ROOT/wheels"
	xberg_stub uv '#!/usr/bin/env bash' \
		'printf "%s|%s\n" "$PWD" "$*" >>"$COMMAND_LOG"'
	local command_log="$TEST_ROOT/commands"

	run env PATH="$STUB_BIN:$PATH" COMMAND_LOG="$command_log" \
		INPUT_LANGUAGE="python" INPUT_VERSION="1.2.3" INPUT_PACKAGE_NAME="xberg" \
		INPUT_ARTIFACT_SOURCE="local" INPUT_LOCAL_PATH="$TEST_ROOT/wheels" \
		INPUT_TEST_APPS_DIR="$TEST_ROOT/test_apps" INPUT_SMOKE_ONLY="true" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/verify.sh"

	[ "$status" -eq 0 ]
	[ "$(cat "$command_log")" = "$TEST_ROOT/test_apps/python|venv"$'\n'"$TEST_ROOT/test_apps/python|pip install --find-links $TEST_ROOT/wheels xberg==1.2.3"$'\n'"$TEST_ROOT/test_apps/python|pip install pytest pytest-asyncio pytest-timeout"$'\n'"$TEST_ROOT/test_apps/python|run pytest tests/test_smoke.py -v" ]
	[[ "$output" == *"verify-install: python OK (xberg @ 1.2.3)"* ]]
}

@test "verify should_return_error_when_node_local_artifact_directory_has_no_tarball" {
	mkdir -p "$TEST_ROOT/test_apps/node" "$TEST_ROOT/tarballs"

	run verify_script node local "$TEST_ROOT/tarballs"

	[ "$status" -eq 1 ]
	[[ "$output" == *"::error::no .tgz found in $TEST_ROOT/tarballs"* ]]
}

@test "verify should_run_full_rust_command_when_smoke_only_is_false" {
	mkdir -p "$TEST_ROOT/test_apps/rust"
	xberg_stub cargo '#!/usr/bin/env bash' 'printf "%s\n" "$*" >>"$COMMAND_LOG"'
	local command_log="$TEST_ROOT/commands"

	run env PATH="$STUB_BIN:$PATH" COMMAND_LOG="$command_log" \
		INPUT_LANGUAGE="rust" INPUT_VERSION="1.2.3" INPUT_PACKAGE_NAME="xberg" \
		INPUT_ARTIFACT_SOURCE="registry" INPUT_LOCAL_PATH="" \
		INPUT_TEST_APPS_DIR="$TEST_ROOT/test_apps" INPUT_SMOKE_ONLY="false" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/verify.sh"

	[ "$status" -eq 0 ]
	[ "$(cat "$command_log")" = "run --locked" ]
	[[ "$output" == *"verify-install: rust OK (xberg @ 1.2.3)"* ]]
}

@test "verify should_return_error_when_language_is_unknown" {
	mkdir -p "$TEST_ROOT/test_apps/unknown"

	run verify_script unknown

	[ "$status" -eq 1 ]
	[[ "$output" == *"::error::Unknown language: unknown"* ]]
}
