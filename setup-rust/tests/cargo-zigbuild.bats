#!/usr/bin/env bats

setup() {
	script="$BATS_TEST_DIRNAME/../scripts/install-cargo-zigbuild.sh"
	export RUNNER_TEMP="$BATS_TEST_TMPDIR/runner"
	export GITHUB_PATH="$BATS_TEST_TMPDIR/github-path"
	export CALLS="$BATS_TEST_TMPDIR/calls"
	export REVISION=89c352ae6ff0bbafe17788da327764d9ef92240b
	mkdir -p "$RUNNER_TEMP" "$BATS_TEST_TMPDIR/bin"
	: >"$GITHUB_PATH"
	cat >"$BATS_TEST_TMPDIR/bin/cargo" <<'STUB'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >>"$CALLS"
[ "${FAIL_INSTALL:-false}" = false ] || exit 42
root=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = --root ]; then root="$2"; shift; fi
  shift
done
[ -n "$root" ]
mkdir -p "$root/bin"
if [ "${MISS_BINARY:-false}" = false ]; then
  printf '#!/bin/sh\nexit 0\n' >"$root/bin/cargo-zigbuild"
  chmod +x "$root/bin/cargo-zigbuild"
fi
printf '{"installs":{"cargo-zigbuild 0.23.4 (git+https://github.com/rust-cross/cargo-zigbuild.git?rev=%s#%s)":{}}}\n' "$REVISION" "${SOURCE_REVISION:-$REVISION}" >"$root/.crates2.json"
STUB
	chmod +x "$BATS_TEST_TMPDIR/bin/cargo"
	export PATH="$BATS_TEST_TMPDIR/bin:$PATH"
}

@test "empty revision leaves the default setup unchanged" {
	run bash "$script" ""
	[ "$status" -eq 0 ]
	[ ! -e "$CALLS" ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "mutable and malformed revisions fail before installation" {
	for revision in main v0.23.4 89c352ae 89C352AE6FF0BBAFE17788DA327764D9EF92240B; do
		run bash "$script" "$revision"
		[ "$status" -ne 0 ]
		[[ "$output" == *"full lowercase 40-character commit SHA"* ]]
	done
	[ ! -e "$CALLS" ]
}

@test "installs the exact official source into an isolated prefix" {
	run bash "$script" "$REVISION"
	[ "$status" -eq 0 ]
	[ "$(wc -l <"$CALLS" | tr -d ' ')" -eq 1 ]
	grep -F -- "install --locked --git https://github.com/rust-cross/cargo-zigbuild.git --rev $REVISION --root $RUNNER_TEMP/cargo-zigbuild." "$CALLS"
	prefix=$(cat "$GITHUB_PATH")
	[ -x "$prefix/cargo-zigbuild" ]
	[[ "$prefix" == "$RUNNER_TEMP"/cargo-zigbuild.*/bin ]]
}

@test "same version from the wrong source revision is rejected" {
	export SOURCE_REVISION=0000000000000000000000000000000000000000
	run bash "$script" "$REVISION"
	[ "$status" -ne 0 ]
	[[ "$output" == *"installed source revision does not match"* ]]
	[ ! -s "$GITHUB_PATH" ]
}

@test "missing installed binary cannot become a successful setup" {
	export MISS_BINARY=true
	run bash "$script" "$REVISION"
	[ "$status" -ne 0 ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "installation failure is propagated without exposing a path" {
	export FAIL_INSTALL=true
	run bash "$script" "$REVISION"
	[ "$status" -eq 42 ]
	[ ! -s "$GITHUB_PATH" ]
}

@test "setup-rust opts into source installation only through its revision input" {
	action="$BATS_TEST_DIRNAME/../action.yml"
	grep -F '  cargo-zigbuild-revision:' "$action"
	grep -F "if: inputs.cargo-zigbuild-revision != ''" "$action"
	grep -F 'CARGO_ZIGBUILD_REVISION: ${{ inputs.cargo-zigbuild-revision }}' "$action"
	grep -F '"$GITHUB_ACTION_PATH/scripts/install-cargo-zigbuild.sh" "$CARGO_ZIGBUILD_REVISION"' "$action"
}
