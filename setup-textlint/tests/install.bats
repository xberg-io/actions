#!/usr/bin/env bats

setup() {
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/install.sh"
	BIN="$BATS_TEST_TMPDIR/bin"
	mkdir -p "$BIN"
	export PATH="$BIN:$PATH"
	export TEXTLINT_DIR="$BATS_TEST_TMPDIR/textlint"
	export GITHUB_PATH="$BATS_TEST_TMPDIR/github-path"
	export GITHUB_ENV="$BATS_TEST_TMPDIR/github-env"
	: >"$GITHUB_PATH"
	: >"$GITHUB_ENV"
}

@test "should_install_standard_and_extra_textlint_packages_with_safe_pnpm_flags" {
	printf '%s\n' '#!/usr/bin/env bash' 'printf "%s\n" "$*" >"$NPM_CALL"' >"$BIN/pnpm"
	chmod +x "$BIN/pnpm"
	export NPM_CALL="$BATS_TEST_TMPDIR/npm-call"
	export INPUT_EXTRA_PACKAGES="textlint-rule-prh @scope/rule"
	run "$SCRIPT"
	[ "$status" -eq 0 ]
	[ "$(cat "$NPM_CALL")" = "add --dir $TEXTLINT_DIR --ignore-scripts --config.strict-peer-dependencies=false textlint textlint-rule-no-todo textlint-rule-no-start-duplicated-conjunction textlint-rule-no-empty-section textlint-rule-terminology textlint-rule-no-zero-width-spaces @textlint-rule/textlint-rule-no-invalid-control-character textlint-rule-no-surrogate-pair @textlint-rule/textlint-rule-no-unmatched-pair textlint-rule-alex textlint-rule-write-good textlint-rule-common-misspellings textlint-rule-stop-words textlint-rule-en-capitalization textlint-filter-rule-comments textlint-filter-rule-node-types textlint-rule-prh @scope/rule" ]
	[ "$(cat "$GITHUB_PATH")" = "$TEXTLINT_DIR/node_modules/.bin" ]
	[ "$(cat "$GITHUB_ENV")" = "NODE_PATH=$TEXTLINT_DIR/node_modules" ]
	[ -f "$TEXTLINT_DIR/package.json" ]
}

@test "should_return_pnpm_failure_when_package_install_fails" {
	printf '%s\n' '#!/usr/bin/env bash' 'exit 23' >"$BIN/pnpm"
	chmod +x "$BIN/pnpm"
	run "$SCRIPT"
	[ "$status" -eq 23 ]
	[ "$output" = "" ]
	[ ! -s "$GITHUB_PATH" ]
	[ ! -s "$GITHUB_ENV" ]
}
