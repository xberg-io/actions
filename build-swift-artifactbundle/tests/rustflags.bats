#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	export PATH="$XBERG_STUB_BIN:$PATH" GITHUB_WORKSPACE="$XBERG_WORK" CARGO_TARGET_DIR="$XBERG_WORK/target" GITHUB_OUTPUT="$XBERG_WORK/out"
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_ARTIFACT_NAME=Kit INPUT_OUTPUT_DIR="$XBERG_WORK/dist"
	unset RUSTFLAGS CARGO_ENCODED_RUSTFLAGS
	xberg_stub rustup 'exit 0'
	xberg_stub df 'printf "fixture 100 1 99 1%% /tmp\n"'
	xberg_stub zig 'echo 0.17.0'
	xberg_stub cargo-zigbuild 'exit 0'
	xberg_stub cargo 'python3 - "$@" <<'"'"'PY'"'"'
import json, os, sys
from pathlib import Path
target = sys.argv[-1]
expected_command = os.environ.get("EXPECTED_CARGO_COMMAND_JSON")
if expected_command is not None:
    assert sys.argv[1:] == json.loads(expected_command), sys.argv[1:]
encoded = os.environ.get("CARGO_ENCODED_RUSTFLAGS")
flags = encoded.split("\x1f") if encoded else []
if encoded is None:
    flags = os.environ.get("RUSTFLAGS", "").split()
assert flags == json.loads(os.environ["EXPECTED_FLAGS_JSON"]), (target, flags)
with (Path(os.environ["GITHUB_WORKSPACE"]) / "calls.jsonl").open("a") as out:
    out.write(json.dumps({"target": target, "flags": flags}) + "\n")
lib = Path(os.environ["CARGO_TARGET_DIR"]) / target / "release/libmy_lib.a"
lib.parent.mkdir(parents=True, exist_ok=True)
lib.write_bytes(b"archive")
PY'
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/build.sh"
}

check_target() {
	export INPUT_TARGETS="$1" EXPECTED_FLAGS_JSON="$2"
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ -s "$INPUT_OUTPUT_DIR/libs/$1/libmy_lib.a" ]
}

@test "should_remove_setup_rust_host_linker_flags_only_for_non_macos_targets" {
	export RUSTFLAGS='-D warnings -C link-arg=-undefined -C link-arg=dynamic_lookup -C force-unwind-tables=yes'
	for target in aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios aarch64-unknown-linux-gnu x86_64-unknown-linux-gnu; do
		check_target "$target" '["-D","warnings","-C","force-unwind-tables=yes"]'
	done
	for target in aarch64-apple-darwin x86_64-apple-darwin; do
		check_target "$target" '["-D","warnings","-C","link-arg=-undefined","-C","link-arg=dynamic_lookup","-C","force-unwind-tables=yes"]'
	done
	[ "$(wc -l <"$XBERG_WORK/calls.jsonl")" -eq 7 ]
	[ "$RUSTFLAGS" = '-D warnings -C link-arg=-undefined -C link-arg=dynamic_lookup -C force-unwind-tables=yes' ]
}

@test "should_remove_compact_and_driver_combined_host_flags_without_removing_security_flags" {
	for host_flags in '-Clink-arg=-undefined -Clink-arg=dynamic_lookup' '-C link-arg=-Wl,-undefined,dynamic_lookup' '-Clink-arg=-Wl,-undefined,dynamic_lookup'; do
		export RUSTFLAGS="-Dwarnings $host_flags -Clink-arg=-Wl,-z,relro"
		check_target aarch64-apple-ios '["-Dwarnings","-Clink-arg=-Wl,-z,relro"]'
	done
	[ "$(wc -l <"$XBERG_WORK/calls.jsonl")" -eq 3 ]
}

@test "should_respect_encoded_precedence_and_preserve_arguments_containing_spaces" {
	export RUSTFLAGS='-D warnings -C link-arg=-undefined -C link-arg=dynamic_lookup --cfg ignored_ambient'
	export CARGO_ENCODED_RUSTFLAGS=$'-D\x1fwarnings\x1f-C\x1flink-arg=-undefined\x1f-C\x1flink-arg=dynamic_lookup\x1f--cfg\x1ffeature="two words"'
	check_target aarch64-apple-ios '["-D","warnings","--cfg","feature=\"two words\""]'
	check_target aarch64-apple-darwin '["-D","warnings","-C","link-arg=-undefined","-C","link-arg=dynamic_lookup","--cfg","feature=\"two words\""]'
	[ "$(wc -l <"$XBERG_WORK/calls.jsonl")" -eq 2 ]
}

@test "should_preserve_empty_encoded_override_and_unrelated_undefined_mode" {
	export RUSTFLAGS='-D warnings -C link-arg=-undefined -C link-arg=dynamic_lookup'
	export CARGO_ENCODED_RUSTFLAGS=''
	check_target aarch64-apple-ios '[]'
	unset CARGO_ENCODED_RUSTFLAGS
	export RUSTFLAGS='-D warnings -C link-arg=-undefined -C link-arg=error'
	check_target aarch64-apple-ios '["-D","warnings","-C","link-arg=-undefined","-C","link-arg=error"]'
	[ "$(wc -l <"$XBERG_WORK/calls.jsonl")" -eq 2 ]
}

@test "should_build_only_static_archives_for_every_apple_target" {
	export RUSTFLAGS='-D warnings'
	for target in aarch64-apple-darwin x86_64-apple-darwin aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios; do
		export EXPECTED_CARGO_COMMAND_JSON='["rustc","--locked","-p","my-crate","--release","--lib","--crate-type","staticlib","--target","'"$target"'"]'
		check_target "$target" '["-D","warnings"]'
	done
	[ "$(wc -l <"$XBERG_WORK/calls.jsonl")" -eq 5 ]
}
