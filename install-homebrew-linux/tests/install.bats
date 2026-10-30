#!/usr/bin/env bats

setup_file() {
	bats_load_library xberg-bats
	xberg_shadow_system_path_without brew bwrap
}

setup() {
	bats_load_library xberg-bats
	xberg_setup_isolated
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	mkdir -p "$STUB_BIN"
	export TEST_ROOT STUB_BIN
}

teardown() {
	rm -rf "$TEST_ROOT"
}

@test "install should_exit_without_installing_when_brew_is_already_on_path" {
	xberg_stub brew '#!/usr/bin/env bash' \
		'if [ "$1" = "--version" ]; then printf "%s\n" "Homebrew 4.5.0"; fi'
	xberg_stub sudo '#!/usr/bin/env bash' 'exit 99'
	xberg_stub curl '#!/usr/bin/env bash' 'exit 99'

	run env PATH="$STUB_BIN:$XBERG_SYS_BIN" GITHUB_PATH="$TEST_ROOT/github-path" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/install.sh"

	[ "$status" -eq 0 ]
	[ "$output" = "brew already on PATH: $STUB_BIN/brew" ]
	[ ! -e "$TEST_ROOT/github-path" ]
}

@test "install should_return_installer_failure_after_safely_installing_bubblewrap" {
	xberg_stub sudo '#!/usr/bin/env bash' \
		'printf "sudo %s\n" "$*" >>"$COMMAND_LOG"' \
		'exit 0'
	xberg_stub curl '#!/usr/bin/env bash' 'printf "%s\n" "exit 7"'
	local command_log="$TEST_ROOT/commands"

	run env PATH="$STUB_BIN:/bin" COMMAND_LOG="$command_log" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/install.sh"

	[ "$status" -eq 7 ]
	[ "$output" = $'Installing bubblewrap for Homebrew Linux sandbox...\nInstalling Homebrew...' ]
	[ "$(cat "$command_log")" = $'sudo apt-get update -y\nsudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends bubblewrap' ]
}
