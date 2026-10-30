#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ACTION_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	CLONE_SOURCE="$TEST_ROOT/clone-source"
	mkdir -p "$STUB_BIN" "$CLONE_SOURCE/Formula"
	ORIGINAL_PATH="$PATH"
	printf '%s\n' '#!/usr/bin/env bash' \
		'if [ "$1" = clone ]; then cp -R "$GIT_CLONE_SOURCE/." "$4"; printf cloned; fi' >"$STUB_BIN/git"
	chmod +x "$STUB_BIN/git"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

@test "should_verify_every_named_formula_contains_requested_version" {
	printf 'version "2.0.0"\n' >"$CLONE_SOURCE/Formula/first.rb"
	printf 'version "2.0.0"\n' >"$CLONE_SOURCE/Formula/second.rb"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" GIT_CLONE_SOURCE="$CLONE_SOURCE" \
		bash "$ACTION_DIR/scripts/verify-tap-push.sh" example/tap $'first\n\nsecond' 2.0.0

	[ "$status" -eq 0 ]
	[ "$output" = $'Verifying Homebrew tap push for 2.0.0...\nTap repo: example/tap\nFormulas: first\n\nsecond\nCloning tap repository for verification...\ncloned\n✓ first contains version 2.0.0\n✓ second contains version 2.0.0\n✓ Tap push verification succeeded — all formulas contain the correct version' ]
}

@test "should_return_error_when_cloned_formula_has_wrong_version" {
	printf 'version "1.0.0"\n' >"$CLONE_SOURCE/Formula/demo.rb"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" GIT_CLONE_SOURCE="$CLONE_SOURCE" \
		bash "$ACTION_DIR/scripts/verify-tap-push.sh" example/tap demo 2.0.0

	[ "$status" -eq 1 ]
	[ "$output" = $'Verifying Homebrew tap push for 2.0.0...\nTap repo: example/tap\nFormulas: demo\nCloning tap repository for verification...\ncloned\n::error::Formula demo does not contain version 2.0.0\nFile contents:\nversion "1.0.0"' ]
}

@test "should_return_usage_error_when_required_argument_is_empty" {
	run bash "$ACTION_DIR/scripts/verify-tap-push.sh" "" demo 2.0.0

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Usage: verify-tap-push.sh <tap-repo> <formulas> <version>" ]
}
