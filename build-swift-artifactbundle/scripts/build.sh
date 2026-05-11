#!/usr/bin/env bash
# Build a Swift Package Manager SE-0305 artifact bundle containing static
# Rust libraries for macOS (arm64, x86_64), iOS (device arm64, simulator
# arm64+x86_64), and Linux (arm64, x86_64). Output is an .artifactbundle
# directory with info.json and per-target static libraries, plus a zip.
#
# Reads (env vars set by the composite action):
#   INPUT_CRATE_NAME        - cargo crate name (e.g. kreuzberg-swift)
#   INPUT_LIB_NAME          - library base name (default = crate_name with - → _)
#   INPUT_ARTIFACT_NAME     - artifact bundle name (default = PascalCase of lib_name)
#   INPUT_HEADER_PATH       - optional path to C headers directory
#   INPUT_OUTPUT_DIR        - output directory (default: dist/swift-artifactbundle)
#   INPUT_BUILD_PROFILE     - cargo profile (release, dev, ...)
#   INPUT_DRY_RUN           - "true" to print the plan and exit
set -euo pipefail

CRATE_NAME="${INPUT_CRATE_NAME:-kreuzberg-swift}"
LIB_NAME="${INPUT_LIB_NAME:-}"
ARTIFACT_NAME="${INPUT_ARTIFACT_NAME:-}"
HEADER_PATH="${INPUT_HEADER_PATH:-}"
OUTPUT_DIR="${INPUT_OUTPUT_DIR:-dist/swift-artifactbundle}"
BUILD_PROFILE="${INPUT_BUILD_PROFILE:-release}"
DRY_RUN="${INPUT_DRY_RUN:-false}"

# Set defaults for lib_name and artifact_name
if [[ -z "$LIB_NAME" ]]; then
  LIB_NAME="${CRATE_NAME//-/_}"
fi

if [[ -z "$ARTIFACT_NAME" ]]; then
  # Convert snake_case to PascalCase
  ARTIFACT_NAME="$(echo "$LIB_NAME" | sed -E 's/(^|_)([a-z])/\U\2/g')"
fi

case "$BUILD_PROFILE" in
release)
  profile_flag="--release"
  ;;
dev | debug)
  profile_flag=""
  ;;
*)
  profile_flag="--profile $BUILD_PROFILE"
  ;;
esac

workspace="${GITHUB_WORKSPACE:-$PWD}"
target_dir="${CARGO_TARGET_DIR:-$workspace/target}"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] cargo build -p $CRATE_NAME $profile_flag --target aarch64-apple-darwin"
  echo "[dry-run] cargo build -p $CRATE_NAME $profile_flag --target x86_64-apple-darwin"
  echo "[dry-run] cargo build -p $CRATE_NAME $profile_flag --target aarch64-apple-ios"
  echo "[dry-run] cargo build -p $CRATE_NAME $profile_flag --target aarch64-apple-ios-sim"
  echo "[dry-run] cargo build -p $CRATE_NAME $profile_flag --target x86_64-apple-ios"
  echo "[dry-run] cross build -p $CRATE_NAME $profile_flag --target aarch64-unknown-linux-gnu"
  echo "[dry-run] cross build -p $CRATE_NAME $profile_flag --target x86_64-unknown-linux-gnu"
  echo "[dry-run] lipo arm64-sim x86_64 -> ios-sim fat"
  echo "[dry-run] would assemble $OUTPUT_DIR/$ARTIFACT_NAME.artifactbundle"
  echo "[dry-run] would generate info.json with SE-0305 metadata"
  if [[ -n "$HEADER_PATH" ]]; then
    echo "[dry-run] would copy headers from $HEADER_PATH"
  fi
  echo "[dry-run] would zip to $OUTPUT_DIR/$ARTIFACT_NAME.artifactbundle.zip"
  echo "[dry-run] would compute checksum via swift package compute-checksum"
  exit 0
