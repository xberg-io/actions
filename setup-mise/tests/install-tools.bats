#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	REAL_MISE="$(command -v mise || true)"
	export REAL_MISE
	xberg_setup
	REPO="$BATS_TEST_TMPDIR/repo"
	mkdir -p "$REPO"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/install-tools.sh"
	export REPO SCRIPT
	# The configured tools `mise current` reports, one "<id> <version>" per line.
	export STUB_CURRENT=""
	# A stand-in mise: traces install calls with the MISE_LOCKED they ran under, and answers bin-paths and env
	# from the spec. Its env output always carries a secret-looking [env] value the script must not export.
	xberg_stub mise \
		'if [ -n "${FALLBACK:-}" ] && [ "$PWD" = "$FALLBACK" ]; then' \
		'  env | grep -E "^MISE_(ENV|[A-Z0-9_]+_VERSION)=" >>"$BATS_TEST_TMPDIR/fallback-env.log" || true' \
		'fi' \
		'case "$1" in' \
		'current) if [ -n "${FALLBACK:-}" ] && [ "$PWD" = "$FALLBACK" ]; then printf "%s" "$STUB_FALLBACK_CURRENT"' \
		'  else printf "%s" "$STUB_CURRENT"; fi ;;' \
		'install) shift; printf "%s from %s\n" "${MISE_TRUSTED_CONFIG_PATHS:-}" "$PWD" >>"$BATS_TEST_TMPDIR/trust.log"' \
		'  printf "install MISE_LOCKED=%s %s%s\n" "${MISE_LOCKED:-}" "${MISE_ENV:+MISE_ENV=$MISE_ENV }" "$*" >>"$XBERG_TRACE" ;;' \
		'bin-paths) printf "/installs/%s/bin\n" "$2"; [ -z "${STUB_EXTRA_PATH:-}" ] || printf "%s\n" "$STUB_EXTRA_PATH" ;;' \
		'env) shift 2; echo "API_TOKEN=do-not-export"' \
		'  for spec in "$@"; do' \
		'    case "$spec" in java*) echo "JAVA_HOME=\"/jdk/$spec\"" ;; go*) echo "GOROOT=/go/$spec"; echo "GOBIN=/go/$spec/bin" ;; esac' \
		'  done ;;' \
		'*) exit 64 ;;' \
		'esac'
}

run_script() {
	run env -u MISE_ENV -u MISE_LOCKED -u GITHUB_EVENT_NAME -u MISE_TRUSTED_CONFIG_PATHS "$@"
}

@test "install_tools should_install_a_configured_tool_from_the_config_when_no_version_is_passed" {
	STUB_CURRENT=$'python 3.13.18\nuv 0.13.6\n'

	run_script MISE_LOCKED=1 "$SCRIPT" "$REPO" python=

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 python"
	xberg_assert_github_path "/installs/python/bin"
	[[ "$output" != *"::notice::"* ]]
}

@test "install_tools should_fail_for_a_tool_the_config_does_not_declare_and_no_version_selects" {
	STUB_CURRENT=$'python 3.13.18\n'

	run_script "$SCRIPT" "$REPO" pnpm

	xberg_assert_status 1
	xberg_assert_output_contains "::error::pnpm is not declared in the mise config for $REPO"
	xberg_assert_trace_empty
	xberg_assert_github_path ""
}

# A fallback root whose config selects helm, cargo-llvm-cov and uv, locked on every platform for the first two and
# on none for uv.
write_fallback_root() {
	FALLBACK="$BATS_TEST_TMPDIR/actions"
	mkdir -p "$FALLBACK"
	{
		printf '%s\n' '[[tools.helm]]' 'version = "4.3.1"' 'backend = "aqua:helm/helm"' ''
		for platform in linux-x64 linux-arm64 macos-x64 macos-arm64 windows-x64; do
			printf '%s\n' "[tools.helm.\"platforms.$platform\"]" 'url = "https://example.invalid/helm"' ''
		done
		printf '%s\n' '[[tools."github:taiki-e/cargo-llvm-cov"]]' 'version = "0.9.1"' ''
		for platform in linux-x64 linux-arm64 macos-x64 macos-arm64 windows-x64; do
			printf '%s\n' "[tools.\"github:taiki-e/cargo-llvm-cov\".\"platforms.$platform\"]" 'url = "https://example.invalid/c"' ''
		done
		printf '%s\n' '[[tools.uv]]' 'version = "0.13.6"'
	} >"$FALLBACK/mise.lock"
	STUB_FALLBACK_CURRENT=$'helm 4.3.1\ngithub:taiki-e/cargo-llvm-cov 0.9.1\nuv 0.13.6\n'
	export FALLBACK STUB_FALLBACK_CURRENT
}

