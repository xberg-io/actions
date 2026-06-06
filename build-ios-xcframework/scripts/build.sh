#!/usr/bin/env bash
set -euo pipefail

# Build a Rust crate for all iOS targets and bundle into an XCFramework.
#
# Stages at: {output-dir}/{xcframework-name}.xcframework
#
# Inputs (env vars):
#     INPUT_CRATE_NAME: cargo package name (required)
#     INPUT_LIB_NAME: library base name (default = crate-name with - → _)
#     INPUT_XCFRAMEWORK_NAME: XCFramework name (default = lib-name PascalCase)
#     INPUT_HEADER_PATH: optional path to C header directory
#     INPUT_OUTPUT_DIR: output root (default dist/ios-xcframework)
#     INPUT_BUILD_PROFILE: cargo build profile (default release)
#     INPUT_DRY_RUN: "true" to skip cargo build (default false)

function write_github_output() {
  local name=$1
  local value=$2
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "${name}=${value}" >>"${GITHUB_OUTPUT}"
  else
    echo "${name}=${value}"
  fi
}

function ensure_input() {
  local name=$1
  local value=$2
  if [[ -z "$value" ]]; then
    echo "Error: ${name} is required" >&2
    exit 1
  fi
  echo "$value"
}

function to_pascal_case() {
  local input=$1
  # Convert underscores to PascalCase (capitalize each segment)
  echo "$input" | sed -E 's/(^|_)([a-z])/\U\2/g'
}

CRATE_NAME=$(ensure_input "INPUT_CRATE_NAME" "${INPUT_CRATE_NAME:-}")
LIB_NAME="${INPUT_LIB_NAME:-}"
[[ -z "$LIB_NAME" ]] && LIB_NAME="${CRATE_NAME//-/_}"

XCFRAMEWORK_NAME="${INPUT_XCFRAMEWORK_NAME:-}"
[[ -z "$XCFRAMEWORK_NAME" ]] && XCFRAMEWORK_NAME=$(to_pascal_case "$LIB_NAME")

HEADER_PATH="${INPUT_HEADER_PATH:-}"
OUTPUT_DIR="${INPUT_OUTPUT_DIR:-dist/ios-xcframework}"
BUILD_PROFILE="${INPUT_BUILD_PROFILE:-release}"
DRY_RUN="${INPUT_DRY_RUN:-false}"

# Determine profile flag for cargo
PROFILE_FLAG=""
case "$BUILD_PROFILE" in
dev)
  PROFILE_FLAG=""
  TARGET_SUBDIR="debug"
  ;;
release)
  PROFILE_FLAG="--release"
  TARGET_SUBDIR="release"
  ;;
*)
  PROFILE_FLAG="--profile" "$BUILD_PROFILE"
  TARGET_SUBDIR="$BUILD_PROFILE"
  ;;
esac

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[build-ios-xcframework] dry-run: skipping cargo build"
  echo "  crate:             $CRATE_NAME"
  echo "  lib:               $LIB_NAME"
  echo "  xcframework:       $XCFRAMEWORK_NAME"
  echo "  output:            $OUTPUT_DIR"
  echo "  profile:           $BUILD_PROFILE"
  echo "  target_subdir:     $TARGET_SUBDIR"
  if [[ -n "$HEADER_PATH" ]]; then
    echo "  headers:           $HEADER_PATH"
  fi

  write_github_output "xcframework-path" "$(cd "$OUTPUT_DIR" 2>/dev/null && pwd || echo "$OUTPUT_DIR")/$XCFRAMEWORK_NAME.xcframework"
  write_github_output "xcframework-zip" "$(cd "$OUTPUT_DIR" 2>/dev/null && pwd || echo "$OUTPUT_DIR")/$XCFRAMEWORK_NAME.xcframework.zip"
  write_github_output "checksum" "placeholder-dry-run"
  exit 0
fi

echo "[build-ios-xcframework] Building for iOS targets..."

# Add iOS targets (x86_64-apple-ios dropped: pyke ORT has no prebuilt for that triple)
echo "[build-ios-xcframework] Installing iOS targets..."
rustup target add aarch64-apple-ios aarch64-apple-ios-sim

# Build for device arm64
echo "[build-ios-xcframework] Building for aarch64-apple-ios..."
cargo build -p "$CRATE_NAME" $PROFILE_FLAG --target aarch64-apple-ios

# Build for simulator arm64
echo "[build-ios-xcframework] Building for aarch64-apple-ios-sim..."
cargo build -p "$CRATE_NAME" $PROFILE_FLAG --target aarch64-apple-ios-sim

# Create simulator library (arm64 only; x86_64-apple-ios deprecated Intel simulator not supported)
echo "[build-ios-xcframework] Preparing simulator library..."
DEVICE_LIB="target/aarch64-apple-ios/$TARGET_SUBDIR/lib${LIB_NAME}.a"
SIM_ARM64_LIB="target/aarch64-apple-ios-sim/$TARGET_SUBDIR/lib${LIB_NAME}.a"

for lib in "$DEVICE_LIB" "$SIM_ARM64_LIB"; do
  if [[ ! -f "$lib" ]]; then
    echo "Error: built library not found at $lib" >&2
    exit 1
  fi
done

# Create XCFramework
echo "[build-ios-xcframework] Building XCFramework..."
mkdir -p "$OUTPUT_DIR"
XCFW="$OUTPUT_DIR/$XCFRAMEWORK_NAME.xcframework"

HEADER_ARGS=""
if [[ -n "$HEADER_PATH" ]] && [[ -d "$HEADER_PATH" ]]; then
  HEADER_ARGS="-headers $HEADER_PATH"
fi

# shellcheck disable=SC2086
xcodebuild -create-xcframework \
  -library "$DEVICE_LIB" \
  $HEADER_ARGS \
  -library "$SIM_ARM64_LIB" \
  $HEADER_ARGS \
  -output "$XCFW"

echo "[build-ios-xcframework] Created XCFramework: $XCFW"

# Zip the XCFramework
echo "[build-ios-xcframework] Zipping XCFramework..."
XCFW_ZIP="$OUTPUT_DIR/$XCFRAMEWORK_NAME.xcframework.zip"
(cd "$OUTPUT_DIR" && zip -r "$XCFRAMEWORK_NAME.xcframework.zip" "$XCFRAMEWORK_NAME.xcframework")
echo "[build-ios-xcframework] Created archive: $XCFW_ZIP"

# Compute checksum for SPM
echo "[build-ios-xcframework] Computing checksum..."
CHECKSUM=$(swift package compute-checksum "$XCFW_ZIP")
echo "[build-ios-xcframework] Checksum: $CHECKSUM"

# Emit outputs
write_github_output "xcframework-path" "$(cd "$OUTPUT_DIR" && pwd)/$XCFRAMEWORK_NAME.xcframework"
write_github_output "xcframework-zip" "$(cd "$OUTPUT_DIR" && pwd)/$XCFRAMEWORK_NAME.xcframework.zip"
write_github_output "checksum" "$CHECKSUM"

echo "[build-ios-xcframework] Done!"
