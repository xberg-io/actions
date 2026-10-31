#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN"
	export PATH="$BIN:$PATH" GITHUB_WORKSPACE="$ROOT" CARGO_TARGET_DIR="$ROOT/target" GITHUB_OUTPUT="$ROOT/out"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/build.sh"
}

@test "should_describe_optional_target_skips_during_dry_run" {
	xberg_stub sed 'input=$(cat); [ "$input" = my_crate ] && { printf "MyCrate\n"; exit 0; }; /usr/bin/sed "$@" <<<"$input"'
	export INPUT_DRY_RUN=true INPUT_CRATE_NAME=my-crate INPUT_INCLUDE_MACOS_X86_64=false INPUT_INCLUDE_IOS_X86_64=false
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"skip x86_64-apple-darwin (include-macos-x86_64=false)"* ]]
	[[ "$output" == *"ios-sim uses arm64 only"* ]]
	[[ "$output" == *"would assemble dist/swift-artifactbundle/MyCrate.artifactbundle"* ]]
	[[ "$output" == *"cargo rustc --locked -p my-crate --release --lib --crate-type staticlib --target aarch64-apple-darwin"* ]]
	[[ "$output" != *"cargo build"* ]]
}

@test "should_return_error_when_a_target_build_does_not_produce_its_static_library" {
	xberg_stub rustup 'exit 0'
	xberg_stub cargo 'exit 0'
	xberg_stub zig 'echo 0.17.0'
	xberg_stub cargo-zigbuild 'exit 0'
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_OUTPUT_DIR="$ROOT/dist" INPUT_INCLUDE_MACOS_X86_64=false INPUT_INCLUDE_IOS_X86_64=false
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"$ROOT/target/aarch64-apple-darwin/release/libmy_lib.a"* ]]
}

@test "should_assemble_disabled_optional_variants_and_write_metadata" {
	xberg_stub rustup 'exit 0'
	xberg_stub cargo 'if [ "$1" = rustc ] || [ "$1" = zigbuild ]; then target="${@: -1}"; mkdir -p "$CARGO_TARGET_DIR/$target/release"; touch "$CARGO_TARGET_DIR/$target/release/libmy_lib.a"; fi'
	xberg_stub zig 'echo 0.17.0'
	xberg_stub cargo-zigbuild 'target="${@: -1}"; mkdir -p "$CARGO_TARGET_DIR/$target/release"; touch "$CARGO_TARGET_DIR/$target/release/libmy_lib.a"'
	xberg_stub df 'printf "fixture 100 1 99 1%% /tmp\n"'
	xberg_stub zip 'touch "$2"'
	xberg_stub swift 'echo checksum123'
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_ARTIFACT_NAME=Kit INPUT_BINARY_TARGET_NAME=KitTarget INPUT_OUTPUT_DIR="$ROOT/dist" INPUT_INCLUDE_MACOS_X86_64=false INPUT_INCLUDE_IOS_X86_64=false
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"Skipping x86_64-apple-darwin (include-macos-x86_64=false)"* ]]
	[ "$(grep -o 'supportedTriples' "$ROOT/dist/Kit.artifactbundle/info.json" | wc -l)" -eq 5 ]
	expected=$(printf 'bundle-path=%s/dist/Kit.artifactbundle\nbundle-zip=%s/dist/Kit.artifactbundle.zip\nchecksum=checksum123' "$ROOT" "$ROOT")
	[ "$(cat "$GITHUB_OUTPUT")" = "$expected" ]
}

