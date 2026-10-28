#!/usr/bin/env bats

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$TEST_ROOT/bin"
	mkdir -p "$STUB_BIN" "$TEST_ROOT/runner" "$TEST_ROOT/mise-install"
	MISE_LOG="$TEST_ROOT/mise.log"
	GITHUB_PATH_FILE="$TEST_ROOT/github-path"
	: >"$MISE_LOG"
	: >"$GITHUB_PATH_FILE"
	printf '%s\n' '#!/bin/sh' 'echo "Task version: v3.54.0"' >"$TEST_ROOT/mise-install/task"
	chmod +x "$TEST_ROOT/mise-install/task"
	export TEST_ROOT STUB_BIN MISE_LOG GITHUB_PATH_FILE
	make_mise_stub
	printf '%s\n' '#!/usr/bin/env bash' 'echo "$1" >>"$TEST_ROOT/sleep.log"' >"$STUB_BIN/sleep"
	chmod +x "$STUB_BIN/sleep"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

# Records every call with its working directory and the settings mise would see, and answers like
# mise 2026.10: `latest` prints the version, `which --tool` prints the installed binary.
# MISE_STUB_FAIL makes the named subcommand fail, its first MISE_STUB_FAIL_TIMES calls if that is set.
make_mise_stub() {
	printf '%s\n' '#!/usr/bin/env bash' \
		'printf "%s|%s|%s|%s|%s\n" "$PWD" "${MISE_GITHUB_TOKEN:-}" "${MISE_LOCKED:-}" "${MISE_HTTP_TIMEOUT:-}" "$*" >>"$MISE_LOG"' \
		'if [ "$1" = "${MISE_STUB_FAIL:-}" ]; then' \
		'  count=$(($(cat "$TEST_ROOT/fail-count" 2>/dev/null || echo 0) + 1)); echo "$count" >"$TEST_ROOT/fail-count"' \
		'  if [ -z "${MISE_STUB_FAIL_TIMES:-}" ] || [ "$count" -le "$MISE_STUB_FAIL_TIMES" ]; then exit 1; fi' \
		'fi' \
		'case "$1" in' \
		'  latest) echo "${MISE_STUB_LATEST:-3.54.0}" ;;' \
		'  which) echo "$TEST_ROOT/mise-install/task" ;;' \
		'esac' >"$STUB_BIN/mise"
	chmod +x "$STUB_BIN/mise"
}

run_script() {
	run env PATH="$STUB_BIN:/usr/bin:/bin" GITHUB_TOKEN="test-token" RUNNER_TEMP="$TEST_ROOT/runner" \
		GITHUB_PATH="$GITHUB_PATH_FILE" "$@"
}

@test "unix should_strip_a_leading_v_and_install_the_pinned_version_through_mise" {
	run_script /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" v3.51.1 "$TEST_ROOT/install"

	[ "$status" -eq 0 ]
	[[ "$output" == *"Installing Task v3.51.1"* ]]
	grep -qx ".*|install task@3.51.1" "$MISE_LOG"
	grep -qx ".*|which task --tool task@3.51.1" "$MISE_LOG"
	[ "$(grep -c '|latest task' "$MISE_LOG")" -eq 0 ]
}

@test "unix should_install_a_bare_pinned_version_unchanged" {
	run_script /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.51.1 "$TEST_ROOT/install"

	[ "$status" -eq 0 ]
	grep -qx ".*|install task@3.51.1" "$MISE_LOG"
}

@test "unix should_resolve_latest_through_mise_and_install_that_exact_version" {
	run_script MISE_STUB_LATEST=3.55.0 /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" latest "$TEST_ROOT/install"

	[ "$status" -eq 0 ]
	[[ "$output" == *"Resolved 'latest' to v3.55.0"* ]]
	grep -qx ".*|install task@3.55.0" "$MISE_LOG"
}

@test "unix should_treat_an_empty_version_as_latest" {
	run_script /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" "" "$TEST_ROOT/install"

	[ "$status" -eq 0 ]
	grep -qx ".*|latest task" "$MISE_LOG"
	grep -qx ".*|install task@3.54.0" "$MISE_LOG"
}

