#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/unix.sh"
	REAL_PYTHON="$(command -v python3)"
	export REAL_PYTHON
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN"
	export PATH="$BIN:$PATH"
	export RUNNER_TEMP="$BATS_TEST_TMPDIR/tmp"
	export GITHUB_PATH="$BATS_TEST_TMPDIR/github-path"
	export ZIG_FIXTURE_INDEX="$BATS_TEST_TMPDIR/index.json"
	export ZIG_FIXTURE_ARCHIVE="$BATS_TEST_TMPDIR/archive"
	export ZIG_EXTRACT_TRACE="$BATS_TEST_TMPDIR/extraction"
	mkdir -p "$RUNNER_TEMP"
	: >"$GITHUB_PATH"
}

fixture() {
	printf 'synthetic-archive\n' >"$ZIG_FIXTURE_ARCHIVE"
	"$REAL_PYTHON" - "$1" "$ZIG_FIXTURE_ARCHIVE" "$ZIG_FIXTURE_INDEX" <<'PY'
import hashlib
import json
import pathlib
import sys

mode, archive, output = sys.argv[1:]
raw = pathlib.Path(archive).read_bytes()
asset = {"tarball": "https://example.test/zig-0.14.0.tar.xz", "shasum": hashlib.sha256(raw).hexdigest(), "size": str(len(raw))}
if mode == "wrong-digest":
    asset["shasum"] = "0" * 64
elif mode == "missing-digest":
    del asset["shasum"]
elif mode == "malformed-digest":
    asset["shasum"] = "not-a-sha256"
elif mode == "wrong-size":
    asset["size"] = str(len(raw) + 1)
elif mode == "missing-size":
    del asset["size"]
elif mode == "malformed-size":
    asset["size"] = "not-a-size"
index = {"0.14.0": {"x86_64-linux": asset}, "master": {"version": "0.14.0", "x86_64-linux": asset}}
pathlib.Path(output).write_text(json.dumps(index))
PY
	cat >"$BATS_TEST_TMPDIR/python-wrapper.py" <<'PY'
import io
import os
import pathlib
import sys
import urllib.request

urllib.request.urlopen = lambda *args, **kwargs: io.BytesIO(pathlib.Path(os.environ["ZIG_FIXTURE_INDEX"]).read_bytes())
sys.argv = sys.argv[1:]
exec(compile(sys.stdin.read(), "installer-stdin", "exec"))
PY
	xberg_stub uname 'set -eu' '[[ "$1" == "-s" ]] && echo Linux || echo x86_64'
	xberg_stub python3 'set -eu' 'exec "$REAL_PYTHON" "$BATS_TEST_TMPDIR/python-wrapper.py" "$@"'
	xberg_stub curl 'set -eu' 'while [[ "$1" != "--output" ]]; do shift; done; cp "$ZIG_FIXTURE_ARCHIVE" "$2"'
	xberg_stub tar 'set -eu' 'echo extract >>"$ZIG_EXTRACT_TRACE"; while [[ "$1" != "-C" ]]; do shift; done; mkdir -p "$2/zig-0.14.0"; printf "%s\n" "#!/usr/bin/env bash" "echo 0.14.0" >"$2/zig-0.14.0/zig"; chmod +x "$2/zig-0.14.0/zig"'
}

@test "should_install_resolved_zig_archive_and_publish_executable_directory" {
	fixture valid
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -eq 0 ]
	[ "$output" = $'Resolved Zig 0.14.0 -> 0.14.0\nDownloading https://example.test/zig-0.14.0.tar.xz\n0.14.0' ]
	installed="$(cat "$GITHUB_PATH")"
	[[ "$installed" == "$RUNNER_TEMP/zig/toolchain."*/zig-0.14.0 ]]
	[ "$("$installed/zig" version)" = 0.14.0 ]
	[ "$(cat "$ZIG_EXTRACT_TRACE")" = extract ]
}

