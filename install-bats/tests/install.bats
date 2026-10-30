#!/usr/bin/env bats

# ~keep Built once per file: the mirrors are read-only and identical for every test here, and
# rebuilding a few thousand symlinks per test is pure wall-clock.
setup_file() {
	bats_load_library xberg-bats
	SYS_ROOT="$(mktemp -d)"
	SYS_BIN="$SYS_ROOT/sysbin"
	SYS_BIN_WITHOUT_PYTHON3="$SYS_ROOT/sysbin-no-python3"
	export SYS_ROOT SYS_BIN SYS_BIN_WITHOUT_PYTHON3
	xberg_shadow_system_path_without curl
	SYS_BIN="$XBERG_SYS_BIN"
	BATS_FILE_TMPDIR="$SYS_ROOT/no-python" xberg_shadow_system_path_without curl python3
	SYS_BIN_WITHOUT_PYTHON3="$XBERG_SYS_BIN"
	# ~keep The whole point of the mirrors is that these commands are missing from them, and a
	# silent leak would put the affected tests back on the host's copies without failing.
	# python3 is asserted present because install.sh parses release metadata with the real
	# interpreter -- a mirror without it would turn every metadata test into a dependency-check
	# test that still passed. Assert the preconditions instead of assuming them.
	[ ! -e "$SYS_BIN/curl" ] || {
		echo "mirror leaked curl" >&2
		return 1
	}
	[ -x "$SYS_BIN/python3" ] || {
		echo "mirror is missing python3" >&2
		return 1
	}
	[ ! -e "$SYS_BIN_WITHOUT_PYTHON3/python3" ] || {
		echo "mirror leaked python3" >&2
		return 1
	}
}

teardown_file() {
	rm -rf "$SYS_ROOT"
}

setup() {
	bats_load_library xberg-bats
	xberg_setup
	# ~keep CI runs this suite through ./run-bats itself, so the outer action exports its own
	# INPUT_PATH and INPUT_ARGS into this process -- and `run env FOO=bar ...` ADDS to the
	# inherited environment rather than replacing it. Without this, the default-path tests read
	# the outer action's `path: .` and assert against the wrong directory. Locally there is no
	# outer action and they pass, so the leak is invisible off CI. Clear the whole prefix so
	# each test starts from nothing and sets only what it means to exercise.
	for _leaked_input in $(env | sed -n 's/^\(INPUT_[A-Za-z0-9_]*\)=.*/\1/p'); do
		unset "$_leaked_input"
	done
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$XBERG_STUB_BIN"
	INSTALL_DIR="$TEST_ROOT/install"
	GITHUB_PATH_FILE="$TEST_ROOT/github-path"
	CURL_LOG="$TEST_ROOT/curl.log"
	# install.sh resolves checksums.tsv relative to its own directory, so the suite runs against a
	# staged copy of the action rather than the checkout. That lets a test pin, unpin or delete the
	# table without touching the committed one, and lets the fixture builders pin the digest of the
	# archive they just built -- so every download test exercises the verified path instead of the
	# unpinned-version warning. ~keep
	ACTION_DIR="$TEST_ROOT/action"
	mkdir -p "$ACTION_DIR"
	cp -R "$BATS_TEST_DIRNAME/../scripts" "$ACTION_DIR/"
	cp "$BATS_TEST_DIRNAME/../checksums.tsv" "$ACTION_DIR/checksums.tsv"
	SCRIPT="$ACTION_DIR/scripts/install.sh"
	mkdir -p "$STUB_BIN" "$INSTALL_DIR"
	: >"$GITHUB_PATH_FILE"
	: >"$CURL_LOG"
	export TEST_ROOT STUB_BIN INSTALL_DIR GITHUB_PATH_FILE CURL_LOG SCRIPT ACTION_DIR
}

teardown() {
	rm -rf "$TEST_ROOT"
}