@test "unix should_copy_the_binary_into_the_install_dir_and_append_it_to_github_path" {
	local install_dir="$TEST_ROOT/install"

	run_script /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.54.0 "$install_dir"

	[ "$status" -eq 0 ]
	[[ "$output" == *"Task is ready at $install_dir/task"* ]]
	[ "$("$install_dir/task" --version)" = "Task version: v3.54.0" ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$install_dir" ]
}

@test "unix should_default_the_install_dir_to_task_bin_under_runner_temp" {
	run_script /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.54.0 ""

	[ "$status" -eq 0 ]
	[ -x "$TEST_ROOT/runner/task-bin/task" ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$TEST_ROOT/runner/task-bin" ]
}

@test "unix should_run_mise_outside_the_checkout_and_pass_the_github_token" {
	cd "$TEST_ROOT"

	run_script /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.54.0 "$TEST_ROOT/install"

	[ "$status" -eq 0 ]
	[ "$(cut -d'|' -f1,2 "$MISE_LOG" | sort -u)" = "$TEST_ROOT/runner|test-token" ]
}

@test "unix should_retry_mise_install_six_times_with_backoff_then_fail_without_touching_github_path" {
	run_script MISE_STUB_FAIL=install /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.54.0 "$TEST_ROOT/install"

	[ "$status" -ne 0 ]
	[[ "$output" == *"Error: 'mise install task@3.54.0' failed after 6 attempts"* ]]
	[ "$(grep -c '|install task@3.54.0$' "$MISE_LOG")" -eq 6 ]
	[ "$(tr '\n' ' ' <"$TEST_ROOT/sleep.log")" = "5 10 20 40 80 " ]
	[ ! -e "$TEST_ROOT/install/task" ]
	[ ! -s "$GITHUB_PATH_FILE" ]
}

@test "unix should_install_once_a_retried_mise_call_succeeds" {
	run_script MISE_STUB_FAIL=install MISE_STUB_FAIL_TIMES=2 \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.54.0 "$TEST_ROOT/install"

	[ "$status" -eq 0 ]
	[ "$(grep -c '|install task@3.54.0$' "$MISE_LOG")" -eq 3 ]
	[ "$(tr '\n' ' ' <"$TEST_ROOT/sleep.log")" = "5 10 " ]
	[ -x "$TEST_ROOT/install/task" ]
}

@test "unix should_resolve_a_relative_install_dir_against_the_caller_directory" {
	mkdir -p "$TEST_ROOT/work"
	cd "$TEST_ROOT/work"

	run_script /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.54.0 rel-bin

	[ "$status" -eq 0 ]
	[ -x "$TEST_ROOT/work/rel-bin/task" ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$TEST_ROOT/work/rel-bin" ]
}

@test "unix should_install_unlocked_with_a_5m_http_timeout_by_default" {
	run_script MISE_LOCKED=1 /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.54.0 "$TEST_ROOT/install"

	[ "$status" -eq 0 ]
	[ "$(cut -d'|' -f3,4 "$MISE_LOG" | sort -u)" = "false|5m" ]
}

@test "unix should_keep_an_http_timeout_the_caller_set" {
	run_script MISE_HTTP_TIMEOUT=90s /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" 3.54.0 "$TEST_ROOT/install"

	[ "$status" -eq 0 ]
	[ "$(cut -d'|' -f4 "$MISE_LOG" | sort -u)" = "90s" ]
}

@test "unix should_fail_when_mise_cannot_resolve_latest" {
	run_script MISE_STUB_FAIL=latest /bin/bash "$BATS_TEST_DIRNAME/../scripts/unix.sh" latest "$TEST_ROOT/install"

	[ "$status" -ne 0 ]
	[ "$(grep -c '|latest task$' "$MISE_LOG")" -eq 6 ]
	[ "$(grep -c '|install ' "$MISE_LOG")" -eq 0 ]
	[ ! -s "$GITHUB_PATH_FILE" ]
}
