#!/usr/bin/env bats

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$TEST_ROOT/bin"
	CALLS="$TEST_ROOT/calls.log"
	mkdir -p "$STUB_BIN"
	: >"$CALLS"
	printf '%s\n' '#!/usr/bin/env bash' \
		'echo "mise $* TEXTLINT_STRICT=${TEXTLINT_STRICT:-}" >>"$CALLS"' \
		'[ "$1 $2" = "tasks info" ] && [ "$3" != "${MISE_STUB_TASK:-}" ] && exit 1' \
		'exit 0' >"$STUB_BIN/mise"
	chmod +x "$STUB_BIN/mise"
	export TEST_ROOT STUB_BIN CALLS
}

teardown() {
	rm -rf "$TEST_ROOT"
}

# The detection is tested in build-docs/tests; both actions ship the same script.
@test "docs-runner should_match_the_build_docs_copy" {
	cmp "$BATS_TEST_DIRNAME/../scripts/docs-runner.sh" "$BATS_TEST_DIRNAME/../../build-docs/scripts/docs-runner.sh"
}

@test "docs-runner should_pass_textlint_strict_through_to_the_mise_prose_task" {
	cd "$TEST_ROOT"

	run env PATH="$STUB_BIN:/usr/bin:/bin" MISE_STUB_TASK="docs:lint:prose" TEXTLINT_STRICT=1 \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/docs-runner.sh" run docs:lint:prose textlint docs/

	[ "$status" -eq 0 ]
	grep -qx "mise run docs:lint:prose TEXTLINT_STRICT=1" "$CALLS"
}

@test "docs-runner should_run_the_snippet_fallback_when_no_runner_defines_the_task" {
	cd "$TEST_ROOT"

	run env PATH="$STUB_BIN:/usr/bin:/bin" /bin/bash "$BATS_TEST_DIRNAME/../scripts/docs-runner.sh" \
		run docs:snippets:validate echo alef snippets validate

	[ "$status" -eq 0 ]
	[[ "$output" == *$'\n'"alef snippets validate" ]]
	[ "$(grep -c '^mise run' "$CALLS")" -eq 0 ]
}