# Serves both curl call sites in install.sh from files chosen by the caller: METADATA_JSON is
# the release API body, ARCHIVE_FILE the source tarball. Leaving either unset makes that call
# fail the way `curl --fail` does, which is the only way to reach the download-failure
# branches. Every invocation is appended to CURL_LOG so a test can assert the URL and headers
# the script actually sent. ~keep
make_curl_stub() {
	xberg_stub curl '#!/usr/bin/env bash' \
		'url=""' \
		'output=""' \
		'previous=""' \
		'for argument in "$@"; do' \
		'  if [ "$previous" = "--output" ]; then output="$argument"; fi' \
		'  case "$argument" in https://*) url="$argument" ;; esac' \
		'  previous="$argument"' \
		'done' \
		'printf "%s\n" "$@" >>"${CURL_LOG:-/dev/null}"' \
		'case "$url" in' \
		'*api.github.com*)' \
		'  [ -n "${METADATA_JSON:-}" ] || exit 22' \
		'  cat "$METADATA_JSON" >"$output"' \
		'  ;;' \
		'*)' \
		'  [ -n "${ARCHIVE_FILE:-}" ] || exit 22' \
		'  cat "$ARCHIVE_FILE" >"$output"' \
		'  ;;' \
		'esac'
}

# Mirrors sha256_of_tar in install.sh: the digest covers the decompressed tar, and the tool used is
# whichever of the two the host provides. ~keep
# Every path that downloads an archive prints one verification line before its own output. Composing
# it here keeps that sentence in a single place rather than embedded in each expectation. ~keep
verified() {
	printf 'Verified Bats %s against the pinned digest.\n%s' "$1" "$2"
}

tar_digest() {
	if command -v sha256sum >/dev/null 2>&1; then
		gzip -dc "$1" | sha256sum | awk '{ print $1 }'
	else
		gzip -dc "$1" | shasum -a 256 | awk '{ print $1 }'
	fi
}

pin_digest() {
	printf '%s\t%s\n' "$1" "$2" >>"$ACTION_DIR/checksums.tsv"
}

# Pins an archive a test built inline, then echoes its path so it can be used directly as
# ARCHIVE_FILE. Without the pin the run takes the unpinned-version warning branch and the extra
# line breaks the exact-output assertions these tests make. ~keep
serve_archive() {
	pin_digest "$2" "$(tar_digest "$1")"
	printf '%s\n' "$1"
}

write_metadata() {
	local tag="$1"
	local tarball_url="${2:-https://api.github.com/repos/bats-core/bats-core/tarball/${tag}}"
	printf '{"tag_name":"%s","assets":[],"tarball_url":"%s"}\n' "$tag" "$tarball_url" \
		>"$TEST_ROOT/release.json"
	printf '%s\n' "$TEST_ROOT/release.json"
}

# Mirrors the layout of a real bats-core source tarball, symlinked test fixture included.
# Upstream ships ten such symlinks (test/fixtures/parallel, test/fixtures/suite), so keeping one
# here means every happy-path test also proves validate_archive admits in-tree links rather than
# banning links outright. ~keep
make_source_archive() {
	local version="$1"
	local include_bin_bats="${2:-true}"
	local root="$TEST_ROOT/src/bats-core-${version}"

	rm -rf "$TEST_ROOT/src"
	mkdir -p "$root/libexec/bats-core" "$root/test/fixtures"
	printf '%s\n' '#!/bin/sh' "printf '%s\\n' 'Bats ${version}'" >"$root/libexec/bats-core/bats"
	chmod +x "$root/libexec/bats-core/bats"
	if [ "$include_bin_bats" = true ]; then
		mkdir -p "$root/bin"
		printf '%s\n' '#!/bin/sh' "printf '%s\\n' 'Bats ${version}'" >"$root/bin/bats"
		chmod +x "$root/bin/bats"
	fi
	printf '%s\n' '@test "upstream" { true; }' >"$root/test/fixtures/parallel1.bats"
	ln -s parallel1.bats "$root/test/fixtures/parallel2.bats"

	tar -czf "$TEST_ROOT/source.tar.gz" -C "$TEST_ROOT/src" "bats-core-${version}"
	pin_digest "$version" "$(tar_digest "$TEST_ROOT/source.tar.gz")"
	printf '%s\n' "$TEST_ROOT/source.tar.gz"
}

