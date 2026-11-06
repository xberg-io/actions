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
		'bottle) "$BOTTLE_STUB" ;;' \
		'esac' >"$STUB_BIN/brew"
	printf '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$GH_TRACE"\n' >"$STUB_BIN/gh"
	# `brew bottle` writes a real tarball holding one Mach-O (by magic bytes) and a manifest
	# shaped like `brew bottle --json`, tagged $BOTTLE_HOST_TAG. ~keep
	export BOTTLE_STUB="$TEST_ROOT/bottle-stub"
	cat >"$BOTTLE_STUB" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
tag="${BOTTLE_HOST_TAG:-arm64_tahoe}"
stage="$(mktemp -d)"
mkdir -p "$stage/demo/1.2.3/bin"
printf '\317\372\355\376stub' >"$stage/demo/1.2.3/bin/demo"
printf 'readme' >"$stage/demo/1.2.3/README"
if [ "${BOTTLE_EXTRA_FILES:-0}" = 1 ]; then
	mkdir -p "$stage/demo/1.2.3/lib"
	printf '\312\376\272\276\000\000\000\002' >"$stage/demo/1.2.3/lib/libdemo.dylib"
	printf '\312\376\272\276\000\000\000\101' >"$stage/demo/1.2.3/lib/Demo.class"
fi
tar -czf "demo--1.2.3.${tag}.bottle.tar.gz" -C "$stage" demo
printf '{"example/tap/demo":{"bottle":{"tags":{"%s":{"filename":"demo-1.2.3.%s.bottle.tar.gz","local_filename":"demo--1.2.3.%s.bottle.tar.gz","sha256":"abc"}}}}}' \
	"$tag" "$tag" "$tag" >"demo--1.2.3.${tag}.bottle.json"
STUB
	# otool reports one LC_BUILD_VERSION whose minos is $OTOOL_MINOS, and rejects a Java class
	# file the way the real one does. ~keep
	cat >"$STUB_BIN/otool" <<'STUB'
#!/usr/bin/env bash
[[ "${*: -1}" != *.class ]] || { echo "otool: not an object file" >&2; exit 1; }
printf '%s\n' "${@: -1}:" "Load command 9" "      cmd LC_BUILD_VERSION" "  cmdsize 32" " platform 1" \
	"    minos ${OTOOL_MINOS:-15.0}" "      sdk 26.0"
STUB
	chmod +x "$STUB_BIN/brew" "$STUB_BIN/gh" "$STUB_BIN/otool" "$BOTTLE_STUB"
}

