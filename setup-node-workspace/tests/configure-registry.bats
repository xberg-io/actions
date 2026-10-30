#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/configure-registry.sh"
	export RUNNER_TEMP="$BATS_TEST_TMPDIR/runner-temp"
	mkdir -p "$RUNNER_TEMP"
}

run_script() {
	run env -u NODE_AUTH_TOKEN -u GITHUB_REPOSITORY_OWNER "$@"
}

@test "configure_registry should_write_a_token_reference_and_the_registry_like_setup_node" {
	run_script "$SCRIPT" https://registry.npmjs.org

	xberg_assert_status 0
	xberg_assert_file "$RUNNER_TEMP/.npmrc" "$(printf '%s\n' '//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}' \
		'registry=https://registry.npmjs.org/')"
	xberg_assert_github_env "$(printf '%s\n' "NPM_CONFIG_USERCONFIG=$RUNNER_TEMP/.npmrc" \
		'NODE_AUTH_TOKEN=XXXXX-XXXXX-XXXXX-XXXXX')"
}

@test "configure_registry should_pass_a_set_token_on_without_writing_it_to_the_npmrc_or_the_log" {
	run_script NODE_AUTH_TOKEN=npm_secret-token "$SCRIPT" https://registry.npmjs.org/

	xberg_assert_status 0
	[[ "$output" != *"npm_secret-token"* ]]
	! grep -q "npm_secret-token" "$RUNNER_TEMP/.npmrc"
	local delimiter
	delimiter="$(sed -n 's/^NODE_AUTH_TOKEN<<//p' "$GITHUB_ENV")"
	[[ "$delimiter" =~ ^NODE_AUTH_TOKEN_[0-9a-f]{16}$ ]]
	xberg_assert_github_env "$(printf '%s\n' "NPM_CONFIG_USERCONFIG=$RUNNER_TEMP/.npmrc" "NODE_AUTH_TOKEN<<$delimiter" \
		npm_secret-token "$delimiter")"
}

@test "configure_registry should_replace_an_earlier_registry_line_and_keep_other_settings" {
	printf '%s\n' 'registry=https://old.example/' 'fund=false' >"$RUNNER_TEMP/.npmrc"

	run_script "$SCRIPT" https://registry.npmjs.org/

	xberg_assert_status 0
	xberg_assert_file "$RUNNER_TEMP/.npmrc" "$(printf '%s\n' 'fund=false' \
		'//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}' 'registry=https://registry.npmjs.org/')"
}

@test "configure_registry should_scope_github_packages_to_the_repository_owner" {
	run_script GITHUB_REPOSITORY_OWNER=Xberg-IO "$SCRIPT" https://npm.pkg.github.com

	xberg_assert_status 0
	xberg_assert_file "$RUNNER_TEMP/.npmrc" "$(printf '%s\n' '//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}' \
		'@xberg-io:registry=https://npm.pkg.github.com/')"
}

@test "configure_registry should_reject_a_value_that_is_not_an_http_url" {
	run_script "$SCRIPT" 'registry.npmjs.org; rm -rf /'

	xberg_assert_status 1
	xberg_assert_output_contains "registry-url must be an http(s) URL"
	xberg_assert_file_absent "$RUNNER_TEMP/.npmrc"
}
