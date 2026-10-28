#!/usr/bin/env bats

setup() {
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
	[ ! -e "$CLONE/sub/nested/mise.toml" ]
	[ ! -e "$CLONE/mise.toml" ]
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

@test "restore should_fail_when_the_ref_cannot_be_fetched" {
	run "$SCRIPT" "$CLONE/sub" "no-such-ref"

	[ "$status" -ne 0 ]
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
