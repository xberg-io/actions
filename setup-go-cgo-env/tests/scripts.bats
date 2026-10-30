#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT_DIR="$(cd "$BATS_TEST_DIRNAME/../scripts" && pwd)"
	WORK="$BATS_TEST_TMPDIR/work"
	mkdir -p "$WORK/target/release"
	export GITHUB_WORKSPACE="$WORK"
	export GITHUB_ENV="$BATS_TEST_TMPDIR/github-env"
	: >"$GITHUB_ENV"
	export PKG_CONFIG_PATH='' LD_LIBRARY_PATH='' DYLD_LIBRARY_PATH='' DYLD_FALLBACK_LIBRARY_PATH=''
}

@test "should_write_cgo_environment_with_rpath_for_existing_ffi_directory" {
	run "$SCRIPT_DIR/unix.sh" target/release true crates/xberg-ffi xberg_ffi
	[ "$status" -eq 0 ]
	local expected
	expected="$(printf 'PKG_CONFIG_PATH=%s/crates/xberg-ffi:\nLD_LIBRARY_PATH=%s/target/release:\nDYLD_LIBRARY_PATH=%s/target/release:\nDYLD_FALLBACK_LIBRARY_PATH=%s/target/release:\nCGO_ENABLED=1\nCGO_CFLAGS=-I%s/crates/xberg-ffi/include\nCGO_LDFLAGS=-L%s/target/release -lxberg_ffi -Wl,-rpath,%s/target/release' "$WORK" "$WORK" "$WORK" "$WORK" "$WORK" "$WORK" "$WORK")"
	[ "$(cat "$GITHUB_ENV")" = "$expected" ]
}

@test "should_return_error_when_ffi_library_directory_is_missing" {
	run "$SCRIPT_DIR/unix.sh" missing
	[ "$status" -eq 1 ]
	[ "$output" = "Error: FFI library directory not found: $WORK/missing" ]
}

@test "should_report_missing_ffi_library_files_without_failing_verification" {
	export RUNNER_OS=Linux
	run "$SCRIPT_DIR/verify.sh" target/release xberg_ffi
	[ "$status" -eq 0 ]
	[[ "$output" == *"FFI library directory: $WORK/target/release"* ]]
	[[ "$output" == *"No libxberg_ffi files found"* ]]
}