install_existing_bats() {
	local version="$1"
	mkdir -p "$INSTALL_DIR/bats-core-${version}/bin"
	printf '%s\n' '#!/bin/sh' "printf '%s\\n' 'Bats ${version}'" \
		>"$INSTALL_DIR/bats-core-${version}/bin/bats"
	chmod +x "$INSTALL_DIR/bats-core-${version}/bin/bats"
}

@test "install should_return_error_when_requested_version_is_not_a_bats_version" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="nightly" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Invalid Bats version 'nightly'. Use 'latest' or a version such as '1.11.1' or 'v1.11.1'." ]
	[ ! -s "$CURL_LOG" ]
}

@test "install should_return_error_when_requested_version_has_no_minor_component" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Invalid Bats version '1'. Use 'latest' or a version such as '1.11.1' or 'v1.11.1'." ]
	[ ! -s "$CURL_LOG" ]
}

@test "install should_return_error_when_requested_version_contains_a_path_separator" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3/../../etc" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Invalid Bats version '1.2.3/../../etc'. Use 'latest' or a version such as '1.11.1' or 'v1.11.1'." ]
	[ ! -s "$CURL_LOG" ]
}

@test "install should_return_error_when_operating_system_is_unsupported" {
	make_curl_stub
	xberg_stub uname '#!/usr/bin/env bash' 'printf "%s\n" FreeBSD'

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Unsupported operating system: FreeBSD. install-bats supports Linux and macOS only." ]
	[ ! -s "$CURL_LOG" ]
}

@test "install should_return_error_when_curl_is_missing_from_path" {
	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::install-bats requires curl, tar, and python3 on PATH." ]
}

@test "install should_return_error_when_python3_is_missing_from_path" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN_WITHOUT_PYTHON3" INPUT_VERSION="1.2.3" \
		INPUT_INSTALL_DIR="$INSTALL_DIR" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::install-bats requires curl, tar, and python3 on PATH." ]
	[ ! -s "$CURL_LOG" ]
}

@test "install should_return_error_when_github_token_contains_a_newline" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN=$'good\nbad' GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::GITHUB_TOKEN must not contain carriage returns or newlines." ]
	[ ! -s "$CURL_LOG" ]
}

@test "install should_return_error_when_github_token_contains_a_carriage_return" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN=$'good\rbad' GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::GITHUB_TOKEN must not contain carriage returns or newlines." ]
	[ ! -s "$CURL_LOG" ]
}

@test "install should_request_the_tagged_release_endpoint_with_a_bearer_token_when_version_is_pinned" {
	make_curl_stub
	install_existing_bats 1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[[ "$(cat "$CURL_LOG")" == *"https://api.github.com/repos/bats-core/bats-core/releases/tags/v1.2.3"* ]]
	[[ "$(cat "$CURL_LOG")" == *"Authorization: Bearer secret-token"* ]]
}

@test "install should_request_the_latest_release_endpoint_when_version_is_latest" {
	make_curl_stub
	install_existing_bats 1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="latest" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[[ "$(cat "$CURL_LOG")" == *"https://api.github.com/repos/bats-core/bats-core/releases/latest"* ]]
}

# ~keep Deliberately run under /bin/bash, which is 3.2 on a macOS runner: expanding an empty
# array under `set -u` aborts before 4.4, and an unset GITHUB_TOKEN -- reachable through
# `github-token: ""` -- is exactly what leaves auth_args empty.
@test "install should_omit_the_authorization_header_when_no_github_token_is_set" {
	make_curl_stub
	install_existing_bats 1.2.3

	run env -u GITHUB_TOKEN PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" \
		INPUT_INSTALL_DIR="$INSTALL_DIR" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$(grep -c 'Authorization' "$CURL_LOG")" -eq 0 ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$INSTALL_DIR/bats-core-1.2.3/bin" ]
}

