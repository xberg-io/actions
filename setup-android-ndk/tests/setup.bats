#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/setup.sh"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN"
	export PATH="$BIN:$PATH"
	export GITHUB_ENV="$BATS_TEST_TMPDIR/github-env"
	export GITHUB_PATH="$BATS_TEST_TMPDIR/github-path"
	export GITHUB_OUTPUT="$BATS_TEST_TMPDIR/github-output"
	: >"$GITHUB_ENV"
	: >"$GITHUB_PATH"
	: >"$GITHUB_OUTPUT"
}

@test "should_export_ndk_paths_and_add_each_requested_rust_target" {
	local home="$BATS_TEST_TMPDIR/android"
	local ndk="$home/ndk/26.3.11579264"
	local host="linux-x86_64"
	mkdir -p "$ndk/toolchains/llvm/prebuilt/$host/bin"
	xberg_stub uname 'set -eu' '[[ "$1" == "-s" ]] && echo Linux || echo x86_64'
	xberg_stub rustup 'set -eu' 'printf "%s\n" "$*" >>"$RUSTUP_CALLS"'
	xberg_stub cargo-ndk 'set -eu' 'exit 0'
	export RUSTUP_CALLS="$BATS_TEST_TMPDIR/rustup-calls"
	export ANDROID_HOME="$home" INPUT_NDK_VERSION=26.3.11579264
	export INPUT_TARGETS="aarch64-linux-android, x86_64-linux-android"
	export INPUT_INSTALL_CARGO_NDK=true
	run "$SCRIPT"
	[ "$status" -eq 0 ]
	local expected_environment
	expected_environment="$(printf 'ANDROID_NDK_HOME=%s\nANDROID_NDK_ROOT=%s\nNDK_HOME=%s' "$ndk" "$ndk" "$ndk")"
	[ "$(cat "$GITHUB_ENV")" = "$expected_environment" ]
	[ "$(cat "$GITHUB_PATH")" = "$ndk/toolchains/llvm/prebuilt/$host/bin" ]
	[ "$(cat "$GITHUB_OUTPUT")" = "ndk-home=$ndk" ]
	[ "$(cat "$RUSTUP_CALLS")" = $'target add aarch64-linux-android\ntarget add x86_64-linux-android' ]
}

@test "should_return_error_when_requested_ndk_version_is_absent" {
	export ANDROID_HOME="$BATS_TEST_TMPDIR/android" INPUT_NDK_VERSION=missing
	run "$SCRIPT"
	[ "$status" -eq 1 ]
	[ "$output" = "Error: ANDROID_HOME/ndk/missing not found" ]
}
