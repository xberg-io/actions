#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT_DIR="$(cd "$BATS_TEST_DIRNAME/../scripts" && pwd)"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN"
	export PATH="$BIN:$PATH"
	export GITHUB_PATH="$BATS_TEST_TMPDIR/github-path"
	: >"$GITHUB_PATH"
}

@test "should_skip_clang_format_install_when_requested_version_is_present" {
	xberg_stub clang-format 'set -eu' 'echo "clang-format version 18.1.8"'
	export CLANG_FORMAT_VERSION=18.1.8
	run "$SCRIPT_DIR/clang-format.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "clang-format 18.1.8 already installed." ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_return_error_when_clang_format_version_is_empty" {
	run env -u CLANG_FORMAT_VERSION "$SCRIPT_DIR/clang-format.sh"
	[ "$status" -eq 1 ]
	[ "$output" = "$SCRIPT_DIR/clang-format.sh: line 8: CLANG_FORMAT_VERSION: clang-format version required" ]
}

@test "should_install_only_requested_linux_tools" {
	xberg_stub sudo 'set -eu' '"$@"'
	xberg_stub apt-get 'set -eu' 'printf "%s\n" "$*" >>"$CALLS"'
	export CALLS="$BATS_TEST_TMPDIR/apt-calls"
	export INSTALL_CLANG_FORMAT=false INSTALL_CPPCHECK=false INSTALL_SHELLCHECK=true INSTALL_SHFMT=false
	run "$SCRIPT_DIR/linux.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "" ]
	[ "$(cat "$CALLS")" = $'update -qq\ninstall -y --no-install-recommends shellcheck' ]
}

@test "should_report_brew_cppcheck_version_when_requested_on_macos" {
	xberg_stub brew 'set -eu' 'if [[ "$1" == "install" ]]; then printf "%s\n" "$*" >>"$BREW_CALLS"; fi'
	xberg_stub cppcheck 'set -eu' 'echo "Cppcheck 2.20.0"'
	export BREW_CALLS="$BATS_TEST_TMPDIR/brew-calls"
	export INSTALL_CLANG_FORMAT=false INSTALL_CPPCHECK=true INSTALL_SHELLCHECK=false INSTALL_SHFMT=false CPPCHECK_VERSION=2.20.0
	run "$SCRIPT_DIR/macos.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "Cppcheck 2.20.0" ]
	[ "$(cat "$BREW_CALLS")" = "install cppcheck" ]
}

@test "should_skip_shfmt_install_when_requested_version_is_present" {
	xberg_stub shfmt 'set -eu' 'echo "3.14.1"'
	export SHFMT_VERSION=3.14.1
	run "$SCRIPT_DIR/shfmt.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "shfmt 3.14.1 already installed." ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_accept_a_v_prefixed_shfmt_version_report" {
	xberg_stub shfmt 'set -eu' 'echo "v3.14.1"'
	export SHFMT_VERSION=3.14.1
	run "$SCRIPT_DIR/shfmt.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "shfmt 3.14.1 already installed." ]
}

@test "should_return_error_when_shfmt_version_is_empty" {
	run env -u SHFMT_VERSION "$SCRIPT_DIR/shfmt.sh"
	[ "$status" -eq 1 ]
	[ "$output" = "$SCRIPT_DIR/shfmt.sh: line 10: SHFMT_VERSION: shfmt version required" ]
}

@test "should_install_shfmt_from_linux_script_when_requested" {
	xberg_stub shfmt 'set -eu' 'echo "3.14.1"'
	export INSTALL_CLANG_FORMAT=false INSTALL_CPPCHECK=false INSTALL_SHELLCHECK=false
	export INSTALL_SHFMT=true SHFMT_VERSION=3.14.1
	run "$SCRIPT_DIR/linux.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "shfmt 3.14.1 already installed." ]
}

@test "should_not_install_shfmt_from_linux_script_when_disabled" {
	export INSTALL_CLANG_FORMAT=false INSTALL_CPPCHECK=false INSTALL_SHELLCHECK=false
	export INSTALL_SHFMT=false
	run "$SCRIPT_DIR/linux.sh"
	[ "$status" -eq 0 ]
	[ "$output" = "" ]
}
