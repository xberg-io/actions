#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT_DIR="$(cd "$BATS_TEST_DIRNAME/../scripts" && pwd)"
	export RUNNER_TEMP="$BATS_TEST_TMPDIR/tmp"
	export GITHUB_WORKSPACE="$BATS_TEST_TMPDIR/work"
	export GITHUB_ENV="$BATS_TEST_TMPDIR/github-env"
	mkdir -p "$RUNNER_TEMP" "$GITHUB_WORKSPACE"
	: >"$GITHUB_ENV"
}

@test "should_copy_cached_linux_runtime_and_write_system_link_outputs" {
	local root="$RUNNER_TEMP/onnxruntime/onnxruntime-linux-x64-1.20.0/lib"
	mkdir -p "$root"
	touch "$root/libonnxruntime.so.1"
	run "$SCRIPT_DIR/linux.sh" 1.20.0 ort x64 system
	[ "$status" -eq 0 ]
	[ "$output" = "Cache hit: Using cached ONNX Runtime 1.20.0" ]
	[ -f "$GITHUB_WORKSPACE/ort/libonnxruntime.so.1" ]
	local expected
	expected="$(printf 'ORT_LIB_LOCATION=%s\nORT_PREFER_DYNAMIC_LINK=1\nORT_SKIP_DOWNLOAD=1\nORT_STRATEGY=system\nORT_DYLIB_PATH=%s/libonnxruntime.so.1\nLD_LIBRARY_PATH=%s:%s/ort:\nLIBRARY_PATH=%s:%s/ort:\nRUSTFLAGS=-L %s' "$root" "$root" "$root" "$GITHUB_WORKSPACE" "$root" "$GITHUB_WORKSPACE" "$root")"
	[ "$(cat "$GITHUB_ENV")" = "$expected" ]
}

@test "should_return_error_when_linux_arch_id_is_unsupported" {
	run "$SCRIPT_DIR/linux.sh" 1.20.0 ort sparc
	[ "$status" -eq 1 ]
	[ "$output" = "Unsupported Linux arch-id: sparc" ]
}

@test "should_copy_cached_macos_runtime_and_write_system_link_outputs" {
	local root="$RUNNER_TEMP/onnxruntime/onnxruntime-osx-x86_64-1.20.0/lib"
	mkdir -p "$root"
	touch "$root/libonnxruntime.1.dylib"
	run "$SCRIPT_DIR/macos.sh" 1.20.0 ort x64 system
	[ "$status" -eq 0 ]
	[ "$output" = $'Using macOS ONNX Runtime arch: x86_64\nCache hit: Using cached ONNX Runtime 1.20.0' ]
	[ -f "$GITHUB_WORKSPACE/ort/libonnxruntime.1.dylib" ]
	[ "$(grep '^ORT_DYLIB_PATH=' "$GITHUB_ENV")" = "ORT_DYLIB_PATH=$root/libonnxruntime.1.dylib" ]
}

@test "should_return_error_when_macos_arch_id_is_unsupported" {
	run "$SCRIPT_DIR/macos.sh" 1.20.0 ort ppc
	[ "$status" -eq 1 ]
	[ "$output" = "Unsupported macOS arch-id: ppc" ]
}
