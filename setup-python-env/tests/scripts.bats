#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT_DIR="$(cd "$BATS_TEST_DIRNAME/../scripts" && pwd)"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN"
	export PATH="$BIN:$PATH"
	export GITHUB_ENV="$BATS_TEST_TMPDIR/github-env"
	export GITHUB_OUTPUT="$BATS_TEST_TMPDIR/github-output"
	: >"$GITHUB_ENV"
	: >"$GITHUB_OUTPUT"
}

@test "should_pin_requested_python_version_with_uv" {
	xberg_stub uv 'set -eu' 'printf "%s\n" "$*" >"$UV_CALL"'
	export UV_CALL="$BATS_TEST_TMPDIR/uv-call"
	run "$SCRIPT_DIR/pin-python.sh" 3.12
	[ "$status" -eq 0 ]
	[ "$(cat "$UV_CALL")" = "python pin 3.12" ]
}

@test "should_return_error_when_python_version_is_empty" {
	run "$SCRIPT_DIR/pin-python.sh"
	[ "$status" -eq 1 ]
	[ "$output" = "$SCRIPT_DIR/pin-python.sh: line 4: 1: python version required" ]
}

@test "should_preserve_pkg_config_path_in_github_environment" {
	export PKG_CONFIG_PATH="/opt/lib/pkgconfig"
	run "$SCRIPT_DIR/preserve-pkg-config-path.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "Preserved PKG_CONFIG_PATH: /opt/lib/pkgconfig" ]
	[ "$(cat "$GITHUB_ENV")" = "PKG_CONFIG_PATH=/opt/lib/pkgconfig" ]
}

@test "should_write_no_lock_value_when_uv_lock_is_missing" {
	local work="$BATS_TEST_TMPDIR/work"
	mkdir -p "$work"
	run bash -c 'cd "$1" && "$2/uv-lock-hash.sh"' _ "$work" "$SCRIPT_DIR"
	[ "$status" -eq 0 ]
	[ "$output" = "uv.lock not found, using fallback hash" ]
	[ "$(cat "$GITHUB_OUTPUT")" = "value=no-uv-lock" ]
}
