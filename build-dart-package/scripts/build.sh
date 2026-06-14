#!/usr/bin/env bash
# Build the Dart-side Rust binding crate, run flutter_rust_bridge codegen,
# and emit the resulting library path on $GITHUB_OUTPUT.
#
# Reads (env vars set by the composite action):
#   INPUT_PACKAGE_DIR    - directory containing pubspec.yaml (e.g. packages/dart)
#   INPUT_CRATE_NAME     - cargo crate name (e.g. kreuzberg-dart)
#   INPUT_BUILD_PROFILE  - cargo profile name (release, dev, ...)
#   INPUT_DRY_RUN        - "true" to print commands and exit
set -euo pipefail

PACKAGE_DIR="${INPUT_PACKAGE_DIR:-packages/dart}"
CRATE_NAME="${INPUT_CRATE_NAME:-kreuzberg-dart}"
BUILD_PROFILE="${INPUT_BUILD_PROFILE:-release}"
DRY_RUN="${INPUT_DRY_RUN:-false}"

# `cargo build --profile dev` is rejected; cargo's dev profile lives under
# target/debug. Map it the same way cargo does.
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

# cargo derives the lib name by replacing dashes with underscores.
lib_basename="${CRATE_NAME//-/_}"

case "${RUNNER_OS:-$(uname -s)}" in
Linux) lib_filename="lib${lib_basename}.so" ;;
macOS | Darwin) lib_filename="lib${lib_basename}.dylib" ;;
Windows | MINGW* | MSYS* | CYGWIN*) lib_filename="${lib_basename}.dll" ;;
*) lib_filename="lib${lib_basename}.so" ;;
esac

workspace="${GITHUB_WORKSPACE:-$PWD}"
target_dir="${CARGO_TARGET_DIR:-$workspace/target}"
library_path="$target_dir/$target_subdir/$lib_filename"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] cd $PACKAGE_DIR && flutter_rust_bridge_codegen generate"
  echo "[dry-run] cargo build --locked -p $CRATE_NAME $profile_flag"
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
cargo build --locked -p "$CRATE_NAME" $profile_flag

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
