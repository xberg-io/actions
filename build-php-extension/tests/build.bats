#!/usr/bin/env bats

bats_require_minimum_version 1.5.0

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN" "$ROOT/ws"
	export PATH="$BIN:$PATH" RUNNER_OS=Linux
	IN="$BATS_TEST_DIRNAME/../scripts/build-in-workspace.sh"
	OUT="$BATS_TEST_DIRNAME/../scripts/build-out-of-workspace.sh"
}

@test "should_print_workspace_extension_path_after_cargo_build" {
	xberg_stub cargo 'printf "%s\n" "$*" > "'"$ROOT"'/cargo.args"; mkdir -p "'"$ROOT"'/ws/target/release"; touch "'"$ROOT"'/ws/target/release/libextension.so"'
	export CARGO_FEATURES=php
	run bash "$IN" crate extension "$ROOT/ws"
	[ "$status" -eq 0 ]
	[ "$output" = "$ROOT/ws/target/release/libextension.so" ]
	[ "$(cat "$ROOT/cargo.args")" = "build --release --locked --package crate --target-dir $ROOT/ws/target --features php" ]
}

@test "should_return_error_when_workspace_build_does_not_create_extension" {
	xberg_stub cargo 'exit 0'
	run bash "$IN" crate extension "$ROOT/ws"
	[ "$status" -eq 1 ]
	[ "$output" = "Error: cargo build did not produce $ROOT/ws/target/release/libextension.so; check lib-name and crate-type" ]
}

@test "should_return_error_when_out_of_workspace_crate_is_missing" {
	run bash "$OUT" crate extension "$ROOT/ws"
	[ "$status" -eq 1 ]
	[ "$output" = "Error: crate directory not found at $ROOT/ws/packages/crate" ]
}

@test "should_build_copied_package_crate_and_print_only_extension_path" {
	mkdir -p "$ROOT/ws/packages/crate"
	printf '[package]\nname = "crate"\nversion = "1"\n' >"$ROOT/ws/packages/crate/Cargo.toml"
	printf '[workspace]\n' >"$ROOT/ws/Cargo.toml"
	xberg_stub cargo 'case "$1" in update) exit 0;; build) mkdir -p target/release; touch target/release/libextension.dylib;; esac'
	export RUNNER_OS=macOS
	run --separate-stderr bash "$OUT" crate extension "$ROOT/ws"
	[ "$status" -eq 0 ]
	[ "$output" = "$ROOT/ws/target/release/libextension.dylib" ]
	[ "$stderr" = "Stripped workspace inheritance from binding crate Cargo.toml" ]
	[ -f "$ROOT/ws/target/release/libextension.dylib" ]
}
