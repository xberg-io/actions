#!/usr/bin/env bats

setup_file() {
	bats_load_library xberg-bats
	xberg_shadow_system_path_without mise task
}

setup() {
	bats_load_library xberg-bats
	xberg_setup_isolated
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	REPO="$TEST_ROOT/repo"
	CALLS="$TEST_ROOT/calls.log"
	mkdir -p "$STUB_BIN" "$REPO"
	: >"$CALLS"
	export TEST_ROOT STUB_BIN REPO CALLS
}

teardown() {
	rm -rf "$TEST_ROOT"
}

# mise 2026.10: `tasks info <name>` exits 0 only for a defined task. MISE_STUB_TASKS lists the defined
# names; MISE_STUB_RUN_STATUS is what `mise run` exits with.
make_mise_stub() {
	printf '%s\n' '#!/usr/bin/env bash' \
		'echo "mise $*" >>"$CALLS"' \
		'case "$1 $2" in' \
		'  "tasks info") for t in ${MISE_STUB_TASKS:-}; do [ "$t" = "$3" ] && exit 0; done; exit 1 ;;' \
		'  "run "*) exit "${MISE_STUB_RUN_STATUS:-0}" ;;' \
		'esac' >"$STUB_BIN/mise"
	chmod +x "$STUB_BIN/mise"
}

run_runner() {
	run env PATH="$STUB_BIN:$XBERG_SYS_BIN" "$@"
}

runner() {
	echo "$BATS_TEST_DIRNAME/../scripts/docs-runner.sh"
}

@test "docs-runner should_run_the_mise_task_when_mise_defines_it" {
	make_mise_stub
	cd "$REPO"

	run_runner MISE_STUB_TASKS="docs:build" /bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 0 ]
	[[ "$output" == *"Running mise task docs:build"* ]]
	[[ "$output" != *"fallback-ran"* ]]
	grep -qx "mise run docs:build" "$CALLS"
}

@test "docs-runner should_run_the_fallback_when_mise_does_not_define_the_task" {
	make_mise_stub
	cd "$REPO"

	run_runner MISE_STUB_TASKS="docs:build:strict" /bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 0 ]
	[[ "$output" == *"No docs:build task in mise; running: echo fallback-ran"* ]]
	[[ "$output" == *$'\n'"fallback-ran"* ]]
	[ "$(grep -c '^mise run' "$CALLS")" -eq 0 ]
}

@test "docs-runner should_never_run_go_task_even_with_a_taskfile_and_task_on_path" {
	printf '%s\n' '#!/usr/bin/env bash' 'echo "task $*" >>"$CALLS"' >"$STUB_BIN/task"
	chmod +x "$STUB_BIN/task"
	touch "$REPO/Taskfile.yml"
	cd "$REPO"

	run_runner /bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 0 ]
	[[ "$output" == *$'\n'"fallback-ran"* ]]
	[ ! -s "$CALLS" ]
}

@test "docs-runner should_run_the_fallback_without_mise" {
	cd "$REPO"

	run_runner /bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 0 ]
	[[ "$output" == *"fallback-ran"* ]]
}

@test "docs-runner should_fail_when_the_fallback_fails" {
	cd "$REPO"

	run_runner /bin/bash "$(runner)" run docs:build /bin/sh -c 'exit 3'

	[ "$status" -eq 3 ]
}

@test "docs-runner should_fail_when_the_mise_task_fails" {
	make_mise_stub
	cd "$REPO"

	run_runner MISE_STUB_TASKS="docs:build" MISE_STUB_RUN_STATUS=4 /bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 4 ]
	[[ "$output" != *"fallback-ran"* ]]
}

@test "docs-runner should_reject_a_run_without_a_fallback_command" {
	cd "$REPO"

	run_runner /bin/bash "$(runner)" run docs:build

	[ "$status" -eq 2 ]
	[[ "$output" == *"usage: docs-runner.sh run"* ]]
}

@test "docs-runner should_reject_an_unknown_mode" {
	run_runner /bin/bash "$(runner)" build

	[ "$status" -eq 2 ]
}
