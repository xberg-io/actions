#!/usr/bin/env bash
set -euo pipefail

FFI_CRATE="${INPUT_FFI_CRATE:-xberg-ffi}"
PACKAGE_DIR="${INPUT_PACKAGE_DIR:-packages/zig}"
BUILD_PROFILE="${INPUT_BUILD_PROFILE:-release}"
DRY_RUN="${INPUT_DRY_RUN:-false}"

case "$BUILD_PROFILE" in
release)
	profile_flag="--release"
	target_subdir="release"
	;;
dev | debug)
	profile_flag=""
	target_subdir="debug"
	;;
*)
	profile_flag="--profile $BUILD_PROFILE"
	target_subdir="$BUILD_PROFILE"
	;;
esac

lib_basename="${FFI_CRATE//-/_}"

case "${RUNNER_OS:-$(uname -s)}" in
Linux) lib_filename="lib${lib_basename}.so" ;;
macOS | Darwin) lib_filename="lib${lib_basename}.dylib" ;;
Windows | MINGW* | MSYS* | CYGWIN*) lib_filename="${lib_basename}.dll" ;;
*) lib_filename="lib${lib_basename}.so" ;;
esac

workspace="${GITHUB_WORKSPACE:-$PWD}"
target_dir="${CARGO_TARGET_DIR:-$workspace/target}"
ffi_library_path="$target_dir/$target_subdir/$lib_filename"

if [[ "$DRY_RUN" == "true" ]]; then
	echo "[dry-run] cargo build --locked -p $FFI_CRATE $profile_flag"
	echo "[dry-run] cd $PACKAGE_DIR && zig build"
	echo "[dry-run] expected ffi library: $ffi_library_path"
	if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
		echo "ffi-library-path=$ffi_library_path" >>"$GITHUB_OUTPUT"
	fi
	exit 0
fi

if [[ ! -d "$PACKAGE_DIR" ]]; then
	echo "Error: package-dir '$PACKAGE_DIR' does not exist" >&2
	exit 1
fi

echo "=== Building cargo crate $FFI_CRATE (profile: $BUILD_PROFILE) ==="
# shellcheck disable=SC2086
cargo build --locked -p "$FFI_CRATE" $profile_flag

if [[ ! -f "$ffi_library_path" ]]; then
	echo "Warning: expected FFI library not found at $ffi_library_path" >&2
	found=$(find "$target_dir/$target_subdir" -maxdepth 1 -type f \
		\( -name "lib${lib_basename}.*" -o -name "${lib_basename}.dll" \) \
		-print -quit 2>/dev/null || true)
	if [[ -n "$found" ]]; then
		ffi_library_path="$found"
		echo "Resolved FFI library: $ffi_library_path"
	else
		echo "Error: no built FFI library found for $FFI_CRATE" >&2
		exit 1
	fi
fi

ffi_dir="$target_dir/$target_subdir"

echo "=== Running zig build in $PACKAGE_DIR (-Dffi_path=$ffi_dir) ==="
(
	cd "$PACKAGE_DIR"
	zig build -Dffi_path="$ffi_dir"
	if [[ -f build.zig ]] && grep -Eq 'b\.step\(\s*"test"' build.zig; then
		echo "=== Running zig build test ==="
		zig build test -Dffi_path="$ffi_dir"
	else
		echo "No 'test' step found in build.zig; skipping zig build test"
	fi
)

echo "Zig smoke build complete"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	echo "ffi-library-path=$ffi_library_path" >>"$GITHUB_OUTPUT"
fi
