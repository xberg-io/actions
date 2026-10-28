#!/usr/bin/env bats

setup() {
	TEST_ROOT="$(mktemp -d)"
	REPO="$TEST_ROOT/repo"
	mkdir -p "$REPO"
	GITHUB_ENV="$TEST_ROOT/github-env"
	GITHUB_OUTPUT="$TEST_ROOT/github-output"
	: >"$GITHUB_ENV"
	: >"$GITHUB_OUTPUT"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/prepare-env.sh"
	export TEST_ROOT REPO GITHUB_ENV GITHUB_OUTPUT SCRIPT
}

teardown() {
	rm -rf "$TEST_ROOT"
}

# Run with a clean mise environment, so the host's own MISE_* variables cannot decide the result.
run_script() {
	run env -u MISE_ENV -u MISE_DATA_DIR -u MISE_RUBY_COMPILE -u MISE_HTTP_TIMEOUT -u MISE_LOCKED "$@"
}

@test "prepare should_export_the_runner_defaults_when_nothing_is_preset" {
	run_script "$SCRIPT" "$REPO" "" auto

	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_ENV")" = "$(printf '%s\n' MISE_RUBY_COMPILE=false MISE_HTTP_TIMEOUT=5m)" ]
	[ "$(cat "$GITHUB_OUTPUT")" = "cache=true" ]
}

@test "prepare should_keep_ruby_and_timeout_settings_the_caller_already_set" {
	run_script MISE_RUBY_COMPILE=true MISE_HTTP_TIMEOUT=60s "$SCRIPT" "$REPO" "" auto

	[ "$status" -eq 0 ]
	[ ! -s "$GITHUB_ENV" ]
}

@test "prepare should_export_mise_env_from_the_input" {
	run_script "$SCRIPT" "$REPO" ci auto

	[ "$status" -eq 0 ]
	grep -qx "MISE_ENV=ci" "$GITHUB_ENV"
}

@test "prepare should_export_mise_locked_when_mise_lock_exists" {
	: >"$REPO/mise.lock"

	run_script "$SCRIPT" "$REPO" "" auto

	[ "$status" -eq 0 ]
	[[ "$output" == *"Found $REPO/mise.lock; installing with MISE_LOCKED=1"* ]]
	grep -qx "MISE_LOCKED=1" "$GITHUB_ENV"
}

@test "prepare should_export_mise_locked_for_the_active_profile_lock_from_the_input" {
	: >"$REPO/mise.ci.lock"

	run_script "$SCRIPT" "$REPO" ci auto

	[ "$status" -eq 0 ]
	grep -qx "MISE_LOCKED=1" "$GITHUB_ENV"
}

@test "prepare should_export_mise_locked_for_a_profile_lock_named_by_a_preset_mise_env" {
	: >"$REPO/mise.release.lock"

	run_script MISE_ENV=ci,release "$SCRIPT" "$REPO" "" auto

	[ "$status" -eq 0 ]
	grep -qx "MISE_LOCKED=1" "$GITHUB_ENV"
	[ "$(grep -c '^MISE_ENV=' "$GITHUB_ENV")" -eq 0 ]
}

@test "prepare should_not_export_mise_locked_without_a_lock_for_the_active_profiles" {
	: >"$REPO/mise.other.lock"

	run_script "$SCRIPT" "$REPO" ci auto

	[ "$status" -eq 0 ]
	[ "$(grep -c '^MISE_LOCKED=' "$GITHUB_ENV")" -eq 0 ]
}

@test "prepare should_turn_auto_cache_off_when_mise_data_dir_is_preset" {
	run_script MISE_DATA_DIR=/opt/mise "$SCRIPT" "$REPO" "" auto

	[ "$status" -eq 0 ]
	[[ "$output" == *"MISE_DATA_DIR is preset (/opt/mise); not caching it"* ]]
	[ "$(cat "$GITHUB_OUTPUT")" = "cache=false" ]
}

@test "prepare should_honour_a_forced_cache_value_even_with_a_preset_mise_data_dir" {
	run_script MISE_DATA_DIR=/opt/mise "$SCRIPT" "$REPO" "" true

	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_OUTPUT")" = "cache=true" ]
}

@test "prepare should_honour_a_forced_cache_off" {
	run_script "$SCRIPT" "$REPO" "" false

	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_OUTPUT")" = "cache=false" ]
}

@test "prepare should_reject_an_unknown_cache_value" {
	run_script "$SCRIPT" "$REPO" "" yes

	[ "$status" -eq 1 ]
	[[ "$output" == *"cache must be auto, true or false, got 'yes'"* ]]
	[ ! -s "$GITHUB_OUTPUT" ]
}
