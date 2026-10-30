#!/usr/bin/env bats

setup() {
	bats_load_library xberg-bats
	xberg_setup
	ROOT="$XBERG_WORK"
	BIN="$XBERG_STUB_BIN"
	mkdir -p "$BIN" "$ROOT/ws"
	ROOT="$(cd "$ROOT" && pwd -P)"
	BIN="$XBERG_STUB_BIN"
	export PATH="$BIN:$PATH"
	SCRIPT="$BATS_TEST_DIRNAME/../scripts/build-out-of-workspace.sh"
}

@test "should_return_error_when_input_path_does_not_exist" {
	run bash "$SCRIPT" absent "$ROOT/out" "$ROOT/ws"
	[ "$status" -eq 1 ]
	[ "$output" = "Error: input not found at $ROOT/ws/absent (neither file nor dir)" ]
}

@test "should_return_error_when_package_has_no_build_manifest" {
	mkdir -p "$ROOT/ws/pkg"
	run bash "$SCRIPT" pkg "$ROOT/out" "$ROOT/ws"
	[ "$status" -eq 1 ]
	[ "$output" = "Error: $ROOT/ws/pkg has neither Cargo.toml nor pyproject.toml" ]
}

@test "should_isolate_normal_package_and_run_lockfile_then_maturin" {
	mkdir -p "$ROOT/ws/pkg"
	printf '[package]\nname = "pkg"\nversion = "1"\n' >"$ROOT/ws/pkg/Cargo.toml"
	xberg_stub cargo 'printf "%s\n" "$*" >> "'"$ROOT"'/calls"'
	xberg_stub maturin 'printf "%s\n" "$*" >> "'"$ROOT"'/calls"'
	run bash "$SCRIPT" pkg "$ROOT/out" "$ROOT/ws"
	[ "$status" -eq 0 ]
	[[ "$output" == *"Building sdist from package: pkg"* ]]
	[ "$(cat "$ROOT/calls")" = $'generate-lockfile\nsdist --out '"$ROOT"'/out' ]
}

@test "should_build_split_layout_from_isolated_workspace" {
	mkdir -p "$ROOT/ws/python" "$ROOT/ws/crates/core"
	printf '[tool.maturin]\nmanifest-path = "../crates/core/Cargo.toml"\n' >"$ROOT/ws/python/pyproject.toml"
	printf '[package]\nname = "core"\nversion = "1"\n' >"$ROOT/ws/crates/core/Cargo.toml"
	printf '[workspace]\nresolver = "2"\n' >"$ROOT/ws/Cargo.toml"
	xberg_stub cargo 'exit 0'
	xberg_stub maturin 'printf "%s\n" "$*" > "'"$ROOT"'/maturin.args"'
	run bash "$SCRIPT" python "$ROOT/out" "$ROOT/ws"
	[ "$status" -eq 0 ]
	[[ "$output" == *"Split layout detected; isolating $ROOT/ws/python + crate into a single-member workspace"* ]]
	[ "$(cat "$ROOT/maturin.args")" = "sdist --out $ROOT/out" ]
}

closure_fixture() {
	mkdir -p "$ROOT/ws/packages/python" "$ROOT/ws/crates/binding/src"
	printf '[workspace]\nmembers=["crates/binding"]\n' >"$ROOT/ws/Cargo.toml"
	printf '[tool.maturin]\nmanifest-path="../../crates/binding/Cargo.toml"\n' >"$ROOT/ws/packages/python/pyproject.toml"
	printf '[package]\nname="binding"\nversion="1.0.0"\n' >"$ROOT/ws/crates/binding/Cargo.toml"
	printf 'fn main() {}\n' >"$ROOT/ws/crates/binding/src/main.rs"
}

metadata_only_cargo() {
	# ~keep Trace legacy lock generation separately; this stub proves shell branches, not real Cargo resolution.
	cat >"$BIN/cargo" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$ROOT/cargo.calls"
case "\$1" in
  generate-lockfile) exit 0 ;;
  metadata) ;;
  *) echo unexpected-cargo >&2; exit 97 ;;
esac
printf '%s\n' '{"workspace_root":"$ROOT/ws","packages":[{"manifest_path":"$ROOT/ws/crates/binding/Cargo.toml","name":"binding","id":"binding","source":null,"dependencies":[]}],"resolve":{"nodes":[{"id":"binding","deps":[]}]}}'
EOF
	chmod +x "$BIN/cargo"
}

