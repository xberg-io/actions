#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN" "$ROOT/licenses"
	export PATH="$BIN:$PATH" GITHUB_WORKSPACE="$ROOT" GITHUB_OUTPUT="$ROOT/out" CARGO_TARGET_DIR="$ROOT/target"
	export INPUT_CRATE_NAME=my-crate INPUT_LIB_NAME=my_lib INPUT_ARTIFACT_NAME=Kit INPUT_OUTPUT_DIR="$ROOT/dist"
	export INPUT_INCLUDE_MACOS_X86_64=false INPUT_INCLUDE_IOS_X86_64=false INPUT_PREBUILT_LIBS_DIR="$ROOT/prebuilt"
	export INPUT_ADDITIONAL_LICENSE_FILES=$'THIRD_PARTY_LICENSES.md\nlicenses/NOTICE.txt\n'
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/build.sh"
	NOTICES="$BATS_TEST_DIRNAME/../scripts/notices.py"
	for triple in aarch64-apple-darwin aarch64-apple-ios aarch64-apple-ios-sim aarch64-unknown-linux-gnu x86_64-unknown-linux-gnu; do
		mkdir -p "$INPUT_PREBUILT_LIBS_DIR/$triple"
		printf 'static fixture %s\n' "$triple" >"$INPUT_PREBUILT_LIBS_DIR/$triple/libmy_lib.a"
	done
	printf 'Copyright\r\nFull conditions and disclaimer\n' >"$ROOT/THIRD_PARTY_LICENSES.md"
	printf 'Nested notice\r\n\377\000\n' >"$ROOT/licenses/NOTICE.txt"
	xberg_stub cargo 'echo "unexpected cargo invocation" >&2; exit 97'
	xberg_stub rustup 'echo "unexpected rustup invocation" >&2; exit 97'
	xberg_stub swift 'exit 1'
}

@test "should_embed_required_notice_bytes_in_the_real_zip_before_checksum" {
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	python3 - "$ROOT" <<'PY'
import hashlib
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
archive = root / "dist/Kit.artifactbundle.zip"
with zipfile.ZipFile(archive) as zipped:
    names = [entry.filename for entry in zipped.infolist() if not entry.is_dir()]
    assert len(names) == len(set(names)) == 8, names
    for name in ["THIRD_PARTY_LICENSES.md", "licenses/NOTICE.txt"]:
        assert zipped.read(f"Kit.artifactbundle/{name}") == (root / name).read_bytes()
outputs = (root / "out").read_text().splitlines()
assert f"checksum={hashlib.sha256(archive.read_bytes()).hexdigest()}" in outputs
PY
	[[ "$output" == *"Verified 2 additional license files"* ]]
}

@test "should_preserve_empty_input_bundle_contents_without_requiring_notices" {
	export INPUT_ADDITIONAL_LICENSE_FILES=''
	rm "$ROOT/THIRD_PARTY_LICENSES.md" "$ROOT/licenses/NOTICE.txt"
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	python3 - "$ROOT/dist/Kit.artifactbundle.zip" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as zipped:
    files = [entry.filename for entry in zipped.infolist() if not entry.is_dir()]
    assert len(files) == 6, files
    assert all("NOTICE" not in name and "LICENSE" not in name for name in files)
PY
}

@test "should_reject_missing_empty_escaping_and_duplicate_notice_inputs_before_assembly" {
	touch "$ROOT/empty.txt"
	for input in missing.txt empty.txt ../outside.txt /absolute.txt 'licenses/../THIRD_PARTY_LICENSES.md' $'THIRD_PARTY_LICENSES.md\nTHIRD_PARTY_LICENSES.md' $'THIRD_PARTY_LICENSES.md\nthird_party_licenses.md'; do
		export INPUT_ADDITIONAL_LICENSE_FILES="$input"
		run /bin/bash "$SCRIPT"
		[ "$status" -eq 1 ]
		[[ "$output" == *"additional license"* ]]
		[ ! -e "$ROOT/dist/Kit.artifactbundle.zip" ]
		[ ! -e "$ROOT/dist/Kit.artifactbundle" ]
	done
}