# Runs the action script with the default stubs; extra VAR=value pairs go first.
run_build() {
	run env PATH="$STUB_BIN:$ORIGINAL_PATH" BREW_TRACE="$TRACE" GH_TRACE="$TEST_ROOT/gh-trace" "$@" \
		TAG=v1.2.3 VERSION=1.2.3 TAP=example/tap FORMULAS=demo OUT_DIR="$TEST_ROOT/output" \
		GITHUB_REPO=example/project UPLOAD=false RUNNER_OS=macOS \
		bash "$ACTION_DIR/scripts/build-bottles.sh"
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
	tar -tzf "$out_dir/demo-1.2.3.arm64_sequoia.bottle.tar.gz" | grep -qx 'demo/1.2.3/bin/demo'
	[ -f "$out_dir/demo--1.2.3.arm64_sequoia.bottle.json" ]
	[ ! -e "$gh_trace" ]
	[ "$(cat "$TRACE")" = $'--version\nconfig\nupdate --quiet\ntrust --help\ntrust --tap example/tap\ntrust --json v1\ntap example/tap\nuninstall --force example/tap/demo\n--repository example/tap\nlist libheif\ninstall --build-bottle --verbose example/tap/demo\nbottle --json --no-rebuild example/tap/demo' ]
	[[ "$output" == *"UPLOAD=false: staged demo-1.2.3.arm64_sequoia.bottle.tar.gz in $out_dir for caller-side upload"* ]]
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

@test "should_retag_the_arm64_bottle_and_manifest_to_the_floor" {
	run_build BOTTLE_HOST_TAG=arm64_tahoe

	[ "$status" -eq 0 ]
	out_dir="$TEST_ROOT/output"
	[ -f "$out_dir/demo-1.2.3.arm64_sequoia.bottle.tar.gz" ]
	[ ! -e "$out_dir/demo--1.2.3.arm64_tahoe.bottle.json" ]
	manifest="$out_dir/demo--1.2.3.arm64_sequoia.bottle.json"
	[ "$(jq -r '.[].bottle.tags | keys | join(",")' "$manifest")" = "arm64_sequoia" ]
	[ "$(jq -r '.[].bottle.tags.arm64_sequoia.filename' "$manifest")" = "demo-1.2.3.arm64_sequoia.bottle.tar.gz" ]
	[ "$(jq -r '.[].bottle.tags.arm64_sequoia.local_filename' "$manifest")" = "demo--1.2.3.arm64_sequoia.bottle.tar.gz" ]
	[ "$(jq -r '.[].bottle.tags.arm64_sequoia.sha256' "$manifest")" = "abc" ]
	[[ "$output" == *"Bottle floor check: 1 Mach-O file(s) run on macOS 15.0 (arm64_sequoia)"* ]]
	[[ "$output" == *"Retagged demo bottle arm64_tahoe -> arm64_sequoia"* ]]
}

@test "should_retag_the_intel_bottle_to_the_floor_without_an_arch_prefix" {
	run_build BOTTLE_HOST_TAG=tahoe

	[ "$status" -eq 0 ]
	[ -f "$TEST_ROOT/output/demo-1.2.3.sequoia.bottle.tar.gz" ]
	[ "$(jq -r '.[].bottle.tags | keys | join(",")' "$TEST_ROOT/output/demo--1.2.3.sequoia.bottle.json")" = "sequoia" ]
}

@test "should_keep_the_host_tag_when_the_floor_input_names_it" {
	run_build BOTTLE_HOST_TAG=arm64_tahoe BOTTLE_FLOOR=tahoe OTOOL_MINOS=26.0

	[ "$status" -eq 0 ]
	[ -f "$TEST_ROOT/output/demo-1.2.3.arm64_tahoe.bottle.tar.gz" ]
	[ "$(jq -r '.[].bottle.tags | keys | join(",")' "$TEST_ROOT/output/demo--1.2.3.arm64_tahoe.bottle.json")" = "arm64_tahoe" ]
	[[ "$output" == *"Bottle floor check: 1 Mach-O file(s) run on macOS 26.0 (arm64_tahoe)"* ]]
	[[ "$output" != *"Retagged"* ]]
}

@test "should_check_universal_binaries_and_skip_java_class_files" {
	run_build BOTTLE_HOST_TAG=arm64_tahoe BOTTLE_EXTRA_FILES=1

	[ "$status" -eq 0 ]
	[[ "$output" == *"Bottle floor check: 2 Mach-O file(s) run on macOS 15.0 (arm64_sequoia)"* ]]
}

@test "should_leave_linux_bottle_tags_untouched" {
	run_build BOTTLE_HOST_TAG=x86_64_linux OTOOL_MINOS=26.0

	[ "$status" -eq 0 ]
	[ -f "$TEST_ROOT/output/demo-1.2.3.x86_64_linux.bottle.tar.gz" ]
	[ "$(jq -r '.[].bottle.tags | keys | join(",")' "$TEST_ROOT/output/demo--1.2.3.x86_64_linux.bottle.json")" = "x86_64_linux" ]
	[[ "$output" != *"Bottle floor check"* ]]
}

@test "should_fail_when_a_mach_o_needs_a_newer_macos_than_the_floor" {
	run_build BOTTLE_HOST_TAG=arm64_tahoe OTOOL_MINOS=26.0

	[ "$status" -ne 0 ]
	[[ "$output" == *"ERROR: demo/1.2.3/bin/demo needs macOS 26.0, newer than the arm64_sequoia bottle floor (macOS 15.0)"* ]]
	[ ! -e "$TEST_ROOT/output/demo-1.2.3.arm64_sequoia.bottle.tar.gz" ]
}

@test "should_reject_a_floor_below_the_supported_macos_releases" {
	run_build BOTTLE_HOST_TAG=arm64_tahoe BOTTLE_FLOOR=sonoma

	[ "$status" -ne 0 ]
	[[ "$output" == *"BOTTLE_FLOOR 'sonoma' is not a supported macOS bottle floor"* ]]
}
