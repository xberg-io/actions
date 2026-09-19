#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	# A gh that answers the release GET with canned notes and records every PATCH it is
	# sent, one argument per line, so the test can assert the exact request body.
	xberg_stub gh \
		'if [ "$1" = api ] && [ "$2" = -X ] && [ "$3" = PATCH ]; then printf "%s\n" "$@" >>"$XBERG_TRACE"; exit 0; fi' \
		'if [ "$1" = api ]; then printf "%s" "$GH_STUB_BODY"; exit 0; fi' \
		'exit 99'
}

run_script() {
	run env GH_TOKEN=token GITHUB_REPOSITORY=example/project RELEASE_ID=4242 TAG=v1.2.3 \
		PKG_NAME=demo URL=https://example.invalid/demo.tar.gz HASH=1220abc \
		GH_STUB_BODY="$1" XBERG_TRACE="$XBERG_TRACE" \
		bash "$BATS_TEST_DIRNAME/../scripts/append-release-notes.sh"
}

# ~keep The PATCH must carry tag_name even though only the body changes. PATCH /releases/{id}
# on a release that is a draft before and after the request resets tag_name to untagged-*
# when the body omits it (reproduced against the live API; gh's own `release edit` re-sends
# it for the same reason). The release was resolved by this tag, so re-sending it is a no-op
# on a healthy release and what keeps a draft attached to its tag (xberg-io/actions#68).
@test "should_append_the_zig_fetch_block_and_resend_tag_name_so_a_draft_keeps_its_tag" {
	run_script "Existing notes"

	xberg_assert_status 0
	xberg_assert_output "Release notes updated with Zig fetch block"
	xberg_assert_trace api -X PATCH repos/example/project/releases/4242 -f tag_name=v1.2.3 \
		-f 'body=Existing notes

<!-- zig-fetch -->
## Zig

Add to your `build.zig.zon`:

```
.dependencies = .{
    .demo = .{
        .url = "https://example.invalid/demo.tar.gz",
        .hash = "1220abc",
    },
},
```
'
}

@test "should_not_patch_when_the_zig_fetch_block_is_already_present" {
	run_script $'Notes\n\n<!-- zig-fetch -->\n## Zig'

	xberg_assert_status 0
	xberg_assert_output "Zig fetch block already present in release notes"
	xberg_assert_trace_empty
}

@test "should_skip_without_calling_gh_when_no_token_is_set" {
	run env -u GH_TOKEN GITHUB_REPOSITORY=example/project RELEASE_ID=4242 TAG=v1.2.3 \
		PKG_NAME=demo URL=https://example.invalid/demo.tar.gz HASH=1220abc XBERG_TRACE="$XBERG_TRACE" \
		bash "$BATS_TEST_DIRNAME/../scripts/append-release-notes.sh"

	xberg_assert_status 0
	xberg_assert_output "GH_TOKEN not set; skipping release-notes update"
	xberg_assert_trace_empty
}

@test "should_return_error_without_calling_gh_when_tag_is_empty" {
	run env GH_TOKEN=token GITHUB_REPOSITORY=example/project RELEASE_ID=4242 TAG= \
		PKG_NAME=demo URL=https://example.invalid/demo.tar.gz HASH=1220abc XBERG_TRACE="$XBERG_TRACE" \
		bash "$BATS_TEST_DIRNAME/../scripts/append-release-notes.sh"

	xberg_assert_status 1
	xberg_assert_output "Error: TAG is required"
	xberg_assert_trace_empty
}
