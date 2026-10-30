#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN" "$ROOT/pkg"
	export PATH="$BIN:$PATH" GITHUB_WORKSPACE="$ROOT" CARGO_TARGET_DIR="$ROOT/target"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/build.sh"
}

@test "should_describe_debug_dry_run" {
	export INPUT_DRY_RUN=true INPUT_BUILD_PROFILE=debug INPUT_CRATE_NAME=my-bridge
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"cargo build --locked -p my-bridge "* ]]
	[[ "$output" == *"$ROOT/target/debug/build/my-bridge-*/out"* ]]
}

@test "should_return_error_when_package_directory_is_missing" {
	export INPUT_PACKAGE_DIR="$ROOT/nope"
	run bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[ "$output" = "Error: package-dir '$ROOT/nope' does not exist" ]
}

@test "should_combine_headers_and_normalize_core_swift_extensions" {
	OUT="$ROOT/target/release/build/my-bridge-a/out"
	mkdir -p "$OUT/my-bridge"
	printf 'CORE\n' >"$OUT/SwiftBridgeCore.h"
	printf 'CRATE\n' >"$OUT/my-bridge/my-bridge.h"
	printf 'extension RustStr: Identifiable {\n' >"$OUT/SwiftBridgeCore.swift"
	printf 'public func bridge() {}\n' >"$OUT/my-bridge/Bridge.swift"
	xberg_stub cargo 'exit 0'
	export INPUT_PACKAGE_DIR="$ROOT/pkg" INPUT_CRATE_NAME=my-bridge
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$(cat "$ROOT/pkg/Sources/RustBridgeC/RustBridgeC.h")" = $'CORE\nCRATE' ]
	[ "$(cat "$ROOT/pkg/Sources/RustBridge/SwiftBridgeCore.swift")" = $'import RustBridgeC\nextension RustStr: @retroactive Identifiable {' ]
	[ "$(cat "$ROOT/pkg/Sources/RustBridge/Bridge.swift")" = $'import RustBridgeC\npublic func bridge() {}' ]
}
