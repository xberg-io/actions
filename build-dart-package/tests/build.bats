#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN" "$ROOT/pkg" "$ROOT/target/release"
	export PATH="$BIN:$PATH" GITHUB_WORKSPACE="$ROOT" CARGO_TARGET_DIR="$ROOT/target" RUNNER_OS=Linux
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/build.sh"
}

@test "should_print_release_dry_run_path_without_running_tools" {
	export INPUT_DRY_RUN=true INPUT_CRATE_NAME=my-crate GITHUB_OUTPUT="$ROOT/output"
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$output" = $'[dry-run] cd packages/dart && flutter_rust_bridge_codegen generate\n[dry-run] cargo build --locked --manifest-path packages/dart/Cargo.toml --release\n[dry-run] expected library: '"$ROOT"$'/target/release/libmy_crate.so' ]
	[ "$(cat "$GITHUB_OUTPUT")" = "library-path=$ROOT/target/release/libmy_crate.so" ]
}

@test "should_return_error_when_package_directory_is_missing" {
	export INPUT_PACKAGE_DIR="$ROOT/missing"
	run bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[ "$output" = "Error: package-dir '$ROOT/missing' does not exist" ]
}

@test "should_use_discovered_library_when_expected_name_is_absent" {
	xberg_stub flutter_rust_bridge_codegen 'exit 0'
	xberg_stub cargo 'if [ "$1" = build ]; then exit 0; fi; printf "{\"target_directory\":\"%s/target\"}\n" "$GITHUB_WORKSPACE"'
	xberg_stub jq 'sed -n "s/.*\"target_directory\":\"\\([^\"]*\\)\".*/\\1/p"'
	touch "$ROOT/target/release/libmy_crate_v2.so"
	export INPUT_PACKAGE_DIR="$ROOT/pkg" INPUT_CRATE_NAME=my-crate GITHUB_OUTPUT="$ROOT/output"
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"Resolved library: $ROOT/target/release/libmy_crate_v2.so"* ]]
	[ "$(cat "$GITHUB_OUTPUT")" = "library-path=$ROOT/target/release/libmy_crate_v2.so" ]
}
