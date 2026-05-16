#!/usr/bin/env bash
# Build the Swift-side Rust binding crate and sync swift-bridge generated
# files into the Swift package's Sources/RustBridgeC/ and Sources/RustBridge/.
#
# Layout (per packages/swift/BUILDING.md):
#   target/<profile>/build/<crate>-*/out/SwiftBridgeCore.h
#   target/<profile>/build/<crate>-*/out/SwiftBridgeCore.swift
#   target/<profile>/build/<crate>-*/out/<crate>/<crate>.h
#   target/<profile>/build/<crate>-*/out/<crate>/<crate>.swift
#
# Sync rules (mirrors BUILDING.md):
#   - Concatenate SwiftBridgeCore.h + <crate>/<crate>.h -> RustBridgeC/RustBridgeC.h
#   - Prepend `import RustBridgeC\n` to each .swift file -> Sources/RustBridge/<file>.swift
#
# Reads (env vars set by the composite action):
#   INPUT_PACKAGE_DIR    - directory containing Package.swift
#   INPUT_CRATE_NAME     - cargo crate name (e.g. kreuzberg-swift)
#   INPUT_BUILD_PROFILE  - cargo profile name (release, dev, ...)
#   INPUT_DRY_RUN        - "true" to print the plan and exit
set -euo pipefail

PACKAGE_DIR="${INPUT_PACKAGE_DIR:-packages/swift}"
CRATE_NAME="${INPUT_CRATE_NAME:-kreuzberg-swift}"
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

workspace="${GITHUB_WORKSPACE:-$PWD}"
target_dir="${CARGO_TARGET_DIR:-$workspace/target}"
build_root="$target_dir/$target_subdir/build"

bridge_c_dst="$PACKAGE_DIR/Sources/RustBridgeC"
bridge_swift_dst="$PACKAGE_DIR/Sources/RustBridge"

normalize_swift_bridge_core() {
  local file="$1"
  local tmp
  tmp="$(mktemp)"
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
    "extension RustStr: Identifiable {")
      printf '%s\n' "extension RustStr: @retroactive Identifiable {"
      ;;
    "extension RustStr: Equatable {")
      printf '%s\n' "extension RustStr: @retroactive Equatable {"
      ;;
    *)
      printf '%s\n' "$line"
      ;;
    esac
  done <"$file" >"$tmp"
  mv "$tmp" "$file"
}

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] cargo build -p $CRATE_NAME $profile_flag"
  echo "[dry-run] would resolve out/ under $build_root/$CRATE_NAME-*/out"
  echo "[dry-run] would write combined header to $bridge_c_dst/RustBridgeC.h"
  echo "[dry-run] would write swift bridge files to $bridge_swift_dst/"
  exit 0
fi

if [[ ! -d "$PACKAGE_DIR" ]]; then
  echo "Error: package-dir '$PACKAGE_DIR' does not exist" >&2
  exit 1
fi

echo "=== Building cargo crate $CRATE_NAME (profile: $BUILD_PROFILE) ==="
# shellcheck disable=SC2086
cargo build -p "$CRATE_NAME" $profile_flag

# Resolve the most recent out/ directory; cargo can keep multiple build hashes.
shopt -s nullglob
candidates=("$build_root/$CRATE_NAME"-*/out)
shopt -u nullglob
if [[ ${#candidates[@]} -eq 0 ]]; then
  echo "Error: no swift-bridge out/ directory found under $build_root/$CRATE_NAME-*/" >&2
  exit 1
fi

# Pick the most recently modified candidate (matches BUILDING.md `ls -dt | head -1`).
out_dir=""
out_mtime=0
for candidate in "${candidates[@]}"; do
  if [[ -d "$candidate" ]]; then
    mtime=$(stat -f '%m' "$candidate" 2>/dev/null || stat -c '%Y' "$candidate" 2>/dev/null || echo 0)
    if ((mtime > out_mtime)); then
      out_mtime=$mtime
      out_dir=$candidate
    fi
  fi
done

if [[ -z "$out_dir" ]]; then
  echo "Error: could not resolve a usable out/ directory" >&2
  exit 1
fi
echo "Resolved swift-bridge out/: $out_dir"

mkdir -p "$bridge_c_dst" "$bridge_swift_dst"

# Combined C header — concatenate the core header with the per-crate header.
core_h="$out_dir/SwiftBridgeCore.h"
crate_h="$out_dir/$CRATE_NAME/$CRATE_NAME.h"
combined_h="$bridge_c_dst/RustBridgeC.h"

if [[ ! -f "$core_h" ]]; then
  echo "Warning: expected $core_h not found; skipping core header" >&2
  : >"$combined_h"
else
  cat "$core_h" >"$combined_h"
fi
if [[ -f "$crate_h" ]]; then
  cat "$crate_h" >>"$combined_h"
else
  echo "Warning: expected $crate_h not found" >&2
fi
echo "Wrote $combined_h"

# Swift bridge files: prepend `import RustBridgeC` to each .swift in out/ and
# in out/<crate>/.
copy_swift_with_import() {
  local src="$1"
  local dst
  dst="$bridge_swift_dst/$(basename "$src")"
  {
    echo "import RustBridgeC"
    cat "$src"
  } >"$dst"
  if [[ "$(basename "$src")" == "SwiftBridgeCore.swift" ]]; then
    normalize_swift_bridge_core "$dst"
  fi
  echo "Wrote $dst"
}

shopt -s nullglob
swift_top=("$out_dir"/*.swift)
swift_crate=("$out_dir/$CRATE_NAME"/*.swift)
shopt -u nullglob

if [[ ${#swift_top[@]} -eq 0 && ${#swift_crate[@]} -eq 0 ]]; then
  echo "Warning: no Swift bridge files found under $out_dir" >&2
fi

for f in "${swift_top[@]}" "${swift_crate[@]}"; do
  copy_swift_with_import "$f"
done

echo "Swift package sync complete"