@test "should_build_only_the_requested_targets_and_stage_them_without_assembling" {
	xberg_stub rustup 'exit 0'
	xberg_stub cargo 'if [ "$1" = rustc ] || [ "$1" = zigbuild ]; then target="${@: -1}"; mkdir -p "$CARGO_TARGET_DIR/$target/release"; touch "$CARGO_TARGET_DIR/$target/release/libmy_lib.a"; fi'
	xberg_stub zig 'echo 0.17.0'
	xberg_stub cargo-zigbuild 'target="${@: -1}"; mkdir -p "$CARGO_TARGET_DIR/$target/release"; touch "$CARGO_TARGET_DIR/$target/release/libmy_lib.a"'
	xberg_stub df 'printf "fixture 100 1 99 1%% /tmp\n"'
	xberg_stub rustup "printf '%s\\n' \"\$*\" >>'$ROOT/rustup.log'"
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_ARTIFACT_NAME=Kit INPUT_OUTPUT_DIR="$ROOT/dist" INPUT_TARGETS=aarch64-apple-darwin
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	# `should_build` must be defined before the toolchain section uses it. A missing
	# function returns 127, and `if should_build x` then quietly takes the false branch --
	# so the only way to see the difference is to assert the target was really added. ~keep
	[ "$(cat "$ROOT/rustup.log")" = "target add aarch64-apple-darwin" ]
	[[ "$output" == *"No Linux target requested; skipping Zig installation"* ]]
	# the requested triple is staged
	[ -f "$ROOT/dist/libs/aarch64-apple-darwin/libmy_lib.a" ]
	# and nothing else was built
	[ ! -d "$CARGO_TARGET_DIR/aarch64-unknown-linux-gnu" ]
	# and no bundle was assembled -- assembling here would be wrong, the other
	# triples do not exist in this job
	[ ! -d "$ROOT/dist/Kit.artifactbundle" ]
	[[ "$output" == *"Build-only mode complete for: aarch64-apple-darwin"* ]]
	[ "$(cat "$GITHUB_OUTPUT")" = "libs-dir=$ROOT/dist/libs" ]
}

@test "should_assemble_from_prebuilt_libraries_without_invoking_cargo" {
	xberg_stub rustup 'exit 0'
	# A cargo invocation in assemble mode is the defect this guards: fail loudly.
	xberg_stub cargo 'echo "cargo must not run in assemble mode: $*" >&2; exit 97'
	xberg_stub cargo-zigbuild 'echo "zigbuild must not run in assemble mode" >&2; exit 97'
	xberg_stub zig 'echo 0.17.0'
	xberg_stub df 'printf "fixture 100 1 99 1%% /tmp\n"'
	xberg_stub zip 'touch "$2"'
	xberg_stub swift 'echo checksum456'
	prebuilt="$ROOT/prebuilt"
	for triple in aarch64-apple-darwin aarch64-apple-ios aarch64-apple-ios-sim aarch64-unknown-linux-gnu x86_64-unknown-linux-gnu; do
		mkdir -p "$prebuilt/$triple"
		touch "$prebuilt/$triple/libmy_lib.a"
	done
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_ARTIFACT_NAME=Kit INPUT_BINARY_TARGET_NAME=KitTarget INPUT_OUTPUT_DIR="$ROOT/dist" INPUT_INCLUDE_MACOS_X86_64=false INPUT_INCLUDE_IOS_X86_64=false INPUT_PREBUILT_LIBS_DIR="$prebuilt"
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ -f "$ROOT/dist/Kit.artifactbundle/Kit-macos-arm64/libmy_lib.a" ]
	[ -f "$ROOT/dist/Kit.artifactbundle/Kit-linux-aarch64/libmy_lib.a" ]
	[ "$(grep -o 'supportedTriples' "$ROOT/dist/Kit.artifactbundle/info.json" | wc -l)" -eq 5 ]
	[[ "$output" != *"must not run in assemble mode"* ]]
}

@test "should_reject_a_stale_zig_version_before_any_linux_cargo_build" {
	xberg_stub rustup 'exit 0'
	xberg_stub zig 'echo 0.16.0'
	xberg_stub cargo 'printf "%s\n" "$*" >>"$GITHUB_WORKSPACE/cargo.log"; target="${@: -1}"; mkdir -p "$CARGO_TARGET_DIR/$target/release"; printf archive >"$CARGO_TARGET_DIR/$target/release/libmy_lib.a"'
	xberg_stub cargo-zigbuild 'exit 0'
	xberg_stub df 'printf "fixture 100 1 99 1%% /tmp\n"'
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_ARTIFACT_NAME=Kit INPUT_TARGETS=aarch64-unknown-linux-gnu
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"Expected Zig 0.17.0, found 0.16.0"* ]]
	[ ! -e "$ROOT/cargo.log" ]
}

