#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN"
	export PATH="$BIN:$PATH" HOME="$ROOT/home" GITHUB_OUTPUT="$ROOT/out"
	cd "$ROOT" || return 1
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/build.sh"
}

@test "should_return_error_when_crate_name_is_empty" {
	export INPUT_CRATE_NAME=
	run bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[ "$output" = "Error: INPUT_CRATE_NAME is required" ]
}

@test "should_write_dry_run_outputs_using_default_names" {
	xberg_stub sed 'input=$(cat); [ "$input" = my_crate ] && { printf "MyCrate\n"; exit 0; }; /usr/bin/sed "$@" <<<"$input"'
	export INPUT_CRATE_NAME=my-crate INPUT_DRY_RUN=true INPUT_OUTPUT_DIR="$ROOT/dist"
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"xcframework:       MyCrate"* ]]
	[ "$(cat "$GITHUB_OUTPUT")" = $'xcframework-path='"$ROOT"$'/dist/MyCrate.xcframework\nxcframework-zip='"$ROOT"$'/dist/MyCrate.xcframework.zip\nchecksum=placeholder-dry-run' ]
}

@test "should_build_archive_checksum_and_include_existing_headers" {
	mkdir -p headers
	xberg_stub rustup 'printf "%s\n" "$*" > "'"$ROOT"'/rustup.args"'
	xberg_stub cargo 'target="${@: -1}"; mkdir -p "target/$target/release"; touch "target/$target/release/libmy_lib.a"'
	xberg_stub xcodebuild 'mkdir -p "${@: -1}"; printf framework >"${@: -1}/marker"'
	xberg_stub zip 'touch "$2"'
	xberg_stub swift 'echo abc123'
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_XCFRAMEWORK_NAME=Kit INPUT_HEADER_PATH="$ROOT/headers" INPUT_OUTPUT_DIR="$ROOT/dist"
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"Checksum: abc123"* ]]
	[ "$(cat "$GITHUB_OUTPUT")" = $'xcframework-path='"$ROOT"$'/dist/Kit.xcframework\nxcframework-zip='"$ROOT"$'/dist/Kit.xcframework.zip\nchecksum=abc123' ]
	[ -f "$ROOT/dist/Kit.xcframework.zip" ]
}