@test "should_reject_notice_symlinks_resolving_outside_the_caller_workspace" {
	printf outside >"$BATS_TEST_TMPDIR/outside.txt"
	ln -s "$BATS_TEST_TMPDIR/outside.txt" "$ROOT/escape.txt"
	export INPUT_ADDITIONAL_LICENSE_FILES=escape.txt
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"escapes workspace"* ]]
	[ ! -e "$ROOT/dist/Kit.artifactbundle.zip" ]
}

@test "should_reject_collisions_with_generated_metadata_and_case_aliased_native_directories" {
	printf 'metadata collision' >"$ROOT/info.json"
	mkdir -p "$ROOT/kit-linux-aarch64"
	printf 'directory collision' >"$ROOT/kit-linux-aarch64/NOTICE.txt"
	for input in info.json kit-linux-aarch64/NOTICE.txt; do
		export INPUT_ADDITIONAL_LICENSE_FILES="$input"
		run /bin/bash "$SCRIPT"
		[ "$status" -eq 1 ]
		[[ "$output" == *"collision"* ]]
		[ ! -e "$ROOT/dist/Kit.artifactbundle.zip" ]
	done
}

@test "should_reject_corrupted_notice_bytes_in_an_actual_zip" {
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	python3 - "$ROOT/dist/Kit.artifactbundle.zip" <<'PY'
import sys
import zipfile

archive = sys.argv[1]
with zipfile.ZipFile(archive) as zipped:
    entries = [(entry, zipped.read(entry)) for entry in zipped.infolist()]
with zipfile.ZipFile(archive, "w") as zipped:
    for entry, data in entries:
        zipped.writestr(entry, b"corrupted" if entry.filename.endswith("/licenses/NOTICE.txt") else data)
PY
	run python3 "$NOTICES" verify "$ROOT" --bundle "$ROOT/dist/Kit.artifactbundle" --archive "$ROOT/dist/Kit.artifactbundle.zip"
	[ "$status" -eq 1 ]
	[[ "$output" == *"contents differ"*"licenses/NOTICE.txt"* ]]
}

@test "should_reject_zip_verification_that_finds_zero_required_notice_entries" {
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	python3 - "$ROOT/dist/Kit.artifactbundle.zip" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1], "w") as zipped:
    zipped.writestr("Kit.artifactbundle/info.json", "{}")
PY
	run python3 "$NOTICES" verify "$ROOT" --bundle "$ROOT/dist/Kit.artifactbundle" --archive "$ROOT/dist/Kit.artifactbundle.zip"
	[ "$status" -eq 1 ]
	[[ "$output" == *"expected exactly one ZIP entry"*"found 0"* ]]
}

@test "should_describe_notices_during_dry_run_without_reading_missing_sources" {
	export INPUT_DRY_RUN=true INPUT_ADDITIONAL_LICENSE_FILES=missing.txt
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"would copy additional license files"*"missing.txt"* ]]
	[ ! -e "$ROOT/dist" ]
}

@test "should_stage_only_libraries_in_split_build_mode" {
	unset INPUT_PREBUILT_LIBS_DIR
	export INPUT_TARGETS=aarch64-apple-darwin
	xberg_stub rustup 'exit 0'
	xberg_stub cargo 'target="${@: -1}"; mkdir -p "$CARGO_TARGET_DIR/$target/release"; printf archive >"$CARGO_TARGET_DIR/$target/release/libmy_lib.a"'
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 0 ]
	[ -s "$ROOT/dist/libs/aarch64-apple-darwin/libmy_lib.a" ]
	[ ! -e "$ROOT/dist/Kit.artifactbundle" ]
	[ ! -e "$ROOT/dist/Kit.artifactbundle.zip" ]
}

@test "should_reject_explicit_whitespace_only_notice_configuration" {
	export INPUT_ADDITIONAL_LICENSE_FILES=$' \n\t\n'
	run /bin/bash "$SCRIPT"
	[ "$status" -eq 1 ]
	[[ "$output" == *"additional license configuration contains no file paths"* ]]
	[ ! -e "$ROOT/dist" ]
}
