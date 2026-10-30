#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ACTION_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	TRACE="$TEST_ROOT/brew-trace"
	mkdir -p "$STUB_BIN"
	ORIGINAL_PATH="$PATH"
	# BREW_TRUSTED_TAPS is the stub trust store: `trust --json v1` reports exactly these,
	# so a test can simulate `brew trust` exiting 0 without the entry landing. ~keep
	printf '%s\n' '#!/usr/bin/env bash' \
		'printf "%s\n" "$*" >>"$BREW_TRACE"' \
		'case "$1" in' \
		'--version) echo "Homebrew 7.0.0" ;;' \
		'config) echo "HOMEBREW_VERSION: 7.0.0" ;;' \
		'trust)' \
		'  case "$2" in' \
		'    --help) [ "${BREW_HAS_TRUST:-1}" = 1 ] || exit 1 ;;' \
		'    --json)' \
		'      [ "${BREW_TRUST_JSON_OK:-1}" = 1 ] || exit 1' \
		'      printf "{\"taps\":[%s],\"formulae\":[]}" "${BREW_TRUSTED_TAPS-\"example/tap\"}" ;;' \
		'  esac' \
		'  exit 0 ;;' \
		'update|tap|install) exit 0 ;;' \
		'uninstall|list) exit 1 ;;' \
		'bottle)' \
		'  printf bottle > "demo--1.2.3.arm64_sonoma.bottle.tar.gz"' \
		'  printf "{}" > "demo--1.2.3.arm64_sonoma.bottle.json" ;;' \
		'esac' >"$STUB_BIN/brew"
	printf '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$GH_TRACE"\n' >"$STUB_BIN/gh"
	chmod +x "$STUB_BIN/brew" "$STUB_BIN/gh"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

@test "should_stage_renamed_bottle_and_manifest_when_upload_is_false" {
	out_dir="$TEST_ROOT/output"
	gh_trace="$TEST_ROOT/gh-trace"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" BREW_TRACE="$TRACE" GH_TRACE="$gh_trace" \
		TAG=v1.2.3 VERSION=1.2.3 TAP=example/tap FORMULAS=demo OUT_DIR="$out_dir" \
		GITHUB_REPO=example/project UPLOAD=false RUNNER_OS=macOS \
		bash "$ACTION_DIR/scripts/build-bottles.sh"

	[ "$status" -eq 0 ]
	[ "$(cat "$out_dir/demo-1.2.3.arm64_sonoma.bottle.tar.gz")" = "bottle" ]
	[ "$(cat "$out_dir/demo--1.2.3.arm64_sonoma.bottle.json")" = "{}" ]
	[ ! -e "$gh_trace" ]
	[ "$(cat "$TRACE")" = $'--version\nconfig\nupdate --quiet\ntrust --help\ntrust --tap example/tap\ntrust --json v1\ntap example/tap\nuninstall --force example/tap/demo\n--repository example/tap\nlist libheif\ninstall --build-bottle --verbose example/tap/demo\nbottle --json --no-rebuild example/tap/demo' ]
	[[ "$output" == *"UPLOAD=false: staged demo-1.2.3.arm64_sonoma.bottle.tar.gz in $out_dir for caller-side upload"* ]]
}

@test "should_return_error_when_brew_produces_no_bottle_tarball" {
	printf '%s\n' '#!/usr/bin/env bash' \
		'case "$1" in' \
		'--version) echo "Homebrew 7.0.0" ;;' \
		'trust) [ "$2" != --json ] || printf "{\"taps\":[\"example/tap\"]}"; exit 0 ;;' \
		'config|update|tap|install) exit 0 ;;' \
		'uninstall|list) exit 1 ;;' \
		'esac' \
		>"$STUB_BIN/brew"
	chmod +x "$STUB_BIN/brew"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" TAG=v1 VERSION=1 TAP=example/tap FORMULAS=demo \
		OUT_DIR="$TEST_ROOT/output" GITHUB_REPO=example/project UPLOAD=false RUNNER_OS=macOS \
		bash "$ACTION_DIR/scripts/build-bottles.sh"

	[ "$status" -eq 1 ]
	[[ "$output" == *"ERROR: no bottle tarball produced for demo"* ]]
}

