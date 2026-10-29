#!/usr/bin/env bats

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$TEST_ROOT/bin"
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

# go-task 3.54: `--list-all --json` prints {"tasks": [{"name": ...}]}. TASK_STUB_TASKS lists the names.
make_task_stub() {
	printf '%s\n' '#!/usr/bin/env bash' \
		'echo "task $*" >>"$CALLS"' \
		'if [ "$1" = "--list-all" ]; then' \
		'  printf "{\n  \"tasks\": [\n"' \
		'  for t in ${TASK_STUB_TASKS:-}; do printf "    {\n      \"name\": \"%s\",\n      \"task\": \"%s\"\n    },\n" "$t" "$t"; done' \
		'  printf "  ]\n}\n"' \
		'fi' >"$STUB_BIN/task"
	chmod +x "$STUB_BIN/task"
}

run_runner() {
	run env PATH="$STUB_BIN:/usr/bin:/bin" "$@"
}

runner() {
	echo "$BATS_TEST_DIRNAME/../scripts/docs-runner.sh"
}

@test "docs-runner should_run_the_mise_task_when_mise_defines_it_even_with_a_taskfile" {
	make_mise_stub
	make_task_stub
	touch "$REPO/Taskfile.yml"
	cd "$REPO"

	run_runner MISE_STUB_TASKS="docs:build" TASK_STUB_TASKS="docs:build" \
		/bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 0 ]
	[[ "$output" == *"Running mise task docs:build"* ]]
	[[ "$output" != *"fallback-ran"* ]]
	grep -qx "mise run docs:build" "$CALLS"
	[ "$(grep -c '^task ' "$CALLS")" -eq 0 ]
}

@test "docs-runner should_run_the_go_task_task_when_only_the_taskfile_defines_it" {
	make_mise_stub
	make_task_stub
	touch "$REPO/Taskfile.yml"
	cd "$REPO"

	run_runner MISE_STUB_TASKS="docs:lint:links" TASK_STUB_TASKS="docs:build docs:build:strict" \
		/bin/bash "$(runner)" run docs:build:strict echo fallback-ran

	[ "$status" -eq 0 ]
	[[ "$output" == *"Running go-task task docs:build:strict"* ]]
	grep -qx "task docs:build:strict" "$CALLS"
	[ "$(grep -c '^mise run' "$CALLS")" -eq 0 ]
}

@test "docs-runner should_find_a_taskfile_in_a_parent_of_the_working_directory" {
	make_task_stub
	touch "$REPO/Taskfile.yaml"
	mkdir -p "$REPO/docs"
	cd "$REPO/docs"

	run_runner TASK_STUB_TASKS="docs:build" /bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 0 ]
	grep -qx "task docs:build" "$CALLS"
}

@test "docs-runner should_run_the_fallback_when_the_taskfile_does_not_list_the_task" {
	make_mise_stub
	make_task_stub
	touch "$REPO/Taskfile.yml"
	cd "$REPO"

	# docs:build must not match docs:build:strict as a prefix.
	run_runner TASK_STUB_TASKS="docs:build:strict" /bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 0 ]
	[[ "$output" == *"No docs:build task in mise or a Taskfile; running: echo fallback-ran"* ]]
	[[ "$output" == *$'\n'"fallback-ran"* ]]
	[ "$(grep -c '^task docs:build' "$CALLS")" -eq 0 ]
}

@test "docs-runner should_ignore_go_task_on_path_when_there_is_no_taskfile" {
	make_task_stub
	cd "$REPO"

	run_runner TASK_STUB_TASKS="docs:build" /bin/bash "$(runner)" run docs:build echo fallback-ran

	[ "$status" -eq 0 ]
	[[ "$output" == *"fallback-ran"* ]]
	[ ! -s "$CALLS" ]
}

@test "docs-runner should_run_the_fallback_without_mise_or_go_task" {
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

@test "docs-runner should_need_go_task_for_a_taskfile_task_mise_does_not_define" {
	make_mise_stub
	touch "$REPO/Taskfile.yml"
	cd "$REPO"

	run_runner MISE_STUB_TASKS="docs:lint:links" /bin/bash "$(runner)" needs-task docs:lint:links docs:lint:prose

	[ "$status" -eq 0 ]
	[ "$output" = "true" ]
}

@test "docs-runner should_need_go_task_for_a_taskfile_in_a_parent_directory" {
	touch "$REPO/taskfile.yml"
	mkdir -p "$REPO/docs"
	cd "$REPO/docs"

	run_runner /bin/bash "$(runner)" needs-task docs:build

	[ "$status" -eq 0 ]
	[ "$output" = "true" ]
}

@test "docs-runner should_not_need_go_task_when_mise_defines_every_task" {
	make_mise_stub
	touch "$REPO/Taskfile.yml"
	cd "$REPO"

	run_runner MISE_STUB_TASKS="docs:lint:links docs:lint:prose" \
		/bin/bash "$(runner)" needs-task docs:lint:links docs:lint:prose

	[ "$status" -eq 0 ]
	[ "$output" = "false" ]
}

@test "docs-runner should_not_need_go_task_without_a_taskfile" {
	cd "$REPO"

	run_runner /bin/bash "$(runner)" needs-task docs:build

	[ "$status" -eq 0 ]
	[ "$output" = "false" ]
}

@test "docs-runner should_not_need_go_task_when_it_is_already_on_path" {
	make_task_stub
	touch "$REPO/Taskfile.yml"
	cd "$REPO"

	run_runner /bin/bash "$(runner)" needs-task docs:build

	[ "$status" -eq 0 ]
	[ "$output" = "false" ]
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
