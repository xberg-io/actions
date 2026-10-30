#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	TEST_ROOT="$(mktemp -d)"
	ORIGIN="$TEST_ROOT/origin"
	CLONE="$TEST_ROOT/clone"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/restore-config.sh"
	export TEST_ROOT ORIGIN CLONE SCRIPT
	make_origin
	git clone --quiet "$ORIGIN" "$CLONE"
	git -C "$CLONE" -c advice.detachedHead=false checkout --quiet "$OLD_SHA"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

commit() {
	git -C "$ORIGIN" add -A
	git -C "$ORIGIN" -c user.name=t -c user.email=t@example.com -c commit.gpgSign=false commit --quiet -m "$1"
}

# An old commit without any mise config, then a newer one that adds it to the root and to sub/.
make_origin() {
	mkdir -p "$ORIGIN/sub"
	printf '%s\n' 'old' >"$ORIGIN/sub/README"
	git -C "$ORIGIN" init --quiet
	commit old
	OLD_SHA="$(git -C "$ORIGIN" rev-parse HEAD)"
	for dir in "$ORIGIN" "$ORIGIN/sub"; do
		printf '%s\n' '[tools]' 'task = "3.54.0"' >"$dir/mise.toml"
		printf '%s\n' 'lockfile_version = 3' >"$dir/mise.lock"
		printf '%s\n' '[tools]' 'task = ["3.54.0", "3.51.1"]' >"$dir/mise.ci.toml"
		printf '%s\n' 'lockfile_version = 3' >"$dir/mise.ci.lock"
		printf '%s\n' 'unrelated' >"$dir/other.toml"
		printf '%s\n' '[tools]' >"$dir/mise.local.toml"
		printf '%s\n' '[tools]' >"$dir/mise.ci.local.toml"
	done
	mkdir -p "$ORIGIN/sub/nested"
	printf '%s\n' '[tools]' >"$ORIGIN/sub/nested/mise.toml"
	commit config
	NEW_SHA="$(git -C "$ORIGIN" rev-parse HEAD)"
	export OLD_SHA NEW_SHA
}

@test "restore should_do_nothing_when_no_config_ref_is_given" {
	run "$SCRIPT" "$CLONE/sub" ""

	[ "$status" -eq 0 ]
	[ -z "$output" ]
	[ ! -e "$CLONE/sub/mise.toml" ]
}

@test "restore should_leave_an_existing_mise_toml_alone_without_fetching" {
	printf '%s\n' '[tools]' >"$CLONE/sub/mise.toml"

	run "$SCRIPT" "$CLONE/sub" "no-such-ref"

	[ "$status" -eq 0 ]
	[ -z "$output" ]
	[ "$(cat "$CLONE/sub/mise.toml")" = "[tools]" ]
}

@test "restore should_restore_only_the_mise_config_and_locks_of_the_working_directory" {
	run "$SCRIPT" "$CLONE/sub" "$NEW_SHA"

	[ "$status" -eq 0 ]
	[[ "$output" == *"No mise.toml in $CLONE/sub; restoring the mise config from $NEW_SHA"* ]]
	[[ "$output" == *"Restored from $NEW_SHA: sub/mise.ci.lock sub/mise.ci.toml sub/mise.lock sub/mise.toml"* ]]
	for file in mise.toml mise.lock mise.ci.toml mise.ci.lock; do
		cmp "$CLONE/sub/$file" "$ORIGIN/sub/$file"
	done
	[ ! -e "$CLONE/sub/other.toml" ]
	[ ! -e "$CLONE/sub/mise.local.toml" ]
	[ ! -e "$CLONE/sub/mise.ci.local.toml" ]
	[ ! -e "$CLONE/sub/nested/mise.toml" ]
	[ ! -e "$CLONE/mise.toml" ]
}