# ~keep `"$bats_bin" --version` failing is a `set -e` abort, not a call to error(), so nothing
# chooses the exit status explicitly -- this is the one path where the status comes from the
# failing command itself and has to survive the EXIT cleanup trap.
@test "install should_exit_non_zero_when_set_e_aborts_before_the_cleanup_trap" {
	make_curl_stub
	mkdir -p "$INSTALL_DIR/bats-core-1.2.3/bin"
	printf '%s\n' '#!/bin/sh' 'exit 3' >"$INSTALL_DIR/bats-core-1.2.3/bin/bats"
	chmod +x "$INSTALL_DIR/bats-core-1.2.3/bin/bats"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" /bin/bash "$SCRIPT"

	[ "$status" -eq 3 ]
	[ ! -s "$GITHUB_PATH_FILE" ]
}

@test "install should_return_error_when_release_metadata_request_fails" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Could not retrieve Bats release metadata from GitHub." ]
}

@test "install should_return_error_when_release_metadata_has_no_tag_name" {
	make_curl_stub
	printf '%s\n' '{"assets":[]}' >"$TEST_ROOT/release.json"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="latest" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$TEST_ROOT/release.json" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::GitHub returned an invalid Bats release tag." ]
}

@test "install should_return_error_when_release_tag_is_not_a_version" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="latest" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata nightly)" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::GitHub returned an invalid Bats release tag." ]
}

@test "install should_return_error_when_github_resolves_a_different_tag_than_requested" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="v1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.4)" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::GitHub returned v1.2.4, not the requested Bats release v1.2.3." ]
}

@test "install should_return_error_when_tarball_url_is_not_the_official_repository" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3 https://api.github.com/repos/attacker/bats-core/tarball/v1.2.3)" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Bats release v1.2.3 has invalid source archive metadata." ]
}

@test "install should_return_error_when_release_metadata_has_no_assets_list" {
	make_curl_stub
	printf '%s\n' \
		'{"tag_name":"v1.2.3","tarball_url":"https://api.github.com/repos/bats-core/bats-core/tarball/v1.2.3"}' \
		>"$TEST_ROOT/release.json"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$TEST_ROOT/release.json" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Bats release v1.2.3 has invalid source archive metadata." ]
}

@test "install should_reuse_the_existing_release_without_downloading_an_archive" {
	make_curl_stub
	install_existing_bats 1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" /bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = $'Using existing Bats v1.2.3 at '"$INSTALL_DIR"$'/bats-core-1.2.3/bin/bats\nBats 1.2.3' ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$INSTALL_DIR/bats-core-1.2.3/bin" ]
	[ "$(grep -c 'archive/refs/tags' "$CURL_LOG")" -eq 0 ]
}

@test "install should_download_extract_and_publish_the_release_bin_directory_to_github_path" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$(make_source_archive 1.2.3)" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = "$(verified 1.2.3 "Bats 1.2.3")" ]
	[ -x "$INSTALL_DIR/bats-core-1.2.3/bin/bats" ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$INSTALL_DIR/bats-core-1.2.3/bin" ]
	[[ "$(cat "$CURL_LOG")" == *"https://github.com/bats-core/bats-core/archive/refs/tags/v1.2.3.tar.gz"* ]]
}

@test "install should_install_under_runner_temp_when_no_install_dir_is_given" {
	make_curl_stub
	local runner_temp="$TEST_ROOT/runner"
	mkdir -p "$runner_temp"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" RUNNER_TEMP="$runner_temp" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$(make_source_archive 1.2.3)" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$runner_temp/bats/bats-core-1.2.3/bin" ]
}

@test "install should_return_error_when_the_source_archive_download_fails" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Could not download the official Bats source archive for v1.2.3." ]
}

@test "install should_return_error_when_the_archive_has_an_unexpected_top_level_directory" {
	make_curl_stub
	mkdir -p "$TEST_ROOT/evil/attacker-1.2.3/bin"
	printf '%s\n' '#!/bin/sh' 'exit 0' >"$TEST_ROOT/evil/attacker-1.2.3/bin/bats"
	chmod +x "$TEST_ROOT/evil/attacker-1.2.3/bin/bats"
	tar -czf "$TEST_ROOT/evil.tar.gz" -C "$TEST_ROOT/evil" attacker-1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$TEST_ROOT/evil.tar.gz" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[[ "$output" == *"::error::Downloaded Bats archive has an unexpected top-level path."* ]]
	[ ! -e "$INSTALL_DIR/bats-core-1.2.3" ]
}

