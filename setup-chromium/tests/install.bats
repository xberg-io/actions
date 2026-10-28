#!/usr/bin/env bats

setup_file() {
	bats_load_library xberg-bats
	# setup-node provides node, npm and npx and nothing else: a pnpm call must fail here as it does on a runner.
	xberg_shadow_system_path_without pnpm npm npx node corepack
}

setup() {
	bats_load_library xberg-bats
	xberg_setup_isolated
	export RUNNER_TEMP="$BATS_TEST_TMPDIR/runner-temp"
	mkdir -p "$RUNNER_TEMP"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/install.sh"
	CHROMIUM="$BATS_TEST_TMPDIR/chrome"
	xberg_stub_trace npm
	xberg_stub_trace npx
	xberg_stub node "printf '%s\\n' '$CHROMIUM'"
}

@test "should_install_with_node_bundled_tools_and_system_deps_on_linux" {
	xberg_stub chrome 'exit 0'
	cp "$XBERG_STUB_BIN/chrome" "$CHROMIUM"
	run env -u PLAYWRIGHT_VERSION PATH="$(xberg_isolated_path)" RUNNER_OS=Linux /bin/bash "$SCRIPT"
	xberg_assert_status 0
	xberg_assert_trace "npm install --no-audit --no-fund --silent playwright@^1.49.0" \
		"npx --no-install playwright install --with-deps chromium"
	xberg_assert_github_output "chromium-path=$CHROMIUM"
}

@test "should_skip_system_deps_off_linux" {
	xberg_stub chrome 'exit 0'
	cp "$XBERG_STUB_BIN/chrome" "$CHROMIUM"
	run env -u PLAYWRIGHT_VERSION PATH="$(xberg_isolated_path)" RUNNER_OS=macOS /bin/bash "$SCRIPT"
	xberg_assert_status 0
	xberg_assert_trace "npm install --no-audit --no-fund --silent playwright@^1.49.0" \
		"npx --no-install playwright install chromium"
}

@test "should_fail_when_playwright_reports_no_executable_binary" {
	run env -u PLAYWRIGHT_VERSION PATH="$(xberg_isolated_path)" RUNNER_OS=Linux /bin/bash "$SCRIPT"
	xberg_assert_status 1
	xberg_assert_output_contains "ERROR: Chromium binary not found at: $CHROMIUM"
	xberg_assert_github_output ""
}