@test "restore should_leave_the_index_and_git_status_clean" {
	run "$SCRIPT" "$CLONE/sub" "$NEW_SHA"

	[ "$status" -eq 0 ]
	git -C "$CLONE" diff --cached --quiet
	git -C "$CLONE" diff --quiet
	[ -z "$(git -C "$CLONE" status --porcelain)" ]
	[ -f "$CLONE/sub/mise.toml" ]
}

@test "restore should_keep_git_status_clean_when_the_restored_files_are_tracked_but_deleted" {
	git -C "$CLONE" -c advice.detachedHead=false checkout --quiet "$NEW_SHA"
	rm "$CLONE/sub/mise.toml" "$CLONE/sub/mise.lock" "$CLONE/sub/mise.ci.toml" "$CLONE/sub/mise.ci.lock"

	run "$SCRIPT" "$CLONE/sub" "$NEW_SHA"

	[ "$status" -eq 0 ]
	[ -z "$(git -C "$CLONE" status --porcelain)" ]
	[ -f "$CLONE/sub/mise.ci.lock" ]
}

@test "restore should_keep_a_full_clone_full_when_the_ref_is_a_present_commit" {
	run "$SCRIPT" "$CLONE/sub" "$NEW_SHA"

	[ "$status" -eq 0 ]
	[ "$(git -C "$CLONE" rev-parse --is-shallow-repository)" = "false" ]
	[ "$(git -C "$CLONE" rev-list --count --all)" -eq 2 ]
}

@test "restore should_keep_a_full_clone_full_when_the_ref_must_be_fetched" {
	git -C "$ORIGIN" -c tag.gpgSign=false -c tag.forceSignAnnotated=false tag config-tag "$NEW_SHA"

	run "$SCRIPT" "$CLONE/sub" config-tag

	[ "$status" -eq 0 ]
	[ "$(git -C "$CLONE" rev-parse --is-shallow-repository)" = "false" ]
	[ "$(git -C "$CLONE" rev-list --count --all)" -eq 2 ]
	cmp "$CLONE/sub/mise.toml" "$ORIGIN/sub/mise.toml"
}

@test "restore should_fetch_shallowly_into_a_shallow_checkout" {
	rm -rf "$CLONE"
	git clone --quiet --depth 1 "file://$ORIGIN" "$CLONE"
	git -C "$ORIGIN" -c tag.gpgSign=false -c tag.forceSignAnnotated=false tag config-tag "$NEW_SHA"
	rm "$CLONE/sub/mise.toml"

	run "$SCRIPT" "$CLONE/sub" config-tag

	[ "$status" -eq 0 ]
	[ "$(git -C "$CLONE" rev-parse --is-shallow-repository)" = "true" ]
	cmp "$CLONE/sub/mise.toml" "$ORIGIN/sub/mise.toml"
}

@test "restore should_add_each_exclude_line_only_once_across_repeated_restores" {
	run "$SCRIPT" "$CLONE/sub" "$NEW_SHA"
	[ "$status" -eq 0 ]
	rm "$CLONE"/sub/mise.toml

	run "$SCRIPT" "$CLONE/sub" "$NEW_SHA"

	[ "$status" -eq 0 ]
	[ "$(grep -cxF '/sub/mise.toml' "$CLONE/.git/info/exclude")" -eq 1 ]
	[ "$(grep -cxF '/sub/mise.ci.lock' "$CLONE/.git/info/exclude")" -eq 1 ]
}

@test "restore should_work_in_a_git_worktree_whose_git_dir_is_a_file" {
	local worktree="$TEST_ROOT/worktree"
	git -C "$CLONE" worktree add --quiet --detach "$worktree" "$OLD_SHA"
	[ -f "$worktree/.git" ]

	run "$SCRIPT" "$worktree/sub" "$NEW_SHA"

	[ "$status" -eq 0 ]
	cmp "$worktree/sub/mise.toml" "$ORIGIN/sub/mise.toml"
	[ -z "$(git -C "$worktree" status --porcelain)" ]
	git -C "$worktree" diff --cached --quiet
}

