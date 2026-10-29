#!/usr/bin/env bats

setup() {
	SCRIPT_DIR="$(cd "$BATS_TEST_DIRNAME/../scripts" && pwd)"
	WORK="$BATS_TEST_TMPDIR/work"
	BIN="$BATS_TEST_TMPDIR/bin"
	mkdir -p "$WORK" "$BIN"
	export PATH="$BIN:$PATH"
	export GITHUB_ENV="$BATS_TEST_TMPDIR/github-env"
	export GITHUB_OUTPUT="$BATS_TEST_TMPDIR/github-output"
	export GITHUB_PATH="$BATS_TEST_TMPDIR/github-path"
	export GITHUB_STEP_SUMMARY="$BATS_TEST_TMPDIR/summary"
	: >"$GITHUB_ENV"
	: >"$GITHUB_OUTPUT"
	: >"$GITHUB_PATH"
	: >"$GITHUB_STEP_SUMMARY"
}

stub() {
	local name="$1"
	shift
	printf '%s\n' '#!/usr/bin/env bash' 'set -eu' "$@" >"$BIN/$name"
	chmod +x "$BIN/$name"
}

@test "should_skip_rust_target_install_when_target_is_already_installed" {
	stub rustup 'if [[ "$*" == "target list" ]]; then echo "aarch64-unknown-linux-gnu (installed)"; else echo "$*" >>"$CALLS"; fi'
	export CALLS="$BATS_TEST_TMPDIR/calls"
	run "$SCRIPT_DIR/add-target.sh" aarch64-unknown-linux-gnu false
	[ "$status" -eq 0 ]
	[ "$output" = $'Checking Rust target: aarch64-unknown-linux-gnu\nTarget aarch64-unknown-linux-gnu is already installed\naarch64-unknown-linux-gnu (installed)' ]
	[ ! -e "$CALLS" ]
}

@test "should_retry_build_without_sccache_when_sccache_failure_is_reported" {
	stub build 'if [[ ! -e "$STATE" ]]; then touch "$STATE"; echo "sccache error"; exit 1; fi; printf "%s/%s\\n" "$RUSTC_WRAPPER" "$SCCACHE_GHA_ENABLED"'
	export STATE="$BATS_TEST_TMPDIR/build-state"
	run "$SCRIPT_DIR/build-with-sccache-fallback.sh" build
	[ "$status" -eq 0 ]
	[ "$output" = $'Building with sccache (fallback on errors)...\nsccache error\nsccache failure detected, retrying without cache...\n/false\nBuild succeeded without sccache (fallback)' ]
}

@test "should_write_sha256_cargo_lock_hash_when_lock_file_exists" {
	printf 'lock\n' >"$WORK/Cargo.lock"
	stub sha256sum 'echo "d8c9f2728aa278ebcd33ccedf3ad309a866870ad5fb93a03526b4b7655c9e911  $1"'
	run bash -c 'cd "$1" && "$2/cargo-lock-hash.sh"' _ "$WORK" "$SCRIPT_DIR"
	[ "$status" -eq 0 ]
	[ "$output" = $'Generated Cargo.lock hash using sha256sum\nUsing Cargo.lock hash: d8c9f2728aa278ebcd33ccedf3ad309a866870ad5fb93a03526b4b7655c9e911' ]
	[ "$(cat "$GITHUB_OUTPUT")" = "hash=d8c9f2728aa278ebcd33ccedf3ad309a866870ad5fb93a03526b4b7655c9e911" ]
}

@test "should_remove_incremental_fingerprints_when_cargo_is_healthy" {
	mkdir -p "$WORK/target/.cargo-ok" "$WORK/target/debug/incremental" "$WORK/target/a/incremental"
	stub cargo '[[ "$1" == "--version" ]] && echo "cargo 1.0"'
	run bash -c 'cd "$1" && "$2/cleanup-fingerprints.sh"' _ "$WORK" "$SCRIPT_DIR"
	[ "$status" -eq 0 ]
	[[ "$output" == *"Fingerprint cleanup completed successfully"* ]]
	[ ! -e "$WORK/target/.cargo-ok" ]
	[ ! -e "$WORK/target/debug/incremental" ]
	[ ! -e "$WORK/target/a/incremental" ]
}

@test "should_disable_sccache_and_write_supported_rust_flags_when_not_requested" {
	stub rustc 'if [[ "$1" == "-V" ]]; then echo "rustc 1.80"; fi'
	run "$SCRIPT_DIR/configure-flags.sh" false false
	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_ENV")" = $'SCCACHE_GHA_ENABLED=false\nRUSTC_WRAPPER=\nRUSTFLAGS=-D warnings -A unpredictable-function-pointer-comparisons -A mismatched-lifetime-syntaxes -A fn_ptr_eq --cfg has_fn_ptr_eq_lint' ]
}

@test "should_add_sccache_directory_to_github_path_when_executable_exists" {
	local cache="$BATS_TEST_TMPDIR/sccache"
	mkdir -p "$cache"
	touch "$cache/sccache"
	export SCCACHE_PATH="$cache"
	run "$SCRIPT_DIR/ensure-sccache-path.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "Added sccache to PATH" ]
	[ "$(cat "$GITHUB_PATH")" = "$cache" ]
}

@test "should_report_exact_sccache_hit_rate_when_wrapper_is_enabled" {
	stub sccache 'if [[ "$1" == "--show-stats" ]]; then printf "Cache hits: 3\\nCache misses: 1\\n"; fi'
	export RUSTC_WRAPPER=sccache
	run "$SCRIPT_DIR/report-sccache-stats.sh"
	[ "$status" -eq 0 ]
	[ "$output" = $'=== sccache Statistics ===\nCache hits: 3\nCache misses: 1\nHit Rate: 75%\nGood hit rate' ]
	[ "$(cat "$GITHUB_STEP_SUMMARY")" = "### sccache: 75% hit rate (3 hits, 1 misses)" ]
}

@test "should_exclude_target_from_cache_paths_on_macos" {
	export RUNNER_OS=macOS
	run "$SCRIPT_DIR/resolve-cache-paths.sh"
	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_ENV")" = $'RUST_CACHE_PATHS<<__XBERG_CACHE_PATHS__\n~/.cargo/registry/index\n~/.cargo/registry/cache\n~/.cargo/git/db\n__XBERG_CACHE_PATHS__' ]
}

@test "should_continue_when_sccache_is_not_available" {
	run env -u SCCACHE_PATH RUSTC_WRAPPER=sccache \
		PATH="$BIN:/usr/bin:/bin" "$SCRIPT_DIR/validate-sccache.sh"
	[ "$status" -eq 0 ]
	local expected=$'Checking sccache runtime...\n'
	expected+='Warning: sccache runtime is unavailable, continuing with direct compilation'
	[ "$output" = "$expected" ]
	[ "$(cat "$GITHUB_ENV")" = $'SCCACHE_GHA_ENABLED=false\nRUSTC_WRAPPER=' ]
}

@test "should_print_rust_installation_versions_and_matching_target" {
	stub rustc 'echo "rustc 1.80.0"'
	stub cargo 'echo "cargo 1.80.0"'
	stub rustup 'if [[ "$1" == "--version" ]]; then echo "rustup 1.27.0"; else echo "aarch64-unknown-linux-gnu (installed)"; fi'
	run "$SCRIPT_DIR/verify-install.sh" aarch64
	[ "$status" -eq 0 ]
	[ "$output" = $'Rust toolchain information:\nrustc 1.80.0\nrustup 1.27.0\ncargo 1.80.0\nAvailable targets:\naarch64-unknown-linux-gnu (installed)' ]
}
