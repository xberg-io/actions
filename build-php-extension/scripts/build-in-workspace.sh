# shellcheck shell=bash

set -euo pipefail

crate_name="$1"
lib_name="$2"
workspace_root="$3"

cd "$workspace_root"

case "${RUNNER_OS:-$(uname)}" in
Windows | MINGW* | MSYS*)
	library="$lib_name.dll"
	export RUSTC_BOOTSTRAP=1
	export CFLAGS_x86_64_pc_windows_msvc=/MD CXXFLAGS_x86_64_pc_windows_msvc=/MD
	export CFLAGS_i686_pc_windows_msvc=/MD CXXFLAGS_i686_pc_windows_msvc=/MD
	;;
macOS | Darwin) library="lib$lib_name.dylib" ;;
*) library="lib$lib_name.so" ;;
esac

build_args=(--release --locked --package "$crate_name" --target-dir "$workspace_root/target")
if [[ -n "${CARGO_FEATURES:-}" ]]; then
	build_args+=(--features "$CARGO_FEATURES")
fi

# ~keep Keep unpublished sibling dependencies and the workspace lock intact. Stdout
# is reserved for the action output; cargo diagnostics belong on stderr.
cargo build "${build_args[@]}" >&2

extension_path="$workspace_root/target/release/$library"
if [[ ! -f "$extension_path" ]]; then
	echo "Error: cargo build did not produce $extension_path; check lib-name and crate-type" >&2
	exit 1
fi
printf '%s\n' "$extension_path"