@test "restore should_reject_a_config_ref_that_starts_with_a_dash" {
	run "$SCRIPT" "$CLONE/sub" "--upload-pack=touch $TEST_ROOT/pwned"

	[ "$status" -eq 1 ]
	[[ "$output" == *"is not a valid git ref"* ]]
	[ ! -e "$TEST_ROOT/pwned" ]
}

@test "restore should_restore_the_root_config_for_the_default_working_directory" {
	cd "$CLONE"

	run "$SCRIPT" . "$NEW_SHA"

	[ "$status" -eq 0 ]
	[[ "$output" == *"Restored from $NEW_SHA: mise.ci.lock mise.ci.toml mise.lock mise.toml"* ]]
	cmp "$CLONE/mise.toml" "$ORIGIN/mise.toml"
	[ ! -e "$CLONE/other.toml" ]
	[ ! -e "$CLONE/sub/mise.toml" ]
}

@test "restore should_fail_when_the_ref_has_no_mise_toml_either" {
	run "$SCRIPT" "$CLONE/sub" "$OLD_SHA"

	[ "$status" -eq 1 ]
	[[ "$output" == *"$OLD_SHA has no sub/mise.toml either; nothing to install from"* ]]
	[ ! -e "$CLONE/sub/mise.toml" ]
}

@test "restore should_fail_with_an_actionable_error_when_the_ref_cannot_be_fetched" {
	run "$SCRIPT" "$CLONE/sub" "no-such-ref"

	[ "$status" -eq 1 ]
	[[ "$output" == *"::error::could not fetch no-such-ref from origin to restore the mise config."* ]]
	[[ "$output" == *"persist-credentials"* ]]
	[ ! -e "$CLONE/sub/mise.toml" ]
}

@test "restore should_create_a_working_directory_the_older_checkout_lacks" {
	mkdir -p "$ORIGIN/later"
	printf '%s\n' '[tools]' >"$ORIGIN/later/mise.toml"
	commit later

	run "$SCRIPT" "$CLONE/later" "$(git -C "$ORIGIN" rev-parse HEAD)"

	[ "$status" -eq 0 ]
	cmp "$CLONE/later/mise.toml" "$ORIGIN/later/mise.toml"
}

@test "restore should_restore_the_file_tasks_beside_the_config" {
	mkdir -p "$ORIGIN/sub/mise-tasks/lint"
	printf '%s\n' '#!/usr/bin/env bash' 'echo lint' >"$ORIGIN/sub/mise-tasks/lint/check.sh"
	commit tasks
	TASKS_SHA="$(git -C "$ORIGIN" rev-parse HEAD)"

	run "$SCRIPT" "$CLONE/sub" "$TASKS_SHA"

	[ "$status" -eq 0 ]
	[[ "$output" == *"sub/mise.toml sub/mise-tasks"* ]]
	cmp "$CLONE/sub/mise-tasks/lint/check.sh" "$ORIGIN/sub/mise-tasks/lint/check.sh"
	[ -z "$(git -C "$CLONE" status --porcelain)" ]
}

@test "restore should_leave_file_tasks_the_checkout_already_has" {
	mkdir -p "$ORIGIN/sub/mise-tasks"
	printf '%s\n' 'new' >"$ORIGIN/sub/mise-tasks/t.sh"
	commit tasks
	TASKS_SHA="$(git -C "$ORIGIN" rev-parse HEAD)"
	mkdir -p "$CLONE/sub/mise-tasks"
	printf '%s\n' 'old' >"$CLONE/sub/mise-tasks/t.sh"

	run "$SCRIPT" "$CLONE/sub" "$TASKS_SHA"

	[ "$status" -eq 0 ]
	[ "$(cat "$CLONE/sub/mise-tasks/t.sh")" = "old" ]
}
