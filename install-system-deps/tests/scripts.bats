#!/usr/bin/env bats

setup_file() {
	bats_load_library xberg-bats
	xberg_shadow_system_path_without cmake
}

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="$TEST_ROOT/bin"
	mkdir -p "$STUB_BIN"
	export TEST_ROOT STUB_BIN
}

teardown() {
	rm -rf "$TEST_ROOT"
}

make_stub() {
	local name="$1"
	shift
	printf '%s\n' "$@" >"$STUB_BIN/$name"
	chmod +x "$STUB_BIN/$name"
}

@test "detect-tesseract-linux should_write_candidate_patch_version_to_github_output" {
	make_stub apt-cache '#!/usr/bin/env bash' \
		'printf "%s\n" "Candidate: 5.4.1-1build1"'
	local output_file="$TEST_ROOT/github-output"

	run env PATH="$STUB_BIN:/usr/bin:/bin" GITHUB_OUTPUT="$output_file" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/detect-tesseract-linux.sh"

	[ "$status" -eq 0 ]
	[ "$(cat "$output_file")" = "version=5.4.1" ]
	[ "$output" = "::notice title=Tesseract Version::Detected version: 5.4.1" ]
}

@test "detect-tesseract-linux should_write_unknown_when_package_cache_has_no_candidate" {
	make_stub apt-cache '#!/usr/bin/env bash' 'exit 0'
	local output_file="$TEST_ROOT/github-output"

	run env PATH="$STUB_BIN:/usr/bin:/bin" GITHUB_OUTPUT="$output_file" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/detect-tesseract-linux.sh"

	[ "$status" -eq 0 ]
	[ "$(cat "$output_file")" = "version=unknown" ]
	[ "$output" = "::notice title=Tesseract Version::Detected version: unknown" ]
}

@test "detect-tesseract-macos should_prefer_json_stable_version" {
	make_stub brew '#!/usr/bin/env bash' \
		'printf "%s\n" "{\"formulae\":[{\"versions\":{\"stable\":\"5.5.0\"}}]}"'
	local output_file="$TEST_ROOT/github-output"

	run env PATH="$STUB_BIN:/usr/bin:/bin" GITHUB_OUTPUT="$output_file" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/detect-tesseract-macos.sh"

	[ "$status" -eq 0 ]
	[ "$(cat "$output_file")" = "version=5.5.0" ]
	[ "$output" = "::notice title=Tesseract Version::Detected version: 5.5.0" ]
}

@test "detect-tesseract-macos should_fall_back_to_human_readable_brew_info" {
	make_stub brew '#!/usr/bin/env bash' \
		'if [ "$1" = "info" ] && [ "$2" = "--json=v2" ]; then exit 0; fi' \
		'printf "%s\n" "tesseract: stable 5.4.1 (bottled)"'
	local output_file="$TEST_ROOT/github-output"

	run env PATH="$STUB_BIN:/usr/bin:/bin" GITHUB_OUTPUT="$output_file" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/detect-tesseract-macos.sh"

	[ "$status" -eq 0 ]
	[ "$(cat "$output_file")" = "version=5.4.1" ]
	[ "$output" = "::notice title=Tesseract Version::Detected version: 5.4.1" ]
}

@test "retry should_return_one_after_three_failed_attempts" {
	make_stub sleep '#!/usr/bin/env bash' 'exit 0'

	run env PATH="$STUB_BIN:/usr/bin:/bin" /bin/bash -c \
		'source "$1"; failure_count=0; fail() { failure_count=$((failure_count + 1)); return 42; }; retry_with_backoff fail; exit $?' \
		_ "$BATS_TEST_DIRNAME/../scripts/retry.sh"

	[ "$status" -eq 1 ]
	[ "$output" = $'⚠ Attempt 1 failed, retrying in 5s...\n⚠ Attempt 2 failed, retrying in 10s...' ]
}

@test "retry should_return_success_when_command_succeeds_on_second_attempt" {
	make_stub sleep '#!/usr/bin/env bash' 'exit 0'

	run env PATH="$STUB_BIN:/usr/bin:/bin" /bin/bash -c \
		'source "$1"; invocation_count=0; eventually() { invocation_count=$((invocation_count + 1)); [ "$invocation_count" -eq 2 ]; }; retry_with_backoff eventually; printf "attempts=%s\n" "$invocation_count"' \
		_ "$BATS_TEST_DIRNAME/../scripts/retry.sh"

	[ "$status" -eq 0 ]
	[ "$output" = $'⚠ Attempt 1 failed, retrying in 5s...\nattempts=2' ]
}