@test "should_fail_when_brew_trust_exits_zero_but_the_tap_never_lands_in_the_store" {
	run env PATH="$STUB_BIN:$ORIGINAL_PATH" BREW_TRACE="$TRACE" BREW_TRUSTED_TAPS="" \
		TAG=v1.2.3 VERSION=1.2.3 TAP=example/tap FORMULAS=demo OUT_DIR="$TEST_ROOT/output" \
		GITHUB_REPO=example/project UPLOAD=false RUNNER_OS=macOS \
		bash "$ACTION_DIR/scripts/build-bottles.sh"

	[ "$status" -ne 0 ]
	[[ "$output" == *"is absent from the trust store"* ]]
	# The tap must never be attempted once trust is known not to have landed. ~keep
	[[ "$(cat "$TRACE")" != *$'\ntap example/tap'* ]]
}

@test "should_skip_trust_and_still_tap_when_brew_predates_the_trust_command" {
	out_dir="$TEST_ROOT/output"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" BREW_TRACE="$TRACE" BREW_HAS_TRUST=0 \
		TAG=v1.2.3 VERSION=1.2.3 TAP=example/tap FORMULAS=demo OUT_DIR="$out_dir" \
		GITHUB_REPO=example/project UPLOAD=false RUNNER_OS=macOS \
		bash "$ACTION_DIR/scripts/build-bottles.sh"

	[ "$status" -eq 0 ]
	[[ "$output" == *"no \`trust\` command (pre-7.0)"* ]]
	[[ "$(cat "$TRACE")" == *$'trust --help\ntap example/tap'* ]]
}

@test "should_warn_and_continue_when_the_trust_store_cannot_be_read_back" {
	out_dir="$TEST_ROOT/output"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" BREW_TRACE="$TRACE" BREW_TRUST_JSON_OK=0 \
		TAG=v1.2.3 VERSION=1.2.3 TAP=example/tap FORMULAS=demo OUT_DIR="$out_dir" \
		GITHUB_REPO=example/project UPLOAD=false RUNNER_OS=macOS \
		bash "$ACTION_DIR/scripts/build-bottles.sh"

	# A brew that cannot report its trust store must not take the whole bottle build with it:
	# trust was still granted, so the tap proceeds. ~keep
	[ "$status" -eq 0 ]
	[[ "$output" == *"skipping the trust assertion"* ]]
	[[ "$(cat "$TRACE")" == *$'trust --tap example/tap\ntrust --json v1\ntap example/tap'* ]]
}

@test "should_accept_the_store_short_name_when_the_tap_input_carries_the_homebrew_prefix" {
	out_dir="$TEST_ROOT/output"

	# The workflows pass `tap: xberg-io/homebrew-tap`, but `brew trust` records the short form
	# `xberg-io/tap` -- Homebrew treats the two as one tap. Comparing the raw input against the
	# store failed all three alef 0.89.0 bottle legs on a tap that HAD been trusted. ~keep
	run env PATH="$STUB_BIN:$ORIGINAL_PATH" BREW_TRACE="$TRACE" BREW_TRUSTED_TAPS='"example/tap"' \
		TAG=v1.2.3 VERSION=1.2.3 TAP=example/homebrew-tap FORMULAS=demo OUT_DIR="$out_dir" \
		GITHUB_REPO=example/project UPLOAD=false RUNNER_OS=macOS \
		bash "$ACTION_DIR/scripts/build-bottles.sh"

	[ "$status" -eq 0 ]
	[[ "$output" == *"Trusted tap verified in store: example/tap"* ]]
	[[ "$output" != *"absent from the trust store"* ]]
}