fi

# Add required targets
echo "=== Adding Rust targets ==="
rustup target add aarch64-apple-darwin x86_64-apple-darwin \
  aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios \
  aarch64-unknown-linux-gnu x86_64-unknown-linux-gnu

# Install cross if not already present
echo "=== Ensuring cross is installed ==="
cargo install cross --locked 2>/dev/null || true

# Create output directory
mkdir -p "$OUTPUT_DIR"
bundle_dir="$OUTPUT_DIR/$ARTIFACT_NAME.artifactbundle"
rm -rf "$bundle_dir"
mkdir -p "$bundle_dir"

# Build Apple targets
echo "=== Building Apple targets ==="
echo "Building aarch64-apple-darwin..."
# shellcheck disable=SC2086
cargo build -p "$CRATE_NAME" $profile_flag --target aarch64-apple-darwin

echo "Building x86_64-apple-darwin..."
# shellcheck disable=SC2086
cargo build -p "$CRATE_NAME" $profile_flag --target x86_64-apple-darwin

echo "Building aarch64-apple-ios..."
# shellcheck disable=SC2086
cargo build -p "$CRATE_NAME" $profile_flag --target aarch64-apple-ios

echo "Building aarch64-apple-ios-sim..."
# shellcheck disable=SC2086
cargo build -p "$CRATE_NAME" $profile_flag --target aarch64-apple-ios-sim

echo "Building x86_64-apple-ios..."
# shellcheck disable=SC2086
cargo build -p "$CRATE_NAME" $profile_flag --target x86_64-apple-ios

# Build Linux targets using cross
echo "=== Building Linux targets (cross) ==="
echo "Building aarch64-unknown-linux-gnu..."
# shellcheck disable=SC2086
cross build -p "$CRATE_NAME" $profile_flag --target aarch64-unknown-linux-gnu

echo "Building x86_64-unknown-linux-gnu..."
# shellcheck disable=SC2086
cross build -p "$CRATE_NAME" $profile_flag --target x86_64-unknown-linux-gnu

# Determine the target subdirectory for library lookup
case "$BUILD_PROFILE" in
release)
  target_subdir="release"
  ;;
dev | debug)
  target_subdir="debug"
  ;;
*)
  target_subdir="$BUILD_PROFILE"
  ;;
esac

# Copy/create bundle directories
echo "=== Creating artifact bundle structure ==="
mkdir -p "$bundle_dir/$ARTIFACT_NAME-macos-arm64"
mkdir -p "$bundle_dir/$ARTIFACT_NAME-macos-x86_64"
mkdir -p "$bundle_dir/$ARTIFACT_NAME-ios-arm64"
mkdir -p "$bundle_dir/$ARTIFACT_NAME-ios-sim"
mkdir -p "$bundle_dir/$ARTIFACT_NAME-linux-x86_64"
mkdir -p "$bundle_dir/$ARTIFACT_NAME-linux-aarch64"

# Copy static libraries
echo "=== Copying static libraries ==="
cp "$target_dir/aarch64-apple-darwin/$target_subdir/lib${LIB_NAME}.a" \
  "$bundle_dir/$ARTIFACT_NAME-macos-arm64/lib${LIB_NAME}.a"

cp "$target_dir/x86_64-apple-darwin/$target_subdir/lib${LIB_NAME}.a" \
  "$bundle_dir/$ARTIFACT_NAME-macos-x86_64/lib${LIB_NAME}.a"

cp "$target_dir/aarch64-apple-ios/$target_subdir/lib${LIB_NAME}.a" \
  "$bundle_dir/$ARTIFACT_NAME-ios-arm64/lib${LIB_NAME}.a"

cp "$target_dir/aarch64-apple-ios-sim/$target_subdir/lib${LIB_NAME}.a" \
  "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.arm64"

cp "$target_dir/x86_64-apple-ios/$target_subdir/lib${LIB_NAME}.a" \
  "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.x86_64"