@test "install_tools should_install_the_fallback_roots_locked_version_for_a_tool_the_config_does_not_declare" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root

	run_script MISE_ENV=ci MISE_HELM_VERSION=3.0.0 INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" \
		helm= cargo-llvm-cov

	xberg_assert_status 0
	xberg_assert_output_contains "::notice::helm is not declared in the mise config for $REPO, so it installs helm@4.3.1"
	xberg_assert_trace "install MISE_LOCKED=1 helm@4.3.1 github:taiki-e/cargo-llvm-cov@0.9.1"
	xberg_assert_file "$BATS_TEST_TMPDIR/trust.log" "$FALLBACK from $FALLBACK"
	xberg_assert_file "$BATS_TEST_TMPDIR/fallback-env.log" ""
	xberg_assert_github_path $'/installs/github:taiki-e/cargo-llvm-cov@0.9.1/bin\n/installs/helm@4.3.1/bin'
}

@test "install_tools should_find_a_platform_entry_early_in_a_fallback_lock_larger_than_a_pipe_buffer" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root
	for index in $(seq 1 4000); do
		printf '%s\n' "[[tools.\"github:example/padding-$index\"]]" 'version = "1.0.0"' ''
	done >>"$FALLBACK/mise.lock"

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" helm

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 helm@4.3.1"
}

@test "install_tools should_fail_where_the_fallback_lock_lacks_the_runners_platform" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" uv

	xberg_assert_status 1
	xberg_assert_output_contains "::error::$FALLBACK/mise.lock has no "
	xberg_assert_output_contains " entry for uv@0.13.6"
	xberg_assert_trace_empty
}

@test "install_tools should_fail_when_the_fallback_lock_lacks_the_version_its_config_selects" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root
	STUB_FALLBACK_CURRENT=$'helm 4.4.0\n'

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" helm

	xberg_assert_status 1
	xberg_assert_output_contains "::error::$FALLBACK/mise.lock does not lock helm@4.4.0"
	xberg_assert_trace_empty
}

@test "install_tools should_fail_when_the_fallback_config_selects_more_than_one_version" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root
	STUB_FALLBACK_CURRENT=$'helm 4.3.1 3.19.0\n'

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" helm

	xberg_assert_status 1
	xberg_assert_output_contains "not one version"
	xberg_assert_trace_empty
}

@test "install_tools should_fail_when_a_short_name_matches_two_fallback_tools" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root
	STUB_FALLBACK_CURRENT=$'aqua:helm/helm 4.3.1\nasdf:helm 4.3.1\n'

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" helm

	xberg_assert_status 1
	xberg_assert_output_contains "::error::helm matches more than one tool in $FALLBACK/mise.toml (aqua:helm/helm asdf:helm)"
	xberg_assert_trace_empty
}

@test "install_tools should_prefer_the_configured_version_over_the_fallback_root" {
	STUB_CURRENT=$'aqua:helm/helm 3.19.0\n'
	write_fallback_root

	run_script MISE_LOCKED=1 INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" helm

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 aqua:helm/helm"
	[[ "$output" != *"::notice::"* ]]
}

@test "install_tools should_prefer_a_passed_version_over_the_fallback_root" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" helm=v3.16.0

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=false helm@3.16.0"
	[[ "$output" != *"is not declared"* ]]
}

@test "install_tools should_fail_for_a_tool_neither_the_config_nor_the_fallback_root_declares" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" pnpm

	xberg_assert_status 1
	xberg_assert_output_contains "::error::pnpm is not declared in the mise config for $REPO"
	xberg_assert_trace_empty
}

@test "install_tools should_fail_when_the_fallback_root_has_no_lock" {
	STUB_CURRENT=$'python 3.13.18\n'
	mkdir -p "$BATS_TEST_TMPDIR/nolock"

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$BATS_TEST_TMPDIR/nolock" "$SCRIPT" "$REPO" helm

	xberg_assert_status 1
	xberg_assert_output_contains "has no mise.lock"
	xberg_assert_trace_empty
}

