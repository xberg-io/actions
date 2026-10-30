#!/usr/bin/env bats

# ~keep Built once per file: the mirror is read-only and identical for every test here, and
# rebuilding a few thousand symlinks per test is pure wall-clock.
setup_file() {
	bats_load_library xberg-bats
	export SYS_BIN
	xberg_shadow_system_path_without bats
	SYS_BIN="$XBERG_SYS_BIN"
	# ~keep The whole point of the mirror is that this command is missing from it, and a silent
	# leak would let run.sh find the host's real Bats -- which, since these tests hand it a
	# directory of .bats files, would recursively run a second Bats suite instead of the shim
	# whose recorded arguments are the assertion. Assert the precondition instead of assuming it.
	[ ! -e "$SYS_BIN/bats" ] || {
		echo "mirror leaked bats" >&2
		return 1
	}
}

setup() {
	bats_load_library xberg-bats
	xberg_setup
	# ~keep run.sh reports and compares paths after `pwd -P`, and on macOS mktemp hands back
	# /var/folders/... which is a symlink to /private/var/folders/.... Resolving here keeps the
	# expected strings equal to what the script prints on both runners.
	TEST_ROOT="$(cd "$(mktemp -d)" && pwd -P)"
	STUB_BIN="$XBERG_STUB_BIN"
	WORKSPACE="$TEST_ROOT/workspace"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/run.sh"
	# ~keep CI runs this suite through ./run-bats itself, so the outer action exports its own
	# INPUT_PATH and INPUT_ARGS into this process -- and `run env FOO=bar ...` ADDS to the
	# inherited environment rather than replacing it. Without this, the default-path tests read
	# the outer action's `path: .` and assert against the wrong directory. Locally there is no
	# outer action and they pass, so the leak is invisible off CI. Clear the whole prefix so
	# each test starts from nothing and sets only what it means to exercise.
	for _leaked_input in $(env | sed -n 's/^\(INPUT_[A-Za-z0-9_]*\)=.*/\1/p'); do
		unset "$_leaked_input"
	done
	mkdir -p "$STUB_BIN" "$WORKSPACE/tests"
	printf '%s\n' '@test "fixture" { true; }' >"$WORKSPACE/tests/sample.bats"
	export TEST_ROOT STUB_BIN WORKSPACE SCRIPT
}

teardown() {
	rm -rf "$TEST_ROOT"
}

# Prints one argument per line and exits with BATS_STUB_STATUS, so a test asserts the exact
# argument vector run.sh assembled and can also drive the failure path. ~keep
make_bats_stub() {
	xberg_stub bats '#!/usr/bin/env bash' \
		'printf "%s\n" "$@"' \
		'exit "${BATS_STUB_STATUS:-0}"'
}

@test "run should_return_error_when_bats_is_not_on_path" {
	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::bats is not on PATH. Run install-bats before run-bats." ]
}

@test "run should_invoke_bats_on_the_resolved_default_tests_directory" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_ARGS="--recursive" /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = $'--recursive\n'"$WORKSPACE/tests" ]
}

@test "run should_pass_every_newline_delimited_argument_before_the_test_path" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_PATH="tests" \
		INPUT_ARGS=$'--recursive\n--print-output-on-failure\n--jobs 2' /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = $'--recursive\n--print-output-on-failure\n--jobs 2\n'"$WORKSPACE/tests" ]
}

@test "run should_return_error_when_args_contain_an_empty_line" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_ARGS=$'--recursive\n\n--timing' \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::args must be newline-delimited arguments without empty lines." ]
}

@test "run should_return_error_when_args_end_with_a_blank_line" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_ARGS=$'--recursive\n' /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::args must be newline-delimited arguments without empty lines." ]
}

@test "run should_propagate_the_bats_exit_status_when_tests_fail" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_ARGS="--recursive" BATS_STUB_STATUS=3 \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 3 ]
	[ "$output" = $'--recursive\n'"$WORKSPACE/tests" ]
}