@test "should_delegate_workspace_closure_to_original_split_package_without_registry_rewrite" {
	closure_fixture
	metadata_only_cargo
	xberg_stub maturin 'printf "%s\n%s\n" "$PWD" "$*" > "'"$ROOT"'/closure-call"'
	run /bin/bash "$SCRIPT" packages/python "$ROOT/out" "$ROOT/ws" workspace-closure
	[ "$status" -eq 0 ]
	[ "$(cat "$ROOT/closure-call")" = "$ROOT/ws/packages/python"$'\n'"sdist --out $ROOT/out" ]
}

@test "should_pass_original_manifest_path_from_workspace_root_in_closure_mode" {
	closure_fixture
	metadata_only_cargo
	xberg_stub maturin 'printf "%s\n%s\n" "$PWD" "$*" > "'"$ROOT"'/closure-call"'
	run /bin/bash "$SCRIPT" crates/binding/Cargo.toml "$ROOT/out" "$ROOT/ws" workspace-closure
	[ "$status" -eq 0 ]
	[ "$(cat "$ROOT/closure-call")" = "$ROOT/ws"$'\n'"sdist --manifest-path $ROOT/ws/crates/binding/Cargo.toml --out $ROOT/out" ]
}

@test "should_resolve_relative_closure_output_from_workspace_root" {
	closure_fixture
	metadata_only_cargo
	xberg_stub maturin 'printf "%s\n" "$*" > "'"$ROOT"'/closure-call"'
	cd "$ROOT/ws"
	run /bin/bash "$SCRIPT" packages/python dist "$ROOT/ws" workspace-closure
	[ "$status" -eq 0 ]
	[ "$(cat "$ROOT/closure-call")" = "sdist --out $ROOT/ws/dist" ]
}

@test "should_reject_unknown_source_mode_before_creating_output" {
	closure_fixture
	metadata_only_cargo
	xberg_stub maturin 'exit 0'
	run /bin/bash "$SCRIPT" packages/python "$ROOT/out" "$ROOT/ws" unknown
	[ "$status" -eq 1 ]
	[ "$output" = "Error: unsupported source-dependencies: unknown" ]
	[ ! -e "$ROOT/out" ]
}

@test "should_reject_closure_input_outside_workspace" {
	closure_fixture
	metadata_only_cargo
	mkdir -p "$ROOT/external/src"
	printf '[tool.maturin]\nmanifest-path="Cargo.toml"\n' >"$ROOT/external/pyproject.toml"
	printf '[package]\nname="external"\nversion="1.0.0"\n' >"$ROOT/external/Cargo.toml"
	printf 'fn main() {}\n' >"$ROOT/external/src/main.rs"
	xberg_stub maturin 'exit 0'
	run /bin/bash "$SCRIPT" ../external "$ROOT/out" "$ROOT/ws" workspace-closure
	[ "$status" -eq 1 ]
	[ "$output" = "Error: input resolves outside workspace" ]
	[ ! -e "$ROOT/out" ]
}

@test "should_propagate_real_maturin_failure_in_closure_mode" {
	closure_fixture
	metadata_only_cargo
	xberg_stub maturin 'echo package-failed >&2; exit 37'
	run /bin/bash "$SCRIPT" packages/python "$ROOT/out" "$ROOT/ws" workspace-closure
	[ "$status" -eq 37 ]
	[[ "$output" == *package-failed* ]]
}

@test "should_canonicalize_symlinked_workspace_for_manifest_and_relative_output" {
	closure_fixture
	metadata_only_cargo
	ln -s "$ROOT/ws" "$ROOT/workspace-link"
	xberg_stub maturin 'printf "%s\n%s\n" "$PWD" "$*" > "'"$ROOT"'/closure-call"'
	run /bin/bash "$SCRIPT" crates/binding/Cargo.toml dist "$ROOT/workspace-link" workspace-closure
	[ "$status" -eq 0 ]
	[ "$(cat "$ROOT/closure-call")" = "$ROOT/ws"$'\n'"sdist --manifest-path $ROOT/ws/crates/binding/Cargo.toml --out $ROOT/ws/dist" ]
}
