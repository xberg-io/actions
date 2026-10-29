#!/usr/bin/env bats

bats_load_library xberg-bats

setup() {
	xberg_setup
	SCRIPT_DIR="$(cd "$BATS_TEST_DIRNAME/../scripts" && pwd)"
	export RUSTC_WRAPPER=sccache
	export SCCACHE_GHA_ENABLED=true
	export CACHE_STATUS=0
	unset SCCACHE_PATH
	unset CACHE_DIAGNOSTIC
	xberg_stub sccache \
		'printf "sccache %s\n" "$*" >>"$XBERG_TRACE"' \
		'case "$1" in' \
		'  --version) echo "sccache 0.19.0" ;;' \
		'  --show-stats) echo "empty statistics" ;;' \
		'  --start-server)' \
		'    if [ "$CACHE_STATUS" -ne 0 ]; then echo "${CACHE_DIAGNOSTIC:-DO_NOT_PRINT_CACHE_DIAGNOSTICS}" >&2; fi' \
		'    exit "$CACHE_STATUS" ;;' \
		'  *) exit 97 ;;' \
		'esac'
}

@test "healthy cold sccache initializes its cache backend" {
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_trace 'sccache --start-server'
	xberg_assert_github_env ''
}

@test "an available version does not hide a remote cache startup failure" {
	export CACHE_STATUS=2
	run sccache --version
	xberg_assert_status 0
	xberg_assert_output 'sccache 0.19.0'
	run sccache --show-stats
	xberg_assert_status 0
	xberg_assert_output 'empty statistics'
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_github_env $'SCCACHE_GHA_ENABLED=false\nRUSTC_WRAPPER='
	xberg_assert_trace $'sccache --version\nsccache --show-stats\nsccache --start-server'
}

@test "cache backend diagnostics never reach setup logs" {
	export CACHE_STATUS=2
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_trace 'sccache --start-server'
	[[ "$output" != *DO_NOT_PRINT_CACHE_DIAGNOSTICS* ]]
	[[ "$output" == *'continuing with direct compilation'* ]]
}

@test "a missing selected wrapper clears the persisted compiler wrapper" {
	export RUSTC_WRAPPER="$XBERG_STUB_BIN/missing-sccache"
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_trace_empty
	xberg_assert_github_env $'SCCACHE_GHA_ENABLED=false\nRUSTC_WRAPPER='
}

@test "disabled sccache does not start an installed executable" {
	export RUSTC_WRAPPER=''
	export SCCACHE_GHA_ENABLED=false
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_trace_empty
	xberg_assert_github_env ''
}

@test "the selected absolute wrapper is probed even when its directory contains spaces" {
	local cache="$BATS_TEST_TMPDIR/cache directory"
	mkdir -p "$cache"
	mv "$XBERG_STUB_BIN/sccache" "$cache/sccache"
	export RUSTC_WRAPPER="$cache/sccache"
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_trace 'sccache --start-server'
	xberg_assert_github_env ''
}

@test "Windows no-daemon selection survives a healthy runtime probe" {
	export SCCACHE_NO_DAEMON=1
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_trace 'sccache --start-server'
	xberg_assert_github_env ''
	[ "$SCCACHE_NO_DAEMON" = 1 ]
}

@test "a later compiler error still fails after cache startup falls back" {
	export CACHE_STATUS=2
	xberg_stub rustc \
		'[ -z "$RUSTC_WRAPPER" ] && [ "$SCCACHE_GHA_ENABLED" = false ] || exit 90' \
		'printf "rustc %s\n" "$*" >>"$XBERG_TRACE"' \
		'echo "simulated compiler type error" >&2; exit 42'
	run bash -c '
    "$1/validate-sccache.sh"
    while IFS= read -r assignment; do export "$assignment"; done <"$GITHUB_ENV"
    rustc input.rs
  ' _ "$SCRIPT_DIR"
	xberg_assert_status 42
	xberg_assert_trace $'sccache --start-server\nrustc input.rs'
	[[ "$output" == *'simulated compiler type error'* ]]
}

@test "the cache probe does not invoke a compiler" {
	xberg_stub rustc 'echo "compiler must not be invoked by setup" >&2; exit 98'
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_trace 'sccache --start-server'
	[[ "$output" != *'compiler must not be invoked by setup'* ]]
}

@test "configuration and validation persist direct compilation for following action steps" {
	export CACHE_STATUS=2
	xberg_stub rustc 'exit 0'
	run bash -c '
    "$1/configure-flags.sh" true false
    while IFS= read -r assignment; do export "$assignment"; done <"$GITHUB_ENV"
    "$1/validate-sccache.sh"
    while IFS= read -r assignment; do export "$assignment"; done <"$GITHUB_ENV"
    [ -z "$RUSTC_WRAPPER" ] && [ "$SCCACHE_GHA_ENABLED" = false ]
  ' _ "$SCRIPT_DIR"
	xberg_assert_status 0
	xberg_assert_trace $'sccache --version\nsccache --start-server'
}

@test "an already occupied server address falls back without stopping another daemon" {
	export CACHE_STATUS=2
	export CACHE_DIAGNOSTIC='Server startup failed: Address in use'
	run "$SCRIPT_DIR/validate-sccache.sh"
	xberg_assert_status 0
	xberg_assert_trace 'sccache --start-server'
	xberg_assert_github_env $'SCCACHE_GHA_ENABLED=false\nRUSTC_WRAPPER='
}
