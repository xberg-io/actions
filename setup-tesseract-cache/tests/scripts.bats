#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT_DIR="$(cd "$BATS_TEST_DIRNAME/../scripts" && pwd)"
	WORK="$BATS_TEST_TMPDIR/work"
	mkdir -p "$WORK"
	export GITHUB_WORKSPACE="$WORK"
	export GITHUB_ENV="$BATS_TEST_TMPDIR/github-env"
	export GITHUB_OUTPUT="$BATS_TEST_TMPDIR/github-output"
	: >"$GITHUB_ENV"
	: >"$GITHUB_OUTPUT"
}

@test "should_create_labelled_tesseract_cache_directories" {
	run bash -c 'cd "$1" && "$2/setup-dirs.sh" linux-x64 .cache' _ "$WORK" "$SCRIPT_DIR"
	[ "$status" -eq 0 ]
	[ -d "$WORK/.cache/linux-x64" ]
	[ -d "$WORK/.xdg-cache/linux-x64" ]
}

@test "should_remove_labelled_cache_directories_when_cache_is_disabled" {
	mkdir -p "$WORK/.cache/linux-x64" "$WORK/.xdg-cache/linux-x64"
	run bash -c 'cd "$1" && "$2/clean-dirs.sh" linux-x64 .cache' _ "$WORK" "$SCRIPT_DIR"
	[ "$status" -eq 0 ]
	[ ! -e "$WORK/.cache/linux-x64" ]
	[ ! -e "$WORK/.xdg-cache/linux-x64" ]
}

@test "should_remove_target_specific_tesseract_cache" {
	mkdir -p "$WORK/target/aarch64/xberg-tesseract-cache"
	run bash -c 'cd "$1" && "$2/clean-target-cache.sh" aarch64' _ "$WORK" "$SCRIPT_DIR"
	[ "$status" -eq 0 ]
	[ ! -e "$WORK/target/aarch64/xberg-tesseract-cache" ]
}

@test "should_write_disabled_cache_outputs_when_cache_is_false" {
	run "$SCRIPT_DIR/set-outputs.sh" linux-x64 false .cache
	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_ENV")" = "TESSERACT_RS_CACHE_DIR=" ]
	[ "$(cat "$GITHUB_OUTPUT")" = $'cache-dir=\ncache-enabled=false\ndocker-options=' ]
}