@test "install_tools should_select_the_newest_locked_version_under_a_requested_prefix" {
	STUB_CURRENT=$'python 3.13.18 3.11.18\n'
	printf '%s\n' '[[tools.python]]' 'version = "3.13.18"' '' '[tools.python."platforms.linux-x64"]' \
		'url = "https://example.invalid/3.13.18.tar.gz"' '' '[[tools.python]]' 'version = "3.13.9"' >"$REPO/mise.lock"

	run_script MISE_LOCKED=1 "$SCRIPT" "$REPO" python=3.13

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 python@3.13.18"
	xberg_assert_github_path "/installs/python@3.13.18/bin"
	[[ "$output" != *"::notice::"* ]]
}

@test "install_tools should_install_a_version_no_lock_covers_unlocked_with_a_notice" {
	STUB_CURRENT=$'node 26.12.1\n'
	printf '%s\n' '[[tools.node]]' 'version = "26.12.1"' >"$REPO/mise.lock"

	run_script MISE_LOCKED=1 "$SCRIPT" "$REPO" node=24

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=false node@24"
	xberg_assert_output_contains "::notice::node@24 is not in the active mise lock, so it installs unlocked."
	xberg_assert_github_path "/installs/node@24/bin"
}

@test "install_tools should_not_match_a_locked_version_that_only_shares_leading_digits" {
	STUB_CURRENT=$'node 26.12.1\n'
	printf '%s\n' '[[tools.node]]' 'version = "240.1.0"' >"$REPO/mise.lock"

	run_script MISE_LOCKED=1 "$SCRIPT" "$REPO" node=24

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=false node@24"
}

@test "install_tools should_read_a_lock_checked_out_with_crlf_line_endings" {
	STUB_CURRENT=$'node 26.12.1\n'
	printf '%s\r\n' '[[tools.node]]' 'version = "26.12.1"' >"$REPO/mise.lock"

	run_script MISE_LOCKED=1 "$SCRIPT" "$REPO" node=26

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 node@26.12.1"
	[[ "$output" != *"::notice::"* ]]
}

@test "install_tools should_not_let_a_version_input_start_a_workflow_command" {
	STUB_CURRENT=$'python 3.13.18\n'

	run_script "$SCRIPT" "$REPO" $'python=3.13\n::warning::injected'

	xberg_assert_status 1
	[[ "$output" != *$'\n::warning::injected'* ]]
	xberg_assert_trace_empty
}

@test "install_tools should_consult_the_lock_of_every_active_profile" {
	STUB_CURRENT=$'python 3.13.18 3.11.18\n'
	printf '%s\n' '[[tools.python]]' 'version = "3.13.18"' >"$REPO/mise.lock"
	printf '%s\n' '[[tools.python]]' 'version = "3.11.18"' >"$REPO/mise.ci.lock"

	run_script MISE_LOCKED=1 MISE_ENV=ci "$SCRIPT" "$REPO" python=3.11

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 MISE_ENV=ci python@3.11.18"
}

@test "install_tools should_resolve_a_short_name_to_the_backend_id_the_config_declares" {
	STUB_CURRENT=$'github:rustwasm/wasm-pack 0.15.0\nnode 26.12.1\n'
	printf '%s\n' '[[tools."github:rustwasm/wasm-pack"]]' 'version = "0.15.0"' >"$REPO/mise.lock"

	run_script MISE_LOCKED=1 "$SCRIPT" "$REPO" wasm-pack wasm-pack=0.15

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 github:rustwasm/wasm-pack github:rustwasm/wasm-pack@0.15.0"
}

@test "install_tools should_install_an_undeclared_tool_by_the_requested_id_when_a_version_is_passed" {
	STUB_CURRENT=$'node 26.12.1\n'

	run_script "$SCRIPT" "$REPO" github:rustwasm/wasm-pack=v0.13.1

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=false github:rustwasm/wasm-pack@0.13.1"
	xberg_assert_output_contains "::notice::github:rustwasm/wasm-pack@0.13.1 is not in the active mise lock"
}

@test "install_tools should_fail_when_a_short_name_matches_two_configured_tools" {
	STUB_CURRENT=$'aqua:pnpm/pnpm 12.15.0\nnpm:pnpm 12.11.2\n'

	run_script "$SCRIPT" "$REPO" pnpm

	xberg_assert_status 1
	xberg_assert_output_contains "::error::pnpm matches more than one configured tool"
	xberg_assert_trace_empty
}