# Create fat iOS simulator library
echo "=== Creating iOS simulator fat library ==="
lipo -create \
  "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.arm64" \
  "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.x86_64" \
  -output "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a"
rm "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.arm64" \
  "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.x86_64"

cp "$target_dir/aarch64-unknown-linux-gnu/$target_subdir/lib${LIB_NAME}.a" \
  "$bundle_dir/$ARTIFACT_NAME-linux-aarch64/lib${LIB_NAME}.a"

cp "$target_dir/x86_64-unknown-linux-gnu/$target_subdir/lib${LIB_NAME}.a" \
  "$bundle_dir/$ARTIFACT_NAME-linux-x86_64/lib${LIB_NAME}.a"

# Optionally copy headers
if [[ -n "$HEADER_PATH" && -d "$HEADER_PATH" ]]; then
  echo "=== Copying headers from $HEADER_PATH ==="
  mkdir -p "$bundle_dir/$ARTIFACT_NAME-headers"
  cp -r "$HEADER_PATH"/* "$bundle_dir/$ARTIFACT_NAME-headers/"
fi

# Generate info.json per SE-0305
echo "=== Generating info.json ==="
cat >"$bundle_dir/info.json" <<'EOF'
{
  "schemaVersion": "1.0",
  "artifacts": {
    "$ARTIFACT_NAME": {
      "type": "staticLibrary",
      "version": "1.0.0",
      "variants": [
        {
          "path": "$ARTIFACT_NAME-macos-arm64/lib$LIB_NAME.a",
          "supportedTriples": ["arm64-apple-macosx"]
        },
        {
          "path": "$ARTIFACT_NAME-macos-x86_64/lib$LIB_NAME.a",
          "supportedTriples": ["x86_64-apple-macosx"]
        },
        {
          "path": "$ARTIFACT_NAME-ios-arm64/lib$LIB_NAME.a",
          "supportedTriples": ["arm64-apple-ios"]
        },
        {
          "path": "$ARTIFACT_NAME-ios-sim/lib$LIB_NAME.a",
          "supportedTriples": ["arm64-apple-ios-simulator", "x86_64-apple-ios-simulator"]
        },
        {
          "path": "$ARTIFACT_NAME-linux-x86_64/lib$LIB_NAME.a",
          "supportedTriples": ["x86_64-unknown-linux-gnu"]
        },
        {
          "path": "$ARTIFACT_NAME-linux-aarch64/lib$LIB_NAME.a",
          "supportedTriples": ["aarch64-unknown-linux-gnu"]
        }
      ]
    }
  }
}
EOF

# Use sed to substitute placeholders (bash doesn't support variable expansion in heredoc with -v)
sed -i '' "s/\$ARTIFACT_NAME/$ARTIFACT_NAME/g" "$bundle_dir/info.json"
sed -i '' "s/\$LIB_NAME/$LIB_NAME/g" "$bundle_dir/info.json"

echo "Created $bundle_dir/info.json"

# Create zip
echo "=== Creating zip archive ==="
pushd "$OUTPUT_DIR" >/dev/null
zip -r "${ARTIFACT_NAME}.artifactbundle.zip" "${ARTIFACT_NAME}.artifactbundle"
popd >/dev/null

bundle_zip="$OUTPUT_DIR/${ARTIFACT_NAME}.artifactbundle.zip"
echo "Created $bundle_zip"

# Compute checksum
echo "=== Computing checksum ==="
checksum=$(swift package compute-checksum "$bundle_zip" 2>/dev/null ||
  shasum -a 256 "$bundle_zip" | awk '{print $1}')
echo "Checksum: $checksum"

# Emit outputs
{
  echo "bundle-path=$bundle_dir"
  echo "bundle-zip=$bundle_zip"
  echo "checksum=$checksum"
} >>"$GITHUB_OUTPUT"

echo "Artifact bundle complete"
