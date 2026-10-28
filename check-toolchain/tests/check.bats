#!/usr/bin/env bats

setup() {
	TEST_ROOT="$(mktemp -d)"
	REPO="$TEST_ROOT/repo"
	mkdir -p "$REPO"
	printf '%s\n' '[tools]' 'task = "3.54.0"' >"$REPO/mise.toml"
	make_toolchains_remote
	export TEST_ROOT REPO
}

teardown() {
	rm -rf "$TEST_ROOT"
}

# A local stand-in for xberg-io/toolchains whose checker records its arguments and exits with the
# code the test asks for, so the script's wiring is asserted without the network.
make_toolchains_remote() {
	local remote="$TEST_ROOT/toolchains"
	mkdir -p "$remote/scripts"
	printf '%s\n' '[tools]' 'task = "3.54.0"' >"$remote/baseline.toml"
	printf '%s\n' 'import os, sys' \
		'print("checker", *sys.argv[1:])' \
		'sys.exit(int(os.environ.get("CHECKER_EXIT", "0")))' >"$remote/scripts/toolchains.py"
	git -C "$remote" init --quiet
	git -C "$remote" add .
	git -C "$remote" -c user.name=t -c user.email=t@example.com -c commit.gpgSign=false commit --quiet -m baseline
	git -C "$remote" -c tag.gpgSign=false -c tag.forceSignAnnotated=false tag v1.0.0
	export TOOLCHAINS_REPOSITORY_URL="$remote"
}

@test "check should_fail_with_exit_2_when_toolchains_toml_is_missing" {
	run "$BATS_TEST_DIRNAME/../scripts/check.sh" "$REPO"

	[ "$status" -eq 2 ]
	[[ "$output" == *"$REPO/toolchains.toml not found"* ]]
}

@test "check should_fail_when_toolchains_toml_has_no_baseline_key" {
	printf '%s\n' '[overrides.node]' 'version = "22.20.0"' >"$REPO/toolchains.toml"

	run "$BATS_TEST_DIRNAME/../scripts/check.sh" "$REPO"

	[ "$status" -eq 1 ]
	[[ "$output" == *"missing a string \`baseline\` key"* ]]
}

@test "check should_run_the_checker_from_the_named_baseline_tag_against_the_repository" {
	printf '%s\n' 'baseline = "v1.0.0"' >"$REPO/toolchains.toml"

	run env RUNNER_TEMP="$TEST_ROOT" "$BATS_TEST_DIRNAME/../scripts/check.sh" "$REPO"

	[ "$status" -eq 0 ]
	[[ "$output" == *"Checking $REPO against xberg-io/toolchains v1.0.0"* ]]
	[[ "$output" =~ checker\ check\ --baseline\ $TEST_ROOT/toolchains\.[^/]+/baseline\.toml\ --repo\ $REPO ]]
}

@test "check should_propagate_the_checker_exit_code_when_it_reports_drift" {
	printf '%s\n' 'baseline = "v1.0.0"' >"$REPO/toolchains.toml"

	run env CHECKER_EXIT=1 RUNNER_TEMP="$TEST_ROOT" "$BATS_TEST_DIRNAME/../scripts/check.sh" "$REPO"

	[ "$status" -eq 1 ]
	[[ "$output" == *"checker check"* ]]
}

@test "check should_fail_when_the_baseline_tag_does_not_exist" {
	printf '%s\n' 'baseline = "v9.9.9"' >"$REPO/toolchains.toml"

	run env RUNNER_TEMP="$TEST_ROOT" "$BATS_TEST_DIRNAME/../scripts/check.sh" "$REPO"

	[ "$status" -ne 0 ]
	[[ "$output" != *"checker"* ]]
}

@test "check should_remove_the_temporary_checkout_when_it_finishes" {
	printf '%s\n' 'baseline = "v1.0.0"' >"$REPO/toolchains.toml"
	mkdir -p "$TEST_ROOT/runner"

	run env RUNNER_TEMP="$TEST_ROOT/runner" "$BATS_TEST_DIRNAME/../scripts/check.sh" "$REPO"

	[ "$status" -eq 0 ]
	[ -z "$(ls -A "$TEST_ROOT/runner")" ]
}
