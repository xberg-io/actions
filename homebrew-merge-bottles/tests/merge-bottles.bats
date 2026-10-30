#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ACTION_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	mkdir -p "$STUB_BIN" "$TEST_ROOT/tap/Formula" "$TEST_ROOT/json"
	ORIGINAL_PATH="$PATH"
	printf '%s\n' '#!/usr/bin/env bash' \
		'case "$*" in' \
		'*"bottle.tags | keys[0]"*) printf arm64_sonoma ;;' \
		'*".sha256"*) printf deadbeef ;;' \
		'*) printf any_skip_relocation ;;' \
		'esac' >"$STUB_BIN/jq"
	printf '#!/usr/bin/env bash\nprintf " Formula/demo.rb | 7 +++++--\\n"\n' >"$STUB_BIN/git"
	chmod +x "$STUB_BIN/jq" "$STUB_BIN/git"
}

teardown() {
	rm -rf "$TEST_ROOT"
}

@test "should_replace_all_existing_bottle_blocks_inside_formula_class" {
	formula="$TEST_ROOT/tap/Formula/demo.rb"
	printf '%s\n' \
		'class Demo < Formula' \
		'  desc "demo"' \
		'  license "MIT"' \
		'  bottle do' \
		'    root_url "old"' \
		'  end' \
		'  url "https://example.invalid/demo.tar.gz"' \
		'end' \
		'bottle do' \
		'  root_url "wrong scope"' \
		'end' >"$formula"
	printf '{}' >"$TEST_ROOT/json/demo--1.2.3.arm64_sonoma.bottle.json"

	run env PATH="$STUB_BIN:$ORIGINAL_PATH" TAG=v1.2.3 VERSION=1.2.3 \
		TAP_DIR="$TEST_ROOT/tap" JSON_DIR="$TEST_ROOT/json" FORMULAS=demo \
		GITHUB_REPO=example/project bash "$ACTION_DIR/scripts/merge-bottles.sh"

	[ "$status" -eq 0 ]
	[ "$output" = $'Merged formulas:\n Formula/demo.rb | 7 +++++--' ]
	run cat "$formula"
	[ "$status" -eq 0 ]
	[ "$output" = $'class Demo < Formula\n  desc "demo"\n  license "MIT"\n\n  bottle do\n    root_url "https://github.com/example/project/releases/download/v1.2.3"\n    sha256 cellar: :any_skip_relocation, arm64_sonoma: "deadbeef"\n  end\n  url "https://example.invalid/demo.tar.gz"\nend' ]
}

@test "should_return_error_when_formula_has_no_json_manifest" {
	run env PATH="$STUB_BIN:$ORIGINAL_PATH" TAG=v1 VERSION=1 TAP_DIR="$TEST_ROOT/tap" \
		JSON_DIR="$TEST_ROOT/json" FORMULAS=missing GITHUB_REPO=example/project \
		bash "$ACTION_DIR/scripts/merge-bottles.sh"

	[ "$status" -eq 1 ]
	[ "$output" = "ERROR: no JSON manifests for missing in $TEST_ROOT/json" ]
}
