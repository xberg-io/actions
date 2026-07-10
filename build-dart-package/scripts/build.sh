#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="${INPUT_PACKAGE_DIR:-packages/dart}"
CRATE_NAME="${INPUT_CRATE_NAME:-xberg-dart}"
BUILD_PROFILE="${INPUT_BUILD_PROFILE:-release}"
DRY_RUN="${INPUT_DRY_RUN:-false}"

MANIFEST_PATH="$PACKAGE_DIR/Cargo.toml"

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

lib_basename="${CRATE_NAME//-/_}"

case "${RUNNER_OS:-$(uname -s)}" in
Linux) lib_filename="lib${lib_basename}.so" ;;
macOS | Darwin) lib_filename="lib${lib_basename}.dylib" ;;
Windows | MINGW* | MSYS* | CYGWIN*) lib_filename="${lib_basename}.dll" ;;
*) lib_filename="lib${lib_basename}.so" ;;
esac

resolve_target_dir() {
	if [[ -n "${CARGO_TARGET_DIR:-}" ]]; then
		echo "$CARGO_TARGET_DIR"
		return
	fi
	cargo metadata --manifest-path "$MANIFEST_PATH" --format-version 1 --no-deps 2>/dev/null |
		jq -r '.target_directory'
}

if [[ "$DRY_RUN" == "true" ]]; then
	echo "[dry-run] cd $PACKAGE_DIR && flutter_rust_bridge_codegen generate"
	echo "[dry-run] cargo build --locked --manifest-path $MANIFEST_PATH $profile_flag"
	workspace="${GITHUB_WORKSPACE:-$PWD}"
	target_dir="${CARGO_TARGET_DIR:-$workspace/target}"
	library_path="$target_dir/$target_subdir/$lib_filename"
	echo "[dry-run] expected library: $library_path"
	if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
		echo "library-path=$library_path" >>"$GITHUB_OUTPUT"
	fi
	exit 0
fi

if [[ ! -d "$PACKAGE_DIR" ]]; then
	echo "Error: package-dir '$PACKAGE_DIR' does not exist" >&2
	exit 1
fi

echo "=== Running flutter_rust_bridge codegen in $PACKAGE_DIR ==="
(
	cd "$PACKAGE_DIR"
	flutter_rust_bridge_codegen generate
)

echo "=== Building cargo crate $CRATE_NAME (profile: $BUILD_PROFILE) ==="
# shellcheck disable=SC2086
cargo build --locked --manifest-path "$MANIFEST_PATH" $profile_flag

target_dir="$(resolve_target_dir)"
if [[ -z "$target_dir" ]]; then
	echo "Error: could not resolve cargo target directory for $MANIFEST_PATH" >&2
	exit 1
fi

library_path="$target_dir/$target_subdir/$lib_filename"

if [[ ! -f "$library_path" ]]; then
	echo "Warning: expected library not found at $library_path" >&2
	echo "Searching $target_dir/$target_subdir for matching artifact..." >&2
	found=$(find "$target_dir/$target_subdir" -maxdepth 1 -type f \
		\( -name "${lib_basename}*.so" -o -name "${lib_basename}*.dylib" \
		-o -name "${lib_basename}*.dll" -o -name "lib${lib_basename}*.so" \
		-o -name "lib${lib_basename}*.dylib" \) \
		-print -quit 2>/dev/null || true)
	if [[ -n "$found" ]]; then
		library_path="$found"
		echo "Resolved library: $library_path"
	else
		echo "Error: no built library found for $CRATE_NAME" >&2
		exit 1
	fi
fi

echo "Built library: $library_path"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	echo "library-path=$library_path" >>"$GITHUB_OUTPUT"
fi