@test "install should_return_error_when_the_archive_contains_a_parent_directory_traversal" {
	make_curl_stub
	python3 - "$TEST_ROOT/traversal.tar.gz" <<'PY'
import io
import sys
import tarfile

with tarfile.open(sys.argv[1], "w:gz") as archive:
    for name in ("bats-core-1.2.3/bin/bats", "bats-core-1.2.3/../escape.sh"):
        entry = tarfile.TarInfo(name)
        entry.size = 0
        entry.mode = 0o755
        archive.addfile(entry, io.BytesIO(b""))
PY

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$TEST_ROOT/traversal.tar.gz" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[[ "$output" == *"::error::Downloaded Bats archive contains an unsafe path."* ]]
	[ ! -e "$TEST_ROOT/escape.sh" ]
	[ ! -e "$INSTALL_DIR/escape.sh" ]
}

@test "install should_return_error_when_the_archive_does_not_contain_bin_bats" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$(make_source_archive 1.2.3 false)" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "$(verified 1.2.3 "::error::Downloaded Bats archive does not contain bin/bats.")" ]
	[ ! -e "$INSTALL_DIR/bats-core-1.2.3" ]
}

# ~keep An archive of nothing but regular files and directories is the ordinary case and must
# install. It is asserted separately from the happy-path tests because those go through
# make_source_archive, which deliberately ships a symlink.
@test "install should_accept_a_source_archive_that_contains_no_symlinks" {
	make_curl_stub
	mkdir -p "$TEST_ROOT/clean/bats-core-1.2.3/bin"
	printf '%s\n' '#!/bin/sh' 'exit 0' >"$TEST_ROOT/clean/bats-core-1.2.3/bin/bats"
	chmod +x "$TEST_ROOT/clean/bats-core-1.2.3/bin/bats"
	tar -czf "$TEST_ROOT/clean.tar.gz" -C "$TEST_ROOT/clean" bats-core-1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$TEST_ROOT/clean.tar.gz" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$INSTALL_DIR/bats-core-1.2.3/bin" ]
}

# ~keep The guard exists to stop extraction-time path traversal, not to ban symlinks: upstream
# bats-core ships ten of them under test/fixtures/, so a blanket rejection would reject every
# real release. These two cases are the line between them.
@test "install should_accept_a_source_archive_whose_symlinks_stay_inside_the_archive" {
	make_curl_stub
	mkdir -p "$TEST_ROOT/intree/bats-core-1.2.3/bin" "$TEST_ROOT/intree/bats-core-1.2.3/test/fixtures"
	printf '%s\n' '#!/bin/sh' 'exit 0' >"$TEST_ROOT/intree/bats-core-1.2.3/bin/bats"
	chmod +x "$TEST_ROOT/intree/bats-core-1.2.3/bin/bats"
	printf '%s\n' '@test "upstream" { true; }' >"$TEST_ROOT/intree/bats-core-1.2.3/test/fixtures/one.bats"
	ln -s one.bats "$TEST_ROOT/intree/bats-core-1.2.3/test/fixtures/two.bats"
	ln -s ../fixtures/one.bats "$TEST_ROOT/intree/bats-core-1.2.3/test/fixtures/three.bats"
	tar -czf "$TEST_ROOT/intree.tar.gz" -C "$TEST_ROOT/intree" bats-core-1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$TEST_ROOT/intree.tar.gz" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$(cat "$GITHUB_PATH_FILE")" = "$INSTALL_DIR/bats-core-1.2.3/bin" ]
}

@test "install should_return_error_when_a_symlink_target_climbs_out_of_the_archive" {
	make_curl_stub
	mkdir -p "$TEST_ROOT/escape/bats-core-1.2.3/bin"
	printf '%s\n' '#!/bin/sh' 'exit 0' >"$TEST_ROOT/escape/bats-core-1.2.3/bin/bats"
	chmod +x "$TEST_ROOT/escape/bats-core-1.2.3/bin/bats"
	ln -s ../../../../etc/passwd "$TEST_ROOT/escape/bats-core-1.2.3/bin/escape"
	tar -czf "$TEST_ROOT/escape.tar.gz" -C "$TEST_ROOT/escape" bats-core-1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$(serve_archive "$TEST_ROOT/escape.tar.gz" 1.2.3)" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "$(verified 1.2.3 "::error::Downloaded Bats archive links outside itself: 'bats-core-1.2.3/bin/escape' -> '../../../../etc/passwd'.")" ]
	[ ! -e "$INSTALL_DIR/bats-core-1.2.3" ]
}