@test "run should_invoke_bats_on_a_single_test_file_when_path_names_a_file" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_PATH="tests/sample.bats" \
		INPUT_ARGS="--timing" /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = $'--timing\n'"$WORKSPACE/tests/sample.bats" ]
}

@test "run should_accept_an_absolute_test_path_inside_the_working_directory" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_PATH="$WORKSPACE/tests" \
		INPUT_ARGS="--timing" /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = $'--timing\n'"$WORKSPACE/tests" ]
}

@test "run should_resolve_a_relative_working_directory_against_the_current_directory" {
	make_bats_stub
	mkdir -p "$WORKSPACE/package/tests"

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="package" INPUT_ARGS="--timing" \
		/bin/bash -c 'cd "$1" && exec /bin/bash "$2"' bash "$WORKSPACE" "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = $'--timing\n'"$WORKSPACE/package/tests" ]
}

@test "run should_default_the_working_directory_to_the_current_directory" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" INPUT_ARGS="--timing" \
		/bin/bash -c 'cd "$1" && exec /bin/bash "$2"' bash "$WORKSPACE" "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = $'--timing\n'"$WORKSPACE/tests" ]
}

@test "run should_return_error_when_the_github_workspace_does_not_exist" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$TEST_ROOT/absent" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_ARGS="--timing" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "${lines[${#lines[@]} - 1]}" = "::error::GitHub workspace does not exist: ${TEST_ROOT}/absent." ]
}

@test "run should_return_error_when_the_working_directory_does_not_exist" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE/absent" INPUT_ARGS="--timing" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "${lines[${#lines[@]} - 1]}" = "::error::Working directory does not exist: ${WORKSPACE}/absent." ]
}

@test "run should_return_error_when_the_working_directory_is_outside_the_workspace" {
	make_bats_stub
	mkdir -p "$TEST_ROOT/outside/tests"

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$TEST_ROOT/outside" INPUT_ARGS="--timing" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Working directory must be inside GITHUB_WORKSPACE." ]
}

@test "run should_return_error_when_the_test_path_does_not_exist" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_PATH="absent" INPUT_ARGS="--timing" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Bats test path does not exist: absent." ]
}

@test "run should_return_error_when_the_test_path_is_a_symbolic_link" {
	make_bats_stub
	ln -s "$WORKSPACE/tests" "$WORKSPACE/linked-tests"

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_PATH="linked-tests" INPUT_ARGS="--timing" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Bats test path must not be a symbolic link." ]
}

@test "run should_return_error_when_the_test_path_escapes_the_workspace" {
	make_bats_stub
	mkdir -p "$TEST_ROOT/outside/tests"

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" INPUT_PATH="$TEST_ROOT/outside/tests" \
		INPUT_ARGS="--timing" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Bats test path must be inside GITHUB_WORKSPACE." ]
}

@test "run should_return_error_when_the_test_path_escapes_the_working_directory" {
	make_bats_stub
	mkdir -p "$WORKSPACE/package" "$WORKSPACE/sibling/tests"

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE/package" INPUT_PATH="../sibling/tests" \
		INPUT_ARGS="--timing" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Bats test path must be inside the working directory." ]
}

# ~keep Deliberately run under /bin/bash, which is 3.2 on a macOS runner: expanding an empty
# array under `set -u` aborts before 4.4, and `args` defaults to "" so the empty case is the
# action's own default. test-run-bats.yml is ubuntu-latest only, so nothing else covers it.
@test "run should_invoke_bats_with_only_the_test_path_when_no_args_are_given" {
	make_bats_stub

	run env PATH="$STUB_BIN:$SYS_BIN" GITHUB_WORKSPACE="$WORKSPACE" \
		INPUT_WORKING_DIRECTORY="$WORKSPACE" /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = "$WORKSPACE/tests" ]
}
