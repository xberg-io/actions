#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/setup.sh"
	BIN="$XBERG_STUB_BIN"
	export RUNNER_TEMP="$BATS_TEST_TMPDIR/tmp"
	export GITHUB_ENV="$BATS_TEST_TMPDIR/github-env"
	export GITHUB_OUTPUT="$BATS_TEST_TMPDIR/github-output"
	mkdir -p "$RUNNER_TEMP" "$BIN"
	: >"$GITHUB_ENV"
	: >"$GITHUB_OUTPUT"
	export PATH="$BIN:$PATH"
}

@test "should_reuse_cached_gpu_runtime_and_write_library_outputs" {
	local lib="$RUNNER_TEMP/onnxruntime/onnxruntime-linux-x64-gpu-1.20.0/lib"
	mkdir -p "$lib"
	touch "$lib/libonnxruntime.so.1"
	printf '%s\n' '#!/usr/bin/env bash' 'echo "listed: $*"' >"$BIN/ls"
	chmod +x "$BIN/ls"
	export INPUT_VERSION=1.20.0 INPUT_PLATFORM=linux-x64-gpu
	run "$SCRIPT"
	[ "$status" -eq 0 ]
	local expected_output expected_environment
	expected_output="$(printf 'Reusing cached ONNX Runtime at %s/onnxruntime/onnxruntime-linux-x64-gpu-1.20.0\nONNX Runtime GPU libraries staged at %s\nlisted: -la %s/libonnxruntime.so.1' "$RUNNER_TEMP" "$lib" "$lib")"
	expected_environment="$(printf 'ORT_DYLIB_PATH=%s/libonnxruntime.so\nLD_LIBRARY_PATH=%s:' "$lib" "$lib")"
	[ "$output" = "$expected_output" ]
	[ "$(cat "$GITHUB_ENV")" = "$expected_environment" ]
	[ "$(cat "$GITHUB_OUTPUT")" = "lib-dir=$lib" ]
}

@test "should_return_error_when_gpu_runtime_version_is_empty" {
	run env -u INPUT_VERSION "$SCRIPT"
	[ "$status" -eq 1 ]
	[ "$output" = "$SCRIPT: line 4: INPUT_VERSION: INPUT_VERSION is required" ]
}