@test "install_tools should_drop_a_wildcard_suffix_and_a_leading_v_from_the_version" {
	STUB_CURRENT=$'python 3.13.18\n'

	run_script "$SCRIPT" "$REPO" python=3.x zig=v0.17.0

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=false python@3 zig@0.17.0"
}

@test "install_tools should_reject_a_version_with_characters_outside_a_version" {
	STUB_CURRENT=$'python 3.13.18\n'

	run_script "$SCRIPT" "$REPO" 'python=3.13;touch /tmp/x'

	xberg_assert_status 1
	xberg_assert_output_contains "is not a version mise can install"
	xberg_assert_trace_empty
}

@test "install_tools should_keep_mise_path_order_by_writing_github_path_in_reverse" {
	STUB_CURRENT=$'python 3.13.18 3.11.18\nuv 0.13.6\n'
	export STUB_EXTRA_PATH=/installs/python-3.11/bin

	run_script "$SCRIPT" "$REPO" python uv

	xberg_assert_status 0
	xberg_assert_github_path "$(printf '%s\n' /installs/python-3.11/bin /installs/uv/bin /installs/python-3.11/bin \
		/installs/python/bin)"
}

@test "install_tools should_export_only_the_requested_tools_variables_and_never_the_config_env" {
	STUB_CURRENT=$'java temurin-25.0.5+8.0.LTS\nmaven 3.10.0\ngo 1.27.3\n'

	run_script "$SCRIPT" "$REPO" java=temurin-21 maven

	xberg_assert_status 0
	xberg_assert_github_env "JAVA_HOME=/jdk/java@temurin-21"
	[[ "$output" != *"do-not-export"* ]]
}

@test "install_tools should_not_export_gobin_or_goroot_for_go" {
	STUB_CURRENT=$'go 1.27.3\n'

	run_script "$SCRIPT" "$REPO" go=1.27

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=false go@1.27"
	[[ ! -s "$GITHUB_ENV" ]]
}

@test "install_tools should_require_at_least_one_tool" {
	run_script "$SCRIPT" "$REPO"

	xberg_assert_status 2
	xberg_assert_trace_empty
}

# ~keep The stub's `mise current` is an assumption about mise; this one asks the real binary, in isolated data and
# ~keep cache directories so the declared tool is certainly not installed, and stubs only install and bin-paths.
@test "install_tools should_resolve_a_declared_locked_uninstalled_tool_through_real_mise_current" {
	[[ -n "$REAL_MISE" ]] || skip "mise is not on PATH"
	printf '%s\n' '[tools]' 'shfmt = "3.10.0"' >"$REPO/mise.toml"
	printf '%s\n' '[[tools.shfmt]]' 'version = "3.10.0"' 'backend = "aqua:mvdan/sh"' >"$REPO/mise.lock"
	xberg_stub mise \
		'case "$1" in' \
		'current) exec "$REAL_MISE" "$@" ;;' \
		'install) shift; printf "install MISE_LOCKED=%s %s\n" "${MISE_LOCKED:-}" "$*" >>"$XBERG_TRACE" ;;' \
		'bin-paths) printf "/installs/%s/bin\n" "$2" ;;' \
		'*) exit 64 ;;' \
		'esac'

	run_script MISE_LOCKED=1 MISE_OFFLINE=1 MISE_DATA_DIR="$BATS_TEST_TMPDIR/data" \
		MISE_CACHE_DIR="$BATS_TEST_TMPDIR/cache" MISE_STATE_DIR="$BATS_TEST_TMPDIR/state" \
		MISE_GLOBAL_CONFIG_FILE="$BATS_TEST_TMPDIR/global.toml" "$SCRIPT" "$REPO" shfmt shfmt=3.10

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 shfmt shfmt@3.10.0"
	[[ "$output" != *"is not declared"* ]]
	[[ "$output" != *"::notice::"* ]]
	[[ ! -d "$BATS_TEST_TMPDIR/data/installs/shfmt" ]]
}