@test "install should_return_error_when_a_symlink_target_is_absolute" {
	make_curl_stub
	mkdir -p "$TEST_ROOT/absolute/bats-core-1.2.3/bin"
	printf '%s\n' '#!/bin/sh' 'exit 0' >"$TEST_ROOT/absolute/bats-core-1.2.3/bin/bats"
	chmod +x "$TEST_ROOT/absolute/bats-core-1.2.3/bin/bats"
	ln -s /etc/passwd "$TEST_ROOT/absolute/bats-core-1.2.3/bin/escape"
	tar -czf "$TEST_ROOT/absolute.tar.gz" -C "$TEST_ROOT/absolute" bats-core-1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$(serve_archive "$TEST_ROOT/absolute.tar.gz" 1.2.3)" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "$(verified 1.2.3 "::error::Downloaded Bats archive links outside itself: 'bats-core-1.2.3/bin/escape' -> '/etc/passwd'.")" ]
	[ ! -e "$INSTALL_DIR/bats-core-1.2.3" ]
}

@test "install should_return_error_when_the_archive_contains_a_special_file" {
	make_curl_stub
	mkdir -p "$TEST_ROOT/special/bats-core-1.2.3/bin"
	printf '%s\n' '#!/bin/sh' 'exit 0' >"$TEST_ROOT/special/bats-core-1.2.3/bin/bats"
	chmod +x "$TEST_ROOT/special/bats-core-1.2.3/bin/bats"
	mkfifo "$TEST_ROOT/special/bats-core-1.2.3/pipe"
	tar -czf "$TEST_ROOT/special.tar.gz" -C "$TEST_ROOT/special" bats-core-1.2.3

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$(serve_archive "$TEST_ROOT/special.tar.gz" 1.2.3)" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "$(verified 1.2.3 "::error::Downloaded Bats archive contains an unsupported special-file entry: 'bats-core-1.2.3/pipe'.")" ]
	[ ! -e "$INSTALL_DIR/bats-core-1.2.3" ]
}

@test "install should_return_error_when_the_release_directory_exists_without_an_executable_bats" {
	make_curl_stub
	mkdir -p "$INSTALL_DIR/bats-core-1.2.3/bin"
	printf '%s\n' 'not executable' >"$INSTALL_DIR/bats-core-1.2.3/bin/bats"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$(make_source_archive 1.2.3)" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "$(verified 1.2.3 "::error::Installation directory already exists but does not contain an executable Bats binary: ${INSTALL_DIR}/bats-core-1.2.3.")" ]
	[ "$(cat "$INSTALL_DIR/bats-core-1.2.3/bin/bats")" = "not executable" ]
}

@test "install should_return_error_when_github_path_is_not_set" {
	make_curl_stub
	install_existing_bats 1.2.3

	run env -u GITHUB_PATH PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" \
		INPUT_INSTALL_DIR="$INSTALL_DIR" GITHUB_TOKEN="secret-token" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" /bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "${lines[2]}" = "::error::GITHUB_PATH is not set; install-bats must run in a GitHub Actions job." ]
}

@test "install should_remove_the_staging_directory_when_the_run_fails" {
	make_curl_stub

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_TOKEN="secret-token" GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$(find "$INSTALL_DIR" -maxdepth 1 -name '.install-bats-*' | wc -l | tr -d ' ')" = "0" ]
}

# ~keep The matching-digest success path is already asserted by
# should_download_extract_and_publish_the_release_bin_directory_to_github_path, which runs against a
# table make_source_archive pinned. The cases below cover what that one cannot: a mismatch, an
# unlisted version, a missing table, the table's own parsing, and what the digest is taken over.