@test "install-linux should_fail_when_cmake_is_unavailable_after_safe_package_attempts" {
	make_stub sudo '#!/usr/bin/env bash' \
		'printf "sudo %s\n" "$*" >>"$COMMAND_LOG"' \
		'exit 0'
	make_stub dpkg '#!/usr/bin/env bash' 'exit 0'
	make_stub pkg-config '#!/usr/bin/env bash' 'printf "%s\n" "1.23.7"'
	make_stub ldconfig '#!/usr/bin/env bash' 'exit 0'
	make_stub apt-cache '#!/usr/bin/env bash' 'exit 1'
	local prefix="$TEST_ROOT/libheif"
	mkdir -p "$prefix/lib/pkgconfig"
	: >"$prefix/lib/pkgconfig/libheif.pc"
	local command_log="$TEST_ROOT/commands"

	run env PATH="$STUB_BIN:$XBERG_SYS_BIN" GITHUB_ACTION= COMMAND_LOG="$command_log" LIBHEIF_PREFIX="$prefix" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/install-linux.sh"

	[ "$status" -eq 1 ]
	[[ "$output" == *"✓ libheif 1.23.7 already installed (cached)"* ]]
	[[ "$output" == *"::error::CMake not found after installation"* ]]
	[ "$(sed -n '1p' "$command_log")" = "sudo apt-get update" ]
	[ "$(sed -n '2p' "$command_log")" = "sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-tur tesseract-ocr-deu tesseract-ocr-kor tesseract-ocr-jpn-vert libtesseract-dev libleptonica-dev fonts-liberation fonts-dejavu-core fonts-noto-core libssl-dev pkg-config build-essential python3 libpng-dev libjpeg-dev libtiff-dev libgif-dev libwebp-dev libopenjp2-7-dev libarchive-dev libcurl4-openssl-dev patchelf cmake libmagic-dev libuv1-dev libde265-dev libaom-dev libx265-dev libdav1d-dev libnuma-dev libboost-dev zlib1g-dev liblzma-dev libbz2-dev" ]
}

@test "install-macos should_fail_after_retrying_required_cmake_installation" {
	# ~keep install-macos.sh probes absolute macOS paths -- /opt/homebrew/bin and
	# /usr/local/bin -- to decide what it appends to GITHUB_PATH, and those cannot be stubbed
	# out of an absolute lookup. On a Linux runner neither exists, GITHUB_PATH stays empty and
	# the assertion below fails; the script simply has nothing to assert there. Skipping is
	# honest, running it on Linux was not.
	[ "$(uname -s)" = "Darwin" ] || skip "install-macos.sh only has observable behaviour on macOS"
	make_stub brew '#!/usr/bin/env bash' \
		'if [ "$1" = "list" ]; then exit 1; fi' \
		'if [ "$1" = "install" ] && [ "$2" = "cmake" ]; then exit 1; fi' \
		'exit 0'
	make_stub sleep '#!/usr/bin/env bash' 'exit 0'
	local github_path="$TEST_ROOT/github-path"
	local github_env="$TEST_ROOT/github-env"
	local bash_env="$TEST_ROOT/bash-env"
	: >"$github_path"
	: >"$github_env"
	printf '%s\n' \
		'brew() {' \
		'  if [ "$1" = "list" ]; then return 1; fi' \
		'  if [ "$1" = "install" ] && [ "$2" = "cmake" ]; then return 1; fi' \
		'  return 0' \
		'}' >"$bash_env"

	run env PATH="$STUB_BIN:/usr/bin:/bin" BASH_ENV="$bash_env" GITHUB_ENV="$github_env" GITHUB_PATH="$github_path" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/install-macos.sh"

	[ "$status" -eq 1 ]
	[[ "$output" == *"Installing CMake..."* ]]
	[[ "$output" == *"::error::Failed to install CMake after retries"* ]]
	[[ "$output" == *"⚠ Attempt 2 failed, retrying in 10s..."* ]]
	[ "$(cat "$github_path")" = $'/opt/homebrew/bin\n/opt/homebrew/sbin\n/usr/local/bin\n/usr/local/sbin' ]
}

@test "install-macos should_verify_available_dependencies_and_export_cmake_location" {
	# ~keep install-macos.sh probes absolute macOS paths -- /opt/homebrew/bin and
	# /usr/local/bin -- to decide what it appends to GITHUB_PATH, and those cannot be stubbed
	# out of an absolute lookup. On a Linux runner neither exists, GITHUB_PATH stays empty and
	# the assertion below fails; the script simply has nothing to assert there. Skipping is
	# honest, running it on Linux was not.
	[ "$(uname -s)" = "Darwin" ] || skip "install-macos.sh only has observable behaviour on macOS"
	local github_path="$TEST_ROOT/github-path"
	local github_env="$TEST_ROOT/github-env"
	local bash_env="$TEST_ROOT/bash-env"
	: >"$github_path"
	: >"$github_env"
	printf '%s\n' \
		'brew() { [ "$1" = "list" ] && return 0; return 0; }' \
		'cmake() { printf "%s\n" "cmake version 3.30.0"; }' \
		'tesseract() { if [ "$1" = "--version" ]; then printf "%s\n" "tesseract 5.5.4" " leptonica-1.87.0"; else printf "%s\n" "eng"; fi; }' \
		'pkg-config() { case "${2:-}" in tesseract) echo 5.5.4 ;; lept) echo 1.87.0 ;; *) echo 2.3.0 ;; esac; }' \
		'php() { printf "%s\n" "PHP 8.4.0"; }' >"$bash_env"

	run env PATH="$STUB_BIN:/usr/bin:/bin" BASH_ENV="$bash_env" GITHUB_ENV="$github_env" GITHUB_PATH="$github_path" \
		/bin/bash "$BATS_TEST_DIRNAME/../scripts/install-macos.sh"

	[ "$status" -eq 0 ]
	[[ "$output" == *"✓ CMake already installed"* ]]
	[[ "$output" == *"✓ Tesseract language packs already installed"* ]]
	[[ "$output" == *"✓ pkg-config available"* ]]
	[ "$(cat "$github_env")" = "CMAKE=cmake" ]
	[ "$(tail -n 1 "$github_path")" = "." ]
}
