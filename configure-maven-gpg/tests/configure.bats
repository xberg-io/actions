#!/usr/bin/env bats

setup_file() {
	bats_load_library xberg-bats
	xberg_shadow_system_path_without gpg2
}

setup() {
	bats_load_library xberg-bats
	xberg_setup_isolated
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN" "$ROOT/home"
	export PATH="$BIN:$XBERG_SYS_BIN" HOME="$ROOT/home" GITHUB_PATH="$ROOT/path" GITHUB_ENV="$ROOT/env"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/configure.sh"
}

@test "should_report_default_gpg_when_gpg2_is_not_available" {
	export INPUT_PREFER_GPG2=true INPUT_PATCH_POM=false
	# ~keep PATH is narrowed to the stub directory alone. The setup PATH keeps /usr/bin, and a
	# runner that ships gpg2 there -- ubuntu-latest does, macOS does not -- satisfies the script's
	# `command -v gpg2` probe and takes the wrapper branch instead of the one under test, which is
	# why this passed locally and failed in CI. With patch-pom off the script reaches only `echo`,
	# a builtin, so it needs nothing else on PATH.
	run env PATH="$BIN" /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$output" = "gpg2 not found; using default gpg" ]
	[ ! -e "$ROOT/path" ]
}

@test "should_create_gpg2_wrapper_and_patch_legacy_pom_arguments" {
	xberg_stub gpg2 'exit 0'
	xberg_stub sed 'file="${@: -1}"; printf "%s\n" "<arg>--pinentry-mode=loopback</arg>" >"$file"'
	printf '<arg>--pinentry-mode</arg><arg>loopback</arg>\n' >"$ROOT/pom.xml"
	export INPUT_POM_FILE="$ROOT/pom.xml"
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$output" = $'gpg2 binary preference configured\nPatched legacy GPG pinentry argument format in '"$ROOT"'/pom.xml' ]
	[ "$(cat "$ROOT/home/.local/bin/gpg")" = $'#!/usr/bin/env bash\nexec gpg2 "$@"' ]
	[ "$(cat "$ROOT/pom.xml")" = '<arg>--pinentry-mode=loopback</arg>' ]
}

@test "should_warn_when_requested_pom_does_not_exist" {
	export INPUT_PREFER_GPG2=false INPUT_POM_FILE="$ROOT/missing.xml"
	run bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$output" = "::warning::pom.xml not found: $ROOT/missing.xml (skipping patch)" ]
}