@test "should_preserve_selected_zig_verified_cargo_driver_and_ambient_rustflags" {
	xberg_stub rustup 'exit 0'
	xberg_stub zig 'echo 0.17.0'
	xberg_stub cargo 'if [[ "$1" == install ]]; then exit 96; fi; printf "%s\n" "$*" "$RUSTFLAGS" >>"$GITHUB_WORKSPACE/cargo.log"; shift; exec cargo-zigbuild "$@"'
	xberg_stub cargo-zigbuild 'printf "%s\n" "$VERIFIED_CARGO_ZIGBUILD_REVISION" >"$GITHUB_WORKSPACE/driver.log"; target="${@: -1}"; mkdir -p "$CARGO_TARGET_DIR/$target/release"; printf archive >"$CARGO_TARGET_DIR/$target/release/libmy_lib.a"'
	xberg_stub df 'printf "fixture 100 1 99 1%% /tmp\n"'
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_ARTIFACT_NAME=Kit INPUT_OUTPUT_DIR="$ROOT/dist" INPUT_TARGETS=aarch64-unknown-linux-gnu INPUT_ZIG_VERSION=0.17.0
	export VERIFIED_CARGO_ZIGBUILD_REVISION=89c352ae6ff0bbafe17788da327764d9ef92240b RUSTFLAGS='-D warnings -C force-unwind-tables=yes'
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$(cat "$ROOT/driver.log")" = "$VERIFIED_CARGO_ZIGBUILD_REVISION" ]
	[ "$(cat "$ROOT/cargo.log")" = $'zigbuild --locked -p my-crate --release --target aarch64-unknown-linux-gnu\n-D warnings -C force-unwind-tables=yes' ]
	[ -s "$ROOT/dist/libs/aarch64-unknown-linux-gnu/libmy_lib.a" ]
}

manifest_step() {
	local step="$BATS_TEST_TMPDIR/substitute-manifest.sh"
	awk '
        /^    - name: Substitute Package.swift placeholders$/ { found = 1; next }
        found && /^      run: \|$/ { body = 1; next }
        body && /^    - name:/ { exit }
        body { sub(/^        /, ""); print }
    ' "$BATS_TEST_DIRNAME/../action.yml" >"$step"
	[ -s "$step" ] || return 1
	grep -q __ALEF_SWIFT_CHECKSUM__ "$step" || return 1
	run env CHECKSUM=checksum123 PACKAGE_MANIFEST_PATH="$ROOT/Package.swift" \
		PACKAGE_VERSION="${1:-}" bash "$step"
}

@test "should_substitute_checksum_placeholder_in_binary_target" {
	printf '%s\n' 'let target = .binaryTarget(checksum: "__ALEF_SWIFT_CHECKSUM__")' >"$ROOT/Package.swift"
	manifest_step
	xberg_assert_status 0
	xberg_assert_file "$ROOT/Package.swift" 'let target = .binaryTarget(checksum: "checksum123")'
	[ ! -e "$ROOT/Package.swift.bak" ]
	xberg_assert_file "$GITHUB_OUTPUT" "package-manifest-path=$ROOT/Package.swift"
}

@test "should_substitute_checksum_and_prerelease_url_version" {
	printf '%s\n' 'checksum: "__ALEF_SWIFT_CHECKSUM__", url: "https://example.test/v__ALEF_SWIFT_VERSION__/bundle.zip"' >"$ROOT/Package.swift"
	manifest_step 0.3.0-rc.52
	xberg_assert_status 0
	xberg_assert_file "$ROOT/Package.swift" 'checksum: "checksum123", url: "https://example.test/v0.3.0-rc.52/bundle.zip"'
	[ ! -e "$ROOT/Package.swift.bak" ]
}

@test "should_reject_missing_manifest_before_substitution" {
	manifest_step
	xberg_assert_status 1
	xberg_assert_output "Error: Package.swift not found at $ROOT/Package.swift"
	[ ! -s "$GITHUB_OUTPUT" ]
}

@test "should_fail_instead_of_installing_an_unpinned_cargo_zigbuild" {
	xberg_shadow_system_path_without cargo-zigbuild
	PATH="$(xberg_isolated_path)"
	export PATH
	xberg_stub rustup 'exit 0'
	xberg_stub zig 'echo 0.17.0'
	xberg_stub cargo 'printf "%s\n" "$*" >>"$GITHUB_WORKSPACE/cargo.log"; exit 0'
	xberg_stub df 'printf "fixture 100 1 99 1%% /tmp\n"'
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_ARTIFACT_NAME=Kit INPUT_TARGETS=aarch64-unknown-linux-gnu
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[[ "$output" == *'cargo-zigbuild is not on PATH: declare "github:rust-cross/cargo-zigbuild" in mise.toml'* ]]
	[ ! -e "$GITHUB_WORKSPACE/cargo.log" ]
}
