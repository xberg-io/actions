#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
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
		'case "$1" in' \
		'current) printf "%s" "$STUB_CURRENT" ;;' \
		'install) shift; printf "install MISE_LOCKED=%s %s%s\n" "${MISE_LOCKED:-}" "${MISE_ENV:+MISE_ENV=$MISE_ENV }" "$*" >>"$XBERG_TRACE" ;;' \
		'trust) shift; printf "trust %s from %s\n" "$*" "$PWD" >>"$XBERG_TRACE" ;;' \
		'bin-paths) printf "/installs/%s/bin\n" "$2"; [ -z "${STUB_EXTRA_PATH:-}" ] || printf "%s\n" "$STUB_EXTRA_PATH" ;;' \
		'env) shift 2; echo "API_TOKEN=do-not-export"' \
		'  for spec in "$@"; do' \
		'    case "$spec" in java*) echo "JAVA_HOME=\"/jdk/$spec\"" ;; go*) echo "GOROOT=/go/$spec"; echo "GOBIN=/go/$spec/bin" ;; esac' \
		'  done ;;' \
		'*) exit 64 ;;' \
		'esac'
}

run_script() {
	run env -u MISE_ENV -u MISE_LOCKED "$@"
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

# A fallback root holding a lock for helm on every platform mise locks here, and one for uv on none.
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
	export FALLBACK
}

@test "install_tools should_install_the_fallback_roots_locked_version_for_a_tool_the_config_does_not_declare" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root

	run_script MISE_ENV=ci INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" helm= cargo-llvm-cov

	xberg_assert_status 0
	xberg_assert_output_contains "::notice::helm is not declared in the mise config for $REPO, so it installs helm@4.3.1"
	xberg_assert_trace "trust --quiet $FALLBACK from $FALLBACK" \
		"install MISE_LOCKED=1 helm@4.3.1 github:taiki-e/cargo-llvm-cov@0.9.1"
	xberg_assert_github_path $'/installs/github:taiki-e/cargo-llvm-cov@0.9.1/bin\n/installs/helm@4.3.1/bin'
}

@test "install_tools should_install_the_pinned_fallback_version_unlocked_where_its_lock_lacks_the_platform" {
	STUB_CURRENT=$'python 3.13.18\n'
	write_fallback_root

	run_script INSTALL_TOOLS_FALLBACK_ROOT="$FALLBACK" "$SCRIPT" "$REPO" uv

	xberg_assert_status 0
	xberg_assert_output_contains "entry for uv, so 0.13.6 installs unlocked."
	xberg_assert_trace "install MISE_LOCKED=false uv@0.13.6"
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
	[[ "$output" != *"::notice::"* ]]
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

@test "install_tools should_require_at_least_one_tool" {
	run_script "$SCRIPT" "$REPO"

	xberg_assert_status 2
	xberg_assert_trace_empty
}
