#!/usr/bin/env bats

setup_file() {
	bats_load_library xberg-bats
	xberg_shadow_system_path_without cargo alef
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

@test "resolve should_use_pinned_version_without_calling_network_for_latest" {
	xberg_stub curl '#!/usr/bin/env bash' 'printf "%s\n" "curl must not run" >&2; exit 99'
	xberg_stub uname '#!/usr/bin/env bash' \
		'if [ "$1" = "-s" ]; then printf "%s\n" Linux; else printf "%s\n" x86_64; fi'
	local work_dir="$TEST_ROOT/work"
	local output_file="$TEST_ROOT/github-output"
	mkdir -p "$work_dir"
	printf '%s\n' 'version = "0.79.5"' >"$work_dir/alef.toml"

	run bash -c 'cd "$1" && env PATH="$2:$XBERG_SYS_BIN" GITHUB_OUTPUT="$3" /bin/bash "$4" latest' \
		_ "$work_dir" "$STUB_BIN" "$output_file" "$BATS_TEST_DIRNAME/../scripts/resolve.sh"

	[ "$status" -eq 0 ]
	[ "$(cat "$output_file")" = $'resolved_version=0.79.5\ninstall_ref=0.79.5\ntarget=x86_64-unknown-linux-gnu' ]
	[ "$output" = $'Using pinned version from alef.toml: 0.79.5\nResolved alef version: 0.79.5 (install ref: 0.79.5, target: x86_64-unknown-linux-gnu)' ]
}

@test "resolve should_use_twelve_character_main_commit_cache_key" {
	xberg_stub curl '#!/usr/bin/env bash' 'printf "%s\n" "{\"sha\":\"0123456789abcdef\"}"'
	xberg_stub uname '#!/usr/bin/env bash' \
		'if [ "$1" = "-s" ]; then printf "%s\n" Linux; else printf "%s\n" aarch64; fi'
	local output_file="$TEST_ROOT/github-output"

	run env PATH="$STUB_BIN:$XBERG_SYS_BIN" GITHUB_TOKEN="test-token" GITHUB_OUTPUT="$output_file" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/resolve.sh" main

	[ "$status" -eq 0 ]
	[ "$(cat "$output_file")" = $'resolved_version=main-0123456789ab\ninstall_ref=main\ntarget=aarch64-unknown-linux-gnu' ]
	[ "$output" = "Resolved alef version: main-0123456789ab (install ref: main, target: aarch64-unknown-linux-gnu)" ]
}

@test "resolve should_return_error_for_unsupported_architecture" {
	xberg_stub uname '#!/usr/bin/env bash' \
		'if [ "$1" = "-s" ]; then printf "%s\n" Linux; else printf "%s\n" riscv64; fi'
	local output_file="$TEST_ROOT/github-output"
	: >"$output_file"

	run env PATH="$STUB_BIN:$XBERG_SYS_BIN" GITHUB_OUTPUT="$output_file" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/resolve.sh" 1.2.3

	[ "$status" -eq 1 ]
	[ "$output" = "Error: unsupported Linux architecture: riscv64" ]
	[ "$(cat "$output_file")" = "" ]
}

@test "unix should_install_release_archive_for_supported_linux_target" {
	local archive_root="$TEST_ROOT/archive/alef-x86_64-unknown-linux-gnu"
	mkdir -p "$archive_root"
	printf '%s\n' '#!/usr/bin/env bash' 'printf "%s\n" "alef 1.2.3"' >"$archive_root/alef"
	chmod +x "$archive_root/alef"
	tar -czf "$TEST_ROOT/alef.tar.gz" -C "$TEST_ROOT/archive" alef-x86_64-unknown-linux-gnu
	xberg_stub uname '#!/usr/bin/env bash' \
		'if [ "$1" = "-s" ]; then printf "%s\n" Linux; else printf "%s\n" x86_64; fi'
	xberg_stub curl '#!/usr/bin/env bash' '/bin/cat "$CURL_ARCHIVE"'
	local home_dir="$TEST_ROOT/home"

	run env PATH="$STUB_BIN:$XBERG_SYS_BIN" GITHUB_TOKEN="test-token" HOME="$home_dir" CURL_ARCHIVE="$TEST_ROOT/alef.tar.gz" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 1.2.3

	[ "$status" -eq 0 ]
	[[ "$output" == *"Alef v1.2.3 installed successfully"* ]]
	[[ "$output" == *"Alef is ready at $home_dir/.local/bin/alef"* ]]
	[ "$("$home_dir/.local/bin/alef")" = "alef 1.2.3" ]
}

@test "unix should_return_error_when_release_and_pinned_source_tag_are_unavailable" {
	xberg_stub uname '#!/usr/bin/env bash' \
		'if [ "$1" = "-s" ]; then printf "%s\n" Linux; else printf "%s\n" x86_64; fi'
	xberg_stub curl '#!/usr/bin/env bash' 'exit 1'
	xberg_stub cargo '#!/usr/bin/env bash' 'exit 1'
	xberg_stub sleep '#!/usr/bin/env bash' 'exit 0'

	run env PATH="$STUB_BIN:$XBERG_SYS_BIN" GITHUB_TOKEN="test-token" HOME="$TEST_ROOT/home" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 1.2.3

	[ "$status" -eq 1 ]
	[[ "$output" == *"Failed to download alef release binary after 3 attempts"* ]]
	[[ "$output" == *"::error::alef v1.2.3 could not be installed: no release archive and no buildable tag v1.2.3 in xberg-io/alef."* ]]
}