@test "should_reject_wrong_archive_digest_before_extraction_or_path_update" {
	fixture wrong-digest
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -ne 0 ]
	[[ "$output" == *"Zig archive SHA-256 mismatch"* ]]
	[ ! -e "$ZIG_EXTRACT_TRACE" ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_reject_missing_digest_before_extraction_or_path_update" {
	fixture missing-digest
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -ne 0 ]
	[[ "$output" == *"Missing or malformed checksum/size"* ]]
	[ ! -e "$ZIG_EXTRACT_TRACE" ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_reject_malformed_digest_before_extraction_or_path_update" {
	fixture malformed-digest
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -ne 0 ]
	[[ "$output" == *"Missing or malformed checksum/size"* ]]
	[ ! -e "$ZIG_EXTRACT_TRACE" ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_reject_wrong_archive_size_before_extraction_or_path_update" {
	fixture wrong-size
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -ne 0 ]
	[[ "$output" == *"Zig archive size mismatch"* ]]
	[ ! -e "$ZIG_EXTRACT_TRACE" ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_reject_missing_size_before_extraction_or_path_update" {
	fixture missing-size
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -ne 0 ]
	[[ "$output" == *"Missing or malformed checksum/size"* ]]
	[ ! -e "$ZIG_EXTRACT_TRACE" ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_reject_malformed_size_before_extraction_or_path_update" {
	fixture malformed-size
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -ne 0 ]
	[[ "$output" == *"Missing or malformed checksum/size"* ]]
	[ ! -e "$ZIG_EXTRACT_TRACE" ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_keep_latest_and_master_resolution_compatible" {
	fixture valid
	for requested in latest master; do
		run /bin/bash "$SCRIPT" "$requested"
		[ "$status" -eq 0 ]
		[[ "$output" == *"Resolved Zig $requested -> 0.14.0"* ]]
	done
}

@test "should_select_the_downloaded_release_instead_of_a_stale_install_directory" {
	fixture valid
	mkdir -p "$RUNNER_TEMP/zig/zig-0.12.0"
	printf '#!/bin/sh\necho 0.12.0\n' >"$RUNNER_TEMP/zig/zig-0.12.0/zig"
	chmod +x "$RUNNER_TEMP/zig/zig-0.12.0/zig"
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -eq 0 ]
	installed="$(cat "$GITHUB_PATH")"
	[[ "$installed" == "$RUNNER_TEMP/zig/toolchain."*/zig-0.14.0 ]]
	[ "$("$installed/zig" version)" = 0.14.0 ]
}

@test "should_return_error_when_operating_system_is_unsupported" {
	xberg_stub uname 'set -eu' 'echo Plan9'
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[ "$output" = "Unsupported OS: Plan9" ]
}

@test "should_reject_an_extracted_executable_reporting_the_wrong_version_before_path_update" {
	fixture valid
	xberg_stub tar 'set -eu' 'echo extract >>"$ZIG_EXTRACT_TRACE"; while [[ "$1" != "-C" ]]; do shift; done; mkdir -p "$2/zig-0.14.0"; printf "%s\n" "#!/usr/bin/env bash" "echo 0.13.0" >"$2/zig-0.14.0/zig"; chmod +x "$2/zig-0.14.0/zig"'
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -ne 0 ]
	[[ "$output" == *"Expected Zig 0.14.0, found 0.13.0"* ]]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_not_publish_a_path_when_the_extracted_executable_fails_its_version_probe" {
	fixture valid
	xberg_stub tar 'set -eu' 'echo extract >>"$ZIG_EXTRACT_TRACE"; while [[ "$1" != "-C" ]]; do shift; done; mkdir -p "$2/zig-0.14.0"; printf "%s\n" "#!/usr/bin/env bash" "exit 94" >"$2/zig-0.14.0/zig"; chmod +x "$2/zig-0.14.0/zig"'
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -eq 94 ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "should_reject_missing_archive_executable_instead_of_reusing_a_same_named_stale_install" {
	fixture valid
	mkdir -p "$RUNNER_TEMP/zig/zig-0.14.0"
	printf '#!/bin/sh\necho 0.14.0\n' >"$RUNNER_TEMP/zig/zig-0.14.0/zig"
	chmod +x "$RUNNER_TEMP/zig/zig-0.14.0/zig"
	xberg_stub tar 'set -eu' 'echo extract >>"$ZIG_EXTRACT_TRACE"; while [[ "$1" != "-C" ]]; do shift; done; mkdir -p "$2/zig-0.14.0"'
	run /bin/bash "$SCRIPT" 0.14.0
	[ "$status" -eq 1 ]
	[[ "$output" == *"Could not locate extracted zig directory"* ]]
	[ ! -s "$GITHUB_PATH" ]
	[ "$("$RUNNER_TEMP/zig/zig-0.14.0/zig" version)" = 0.14.0 ]
}
