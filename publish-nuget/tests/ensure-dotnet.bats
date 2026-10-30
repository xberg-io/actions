#!/usr/bin/env bats

setup_file() {
	bats_load_library xberg-bats
	export SYS_BIN
	xberg_shadow_system_path_without dotnet
	SYS_BIN="$XBERG_SYS_BIN"
	# ~keep The whole point of the mirror is that this command is missing from it, and a
	# silent leak would put every test in this file back on the host's copy without
	# failing. Assert the precondition instead of assuming it.
	[ ! -e "$SYS_BIN/dotnet" ] || {
		echo "mirror leaked dotnet" >&2
		return 1
	}
}

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ACTION_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	mkdir -p "$STUB_BIN" "$TEST_ROOT/home"
	ORIGINAL_PATH="$PATH"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

@test "should_skip_installation_when_dotnet_is_already_on_path" {
	printf '#!/usr/bin/env bash\nprintf 9.0.100\n' >"$STUB_BIN/dotnet"
	printf '#!/usr/bin/env bash\nexit 99\n' >"$STUB_BIN/curl"
	chmod +x "$STUB_BIN/dotnet" "$STUB_BIN/curl"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" HOME="$TEST_ROOT/home" \
		bash "$ACTION_DIR/scripts/ensure-dotnet.sh"

	[ "$status" -eq 0 ]
	[ "$output" = "dotnet already available: 9.0.100" ]
}

@test "should_install_lts_sdk_and_publish_dotnet_path_when_missing" {
	github_path="$TEST_ROOT/github-path"
	dotnet_template="$TEST_ROOT/dotnet-template"
	printf '#!/usr/bin/env bash\nprintf 8.0.999\n' >"$dotnet_template"
	chmod +x "$dotnet_template"
	printf '%s\n' '#!/usr/bin/env bash' \
		'for argument in "$@"; do output="$argument"; done' \
		'printf "%s\n" "#!/usr/bin/env bash" "mkdir -p \"\$HOME/.dotnet\"" "cp \"\$DOTNET_TEMPLATE\" \"\$HOME/.dotnet/dotnet\"" "chmod +x \"\$HOME/.dotnet/dotnet\"" >"$output"' >"$STUB_BIN/curl"
	chmod +x "$STUB_BIN/curl"

	run env PATH="$STUB_BIN:$SYS_BIN" HOME="$TEST_ROOT/home" GITHUB_PATH="$github_path" \
		DOTNET_TEMPLATE="$dotnet_template" \
		bash "$ACTION_DIR/scripts/ensure-dotnet.sh"

	[ "$status" -eq 0 ]
	[ "$output" = $'Installing .NET SDK...\nInstalled dotnet: 8.0.999' ]
	[ "$(cat "$github_path")" = "$TEST_ROOT/home/.dotnet" ]
	[ ! -e /tmp/dotnet-install.sh ]
}