@test "install_tools should_read_an_untrusted_caller_config_through_real_mise" {
	[[ -n "$REAL_MISE" ]] || skip "mise is not on PATH"
	printf '%s\n' '[env]' 'CALLER_VALUE = "set"' '[tools]' 'shfmt = "3.10.0"' >"$REPO/mise.toml"
	xberg_stub mise \
		'case "$1" in' \
		'current) exec "$REAL_MISE" "$@" ;;' \
		'install) shift; printf "install %s\n" "$*" >>"$XBERG_TRACE" ;;' \
		'bin-paths) printf "/installs/%s/bin\n" "$2" ;;' \
		'*) exit 64 ;;' \
		'esac'
	isolated=(MISE_OFFLINE=1 MISE_DATA_DIR="$BATS_TEST_TMPDIR/data" MISE_CACHE_DIR="$BATS_TEST_TMPDIR/cache"
		MISE_STATE_DIR="$BATS_TEST_TMPDIR/state" MISE_GLOBAL_CONFIG_FILE="$BATS_TEST_TMPDIR/global.toml")
	run env -u MISE_TRUSTED_CONFIG_PATHS "${isolated[@]}" "$REAL_MISE" current --cd "$REPO"
	[[ "$status" -ne 0 ]]

	run_script "${isolated[@]}" "$SCRIPT" "$REPO" shfmt

	xberg_assert_status 0
	xberg_assert_trace "install shfmt"
	run env -u MISE_TRUSTED_CONFIG_PATHS "${isolated[@]}" "$REAL_MISE" current --cd "$REPO"
	[[ "$status" -ne 0 ]]
}

@test "install_tools should_not_trust_the_caller_config_on_a_pull_request_target_run" {
	[[ -n "$REAL_MISE" ]] || skip "mise is not on PATH"
	printf '%s\n' '[env]' 'CALLER_VALUE = "set"' '[tools]' 'shfmt = "3.10.0"' >"$REPO/mise.toml"
	xberg_stub mise \
		'case "$1" in' \
		'current) exec "$REAL_MISE" "$@" ;;' \
		'*) printf "%s\n" "$*" >>"$XBERG_TRACE" ;;' \
		'esac'

	run_script GITHUB_EVENT_NAME=pull_request_target MISE_OFFLINE=1 MISE_DATA_DIR="$BATS_TEST_TMPDIR/data" \
		MISE_STATE_DIR="$BATS_TEST_TMPDIR/state" MISE_GLOBAL_CONFIG_FILE="$BATS_TEST_TMPDIR/global.toml" \
		"$SCRIPT" "$REPO" shfmt

	xberg_assert_status 1
	xberg_assert_output_contains "::error::The mise config in $REPO is not trusted, and a pull_request_target run"
	xberg_assert_output_contains "Set MISE_TRUSTED_CONFIG_PATHS"
	xberg_assert_trace_empty
}

@test "install_tools should_install_the_fallback_for_a_caller_directory_without_a_mise_config_through_real_mise" {
	[[ -n "$REAL_MISE" ]] || skip "mise is not on PATH"
	FALLBACK="$BATS_TEST_TMPDIR/actions"
	mkdir -p "$FALLBACK"
	printf '%s\n' '[tools]' 'shfmt = "3.10.0"' >"$FALLBACK/mise.toml"
	{
		printf '%s\n' '[[tools.shfmt]]' 'version = "3.10.0"' 'backend = "aqua:mvdan/sh"' ''
		for platform in linux-x64 linux-arm64 macos-x64 macos-arm64 windows-x64; do
			printf '%s\n' "[tools.shfmt.\"platforms.$platform\"]" 'url = "https://example.invalid/shfmt"' ''
		done
	} >"$FALLBACK/mise.lock"
	xberg_stub mise \
		'case "$1" in' \
		'current) exec "$REAL_MISE" "$@" ;;' \
		'install) shift; printf "install MISE_LOCKED=%s %s from %s\n" "${MISE_LOCKED:-}" "$*" "$PWD" >>"$XBERG_TRACE" ;;' \
		'bin-paths) printf "/installs/%s/bin\n" "$2" ;;' \
		'*) exit 64 ;;' \
		'esac'

	run_script MISE_OFFLINE=1 MISE_DATA_DIR="$BATS_TEST_TMPDIR/data" MISE_CACHE_DIR="$BATS_TEST_TMPDIR/cache" \
		MISE_STATE_DIR="$BATS_TEST_TMPDIR/state" MISE_GLOBAL_CONFIG_FILE="$BATS_TEST_TMPDIR/global.toml" \
		INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" shfmt

	xberg_assert_status 0
	xberg_assert_trace "install MISE_LOCKED=1 shfmt@3.10.0 from $FALLBACK"
	xberg_assert_github_path "/installs/shfmt@3.10.0/bin"
}