@test "install should_return_error_when_the_archive_digest_does_not_match_the_pin" {
	make_curl_stub
	local archive
	archive="$(make_source_archive 1.2.3)"
	# Repin to a digest no archive can have, leaving the downloaded bytes untouched -- so the run
	# fails on the comparison rather than on anything structural. ~keep
	printf '%s\t%s\n' 1.2.3 "0000000000000000000000000000000000000000000000000000000000000000" >"$ACTION_DIR/checksums.tsv"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$archive" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[[ "$output" == "::error::Bats 1.2.3 archive digest mismatch: "* ]]
	[ ! -e "$INSTALL_DIR/bats-core-1.2.3" ]
}

@test "install should_name_both_digests_when_it_refuses_an_archive" {
	make_curl_stub
	local archive actual
	archive="$(make_source_archive 1.2.3)"
	actual="$(tar_digest "$archive")"
	printf '%s\t%s\n' 1.2.3 "0000000000000000000000000000000000000000000000000000000000000000" >"$ACTION_DIR/checksums.tsv"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$archive" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[ "$output" = "::error::Bats 1.2.3 archive digest mismatch: expected 0000000000000000000000000000000000000000000000000000000000000000, got ${actual}." ]
}

@test "install should_warn_rather_than_fail_when_the_version_is_absent_from_the_table" {
	make_curl_stub
	local archive
	archive="$(make_source_archive 1.2.3)"
	# A table that parses but does not list this version. `latest` and any release newer than the
	# committed table land here, so it has to install rather than abort. ~keep
	printf '# only a comment\n' >"$ACTION_DIR/checksums.tsv"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$archive" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[[ "$output" == "::warning::Bats 1.2.3 is not in install-bats/checksums.tsv;"* ]]
	[ -x "$INSTALL_DIR/bats-core-1.2.3/bin/bats" ]
}

@test "install should_return_error_when_the_checksum_table_is_missing_entirely" {
	make_curl_stub
	local archive
	archive="$(make_source_archive 1.2.3)"
	# A missing table is a broken action, not an unpinned version: it must not degrade into the
	# warning path, which would report success having verified nothing at all. ~keep
	rm -f "$ACTION_DIR/checksums.tsv"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$archive" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 1 ]
	[[ "$output" == "::error::Checksum table is missing: "* ]]
	[ ! -e "$INSTALL_DIR/bats-core-1.2.3" ]
}

@test "install should_ignore_comment_and_blank_lines_when_reading_the_table" {
	make_curl_stub
	local archive digest
	archive="$(make_source_archive 1.2.3)"
	digest="$(tar_digest "$archive")"
	printf '# leading comment\n\n   \n%s\t%s\n' 1.2.3 "$digest" >"$ACTION_DIR/checksums.tsv"

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$archive" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = "$(verified 1.2.3 "Bats 1.2.3")" ]
}

@test "install should_verify_the_tar_payload_rather_than_the_compressed_bytes" {
	make_curl_stub
	local archive recompressed
	archive="$(make_source_archive 1.2.3)"
	# GitHub does not promise stable compressed bytes -- its January 2023 gzip change altered the
	# checksum of every source archive on the platform with no repository content changing.
	# Recompressing at a different level reproduces exactly that: different .tar.gz, identical tar.
	# The pin must survive it, or every stored digest rots on the next such change. ~keep
	recompressed="$TEST_ROOT/recompressed.tar.gz"
	gzip -dc "$archive" | gzip -9 -c >"$recompressed"
	[ "$(cksum <"$archive" | awk '{ print $1 }')" != "$(cksum <"$recompressed" | awk '{ print $1 }')" ]

	run env PATH="$STUB_BIN:$SYS_BIN" INPUT_VERSION="1.2.3" INPUT_INSTALL_DIR="$INSTALL_DIR" \
		GITHUB_PATH="$GITHUB_PATH_FILE" CURL_LOG="$CURL_LOG" \
		METADATA_JSON="$(write_metadata v1.2.3)" ARCHIVE_FILE="$recompressed" \
		/bin/bash "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$output" = "$(verified 1.2.3 "Bats 1.2.3")" ]
}
