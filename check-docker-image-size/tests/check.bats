#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN"
	export PATH="$BIN:$PATH" GITHUB_OUTPUT="$ROOT/out" GITHUB_STEP_SUMMARY="$ROOT/summary"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/check.sh"
}

@test "should_return_shell_error_when_image_is_missing" {
	run bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"INPUT_IMAGE is required"* ]]
}

@test "should_return_error_when_image_is_not_local" {
	xberg_stub docker 'exit 1'
	export INPUT_IMAGE=example:tag
	run bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[ "$output" = "::error::image not found locally: example:tag" ]
}

@test "should_emit_warning_summary_and_size_for_threshold_branch" {
	xberg_stub docker 'if [ "$3" = "--format={{.Size}}" ]; then echo 3145728; else exit 0; fi'
	export INPUT_IMAGE=example:tag INPUT_LABEL=runtime INPUT_WARN_MB=2 INPUT_FAIL_MB=4
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$output" = $'Image: example:tag\nSize:  3MB\n::warning::runtime is larger than 2MB (3MB)' ]
	[ "$(cat "$GITHUB_OUTPUT")" = "size-mb=3" ]
	[ "$(cat "$GITHUB_STEP_SUMMARY")" = "- **runtime**: 3MB" ]
}

@test "should_fail_when_size_exceeds_fail_threshold" {
	xberg_stub docker 'if [ "$3" = "--format={{.Size}}" ]; then echo 3145728; else exit 0; fi'
	export INPUT_IMAGE=example INPUT_FAIL_MB=2
	run bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"::error::example exceeds fail threshold (3MB > 2MB)"* ]]
}
