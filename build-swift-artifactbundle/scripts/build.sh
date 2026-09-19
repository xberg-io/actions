#!/usr/bin/env bash
set -euo pipefail

CRATE_NAME="${INPUT_CRATE_NAME:-xberg-swift}"
LIB_NAME="${INPUT_LIB_NAME:-}"
ARTIFACT_NAME="${INPUT_ARTIFACT_NAME:-}"
BINARY_TARGET_NAME="${INPUT_BINARY_TARGET_NAME:-}"
HEADER_PATH="${INPUT_HEADER_PATH:-}"
OUTPUT_DIR="${INPUT_OUTPUT_DIR:-dist/swift-artifactbundle}"
BUILD_PROFILE="${INPUT_BUILD_PROFILE:-release}"
INCLUDE_MACOS_X86_64="${INPUT_INCLUDE_MACOS_X86_64:-true}"
INCLUDE_IOS_X86_64="${INPUT_INCLUDE_IOS_X86_64:-true}"
# shellcheck disable=SC2034
PACKAGE_MANIFEST_PATH="${INPUT_PACKAGE_MANIFEST_PATH:-}"
DRY_RUN="${INPUT_DRY_RUN:-false}"
# Split-build support. Six targets on one runner overflow the macOS runner disk (see
# prune_target_intermediates below), so the monolithic build had to discard each target's
# cache to fit. Building one triple per job removes both the disk ceiling and the serial
# wall-clock, and keeps the warm cache. ~keep
TARGETS="${INPUT_TARGETS:-}"
PREBUILT_LIBS_DIR="${INPUT_PREBUILT_LIBS_DIR:-}"

if [[ -z "$LIB_NAME" ]]; then
  LIB_NAME="${CRATE_NAME//-/_}"
fi

if [[ -z "$ARTIFACT_NAME" ]]; then
  ARTIFACT_NAME="$(echo "$LIB_NAME" | sed -E 's/(^|_)([a-z])/\U\2/g')"
fi

if [[ -z "$BINARY_TARGET_NAME" ]]; then
  BINARY_TARGET_NAME="$ARTIFACT_NAME"
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
  echo "[dry-run] cargo build --locked -p $CRATE_NAME $profile_flag --target aarch64-apple-darwin"
  if [[ "$INCLUDE_MACOS_X86_64" == "true" ]]; then
    echo "[dry-run] cargo build --locked -p $CRATE_NAME $profile_flag --target x86_64-apple-darwin"
  else
    echo "[dry-run] skip x86_64-apple-darwin (include-macos-x86_64=false)"
  fi
  echo "[dry-run] cargo build --locked -p $CRATE_NAME $profile_flag --target aarch64-apple-ios"
  echo "[dry-run] cargo build --locked -p $CRATE_NAME $profile_flag --target aarch64-apple-ios-sim"
  if [[ "$INCLUDE_IOS_X86_64" == "true" ]]; then
    echo "[dry-run] cargo build --locked -p $CRATE_NAME $profile_flag --target x86_64-apple-ios"
    echo "[dry-run] lipo arm64-sim x86_64 -> ios-sim fat"
  else
    echo "[dry-run] skip x86_64-apple-ios (include-ios-x86_64=false) — ios-sim uses arm64 only"
  fi
  echo "[dry-run] cargo zigbuild --locked -p $CRATE_NAME $profile_flag --target aarch64-unknown-linux-gnu"
  echo "[dry-run] cargo zigbuild --locked -p $CRATE_NAME $profile_flag --target x86_64-unknown-linux-gnu"
  echo "[dry-run] would assemble $OUTPUT_DIR/$ARTIFACT_NAME.artifactbundle"
  echo "[dry-run] would generate info.json with SE-0305 metadata"
  if [[ -n "$HEADER_PATH" ]]; then
    echo "[dry-run] would copy headers from $HEADER_PATH"
  fi
  echo "[dry-run] would zip to $OUTPUT_DIR/$ARTIFACT_NAME.artifactbundle.zip"
  echo "[dry-run] would compute checksum via swift package compute-checksum"
  exit 0
fi

# The full target set, in the order the bundle expects them. `should_build` narrows it when
# the caller asked for a subset (one job per triple); with TARGETS empty every triple is
# built, which is the original single-job behaviour. ~keep
ALL_TARGETS="aarch64-apple-darwin x86_64-apple-darwin aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios aarch64-unknown-linux-gnu x86_64-unknown-linux-gnu"

should_build() {
  local triple="$1"
  [[ -n "$PREBUILT_LIBS_DIR" ]] && return 1
  [[ -z "$TARGETS" ]] && return 0
  local wanted
  for wanted in ${TARGETS//,/ }; do
    [[ "$wanted" == "$triple" ]] && return 0
  done
  return 1
}

# Where a finished static library lives. In assemble mode the libraries were produced by
# other jobs and downloaded, so they come from a staging directory instead of the cargo
# target tree. Every copy below goes through this, so the two modes cannot drift. ~keep
lib_for() {
  local triple="$1"
  if [[ -n "$PREBUILT_LIBS_DIR" ]]; then
    echo "$PREBUILT_LIBS_DIR/$triple/lib${LIB_NAME}.a"
  else
    echo "$target_dir/$triple/$target_subdir/lib${LIB_NAME}.a"
  fi
}

# Assemble mode compiles nothing, so installing toolchains would be pure cost --
# `cargo install cargo-zigbuild` alone can run for minutes. In build-only mode install
# only what the requested triples actually need. ~keep
if [[ -n "$PREBUILT_LIBS_DIR" ]]; then
  echo "=== Assemble mode: skipping Rust target and Zig installation ==="
else
  echo "=== Adding Rust targets ==="
  apple_targets=(aarch64-apple-darwin aarch64-apple-ios aarch64-apple-ios-sim)
  if [[ "$INCLUDE_MACOS_X86_64" == "true" ]]; then
    apple_targets+=(x86_64-apple-darwin)
  fi
  if [[ "$INCLUDE_IOS_X86_64" == "true" ]]; then
    apple_targets+=(x86_64-apple-ios)
  fi
  wanted_targets=()
  for candidate in "${apple_targets[@]}" aarch64-unknown-linux-gnu x86_64-unknown-linux-gnu; do
    if should_build "$candidate"; then
      wanted_targets+=("$candidate")
    fi
  done
  if [[ ${#wanted_targets[@]} -gt 0 ]]; then
    rustup target add "${wanted_targets[@]}"
  fi

  # Zig is only the cross-linker for the Linux triples; an Apple-only job does not need it.
  needs_zig=false
  for candidate in aarch64-unknown-linux-gnu x86_64-unknown-linux-gnu; do
    if should_build "$candidate"; then
      needs_zig=true
    fi
  done
  if [[ "$needs_zig" == "true" ]]; then
    echo "=== Ensuring cargo-zigbuild + Zig are installed ==="
    if ! command -v zig >/dev/null 2>&1; then
      if command -v brew >/dev/null 2>&1; then
        brew install zig 2>/dev/null || true
      fi
    fi
    if ! command -v cargo-zigbuild >/dev/null 2>&1; then
      cargo install --locked cargo-zigbuild 2>/dev/null || true
    fi
  else
    echo "=== No Linux target requested; skipping Zig installation ==="
  fi
fi

mkdir -p "$OUTPUT_DIR"
bundle_dir="$OUTPUT_DIR/$ARTIFACT_NAME.artifactbundle"
# Only materialise the bundle directory on a path that will actually assemble one.
# A build-only job that left an empty `.artifactbundle` behind would publish something
# indistinguishable from a real bundle to anything globbing for it. ~keep
if [[ -z "$TARGETS" || -n "$PREBUILT_LIBS_DIR" ]]; then
  rm -rf "$bundle_dir"
  mkdir -p "$bundle_dir"
fi

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

# Six targets are built back to back and every one leaves a full per-target tree behind. On a
# hosted macOS runner the sum overflows the disk before the copy step -- an observed failure was
# `fcopyfile failed: No space left on device` on the third archive, with 1258 sccache write
# errors just before it. Only `lib<name>.a`, which sits directly in the profile directory, is
# needed after a target is built, so drop that target's intermediates as soon as it finishes.
# This trades some warm-cache reuse for a build that fits. ~keep
prune_target_intermediates() {
  local triple="$1"
  local dir="$target_dir/$triple/$target_subdir"
  if [[ ! -d "$dir" ]]; then
    echo "  no build directory for $triple at $dir; nothing to prune"
    return 0
  fi
  rm -rf "$dir/deps" "$dir/build" "$dir/incremental" "$dir/examples"
  echo "  pruned intermediates for $triple; free space now:"
  df -h "$target_dir" | tail -1
}

# `df` exits non-zero on a path that does not exist, and under `set -euo pipefail` that
# aborts the job before a single target is built. The target directory is created by the
# first cargo invocation, so it is absent here whenever no cache restored it. A disk-space
# diagnostic must not decide whether the build runs. ~keep
mkdir -p "$target_dir"
echo "=== Disk space before building ==="
df -h "$target_dir" | tail -1

echo "=== Building Apple targets ==="
if should_build aarch64-apple-darwin; then
  echo "Building aarch64-apple-darwin..."
  # shellcheck disable=SC2086
  cargo build --locked -p "$CRATE_NAME" $profile_flag --target aarch64-apple-darwin
  prune_target_intermediates aarch64-apple-darwin
fi

if [[ "$INCLUDE_MACOS_X86_64" == "true" ]] && should_build x86_64-apple-darwin; then
  echo "Building x86_64-apple-darwin..."
  # shellcheck disable=SC2086
  cargo build --locked -p "$CRATE_NAME" $profile_flag --target x86_64-apple-darwin
  prune_target_intermediates x86_64-apple-darwin
else
  echo "Skipping x86_64-apple-darwin (include-macos-x86_64=false)"
fi

if should_build aarch64-apple-ios; then
  echo "Building aarch64-apple-ios..."
  # shellcheck disable=SC2086
  cargo build --locked -p "$CRATE_NAME" $profile_flag --target aarch64-apple-ios
  prune_target_intermediates aarch64-apple-ios
fi

if should_build aarch64-apple-ios-sim; then
  echo "Building aarch64-apple-ios-sim..."
  # shellcheck disable=SC2086
  cargo build --locked -p "$CRATE_NAME" $profile_flag --target aarch64-apple-ios-sim
  prune_target_intermediates aarch64-apple-ios-sim
fi

if [[ "$INCLUDE_IOS_X86_64" == "true" ]] && should_build x86_64-apple-ios; then
  echo "Building x86_64-apple-ios..."
  # shellcheck disable=SC2086
  cargo build --locked -p "$CRATE_NAME" $profile_flag --target x86_64-apple-ios
  prune_target_intermediates x86_64-apple-ios
else
  echo "Skipping x86_64-apple-ios (include-ios-x86_64=false)"
fi

echo "=== Building Linux targets (cargo-zigbuild) ==="

if should_build aarch64-unknown-linux-gnu; then
  echo "Building aarch64-unknown-linux-gnu..."
  # shellcheck disable=SC2086
  cargo zigbuild --locked -p "$CRATE_NAME" $profile_flag --target aarch64-unknown-linux-gnu
  prune_target_intermediates aarch64-unknown-linux-gnu
fi
if should_build x86_64-unknown-linux-gnu; then
  echo "Building x86_64-unknown-linux-gnu..."
  # shellcheck disable=SC2086
  cargo zigbuild --locked -p "$CRATE_NAME" $profile_flag --target x86_64-unknown-linux-gnu
  prune_target_intermediates x86_64-unknown-linux-gnu
fi
# Build-only mode: the caller asked for a subset of triples, so this job's job is done.
# Stage each library under a flat <triple>/ layout and stop -- a later assemble job
# downloads every job's staging directory and passes it as prebuilt-libs-dir. Assembling
# here would be wrong: the other triples do not exist in this job. ~keep
if [[ -n "$TARGETS" && -z "$PREBUILT_LIBS_DIR" ]]; then
  libs_dir="$OUTPUT_DIR/libs"
  rm -rf "$libs_dir"
  for triple in ${TARGETS//,/ }; do
    built="$target_dir/$triple/$target_subdir/lib${LIB_NAME}.a"
    if [[ ! -f "$built" ]]; then
      echo "error: $triple produced no lib${LIB_NAME}.a at $built" >&2
      exit 1
    fi
    mkdir -p "$libs_dir/$triple"
    cp "$built" "$libs_dir/$triple/lib${LIB_NAME}.a"
    echo "staged $triple -> $libs_dir/$triple/lib${LIB_NAME}.a"
  done
  echo "libs-dir=$libs_dir" >>"$GITHUB_OUTPUT"
  echo "Build-only mode complete for: $TARGETS"
  exit 0
fi

echo "=== Creating artifact bundle structure ==="
mkdir -p "$bundle_dir/$ARTIFACT_NAME-macos-arm64"
if [[ "$INCLUDE_MACOS_X86_64" == "true" ]]; then
  mkdir -p "$bundle_dir/$ARTIFACT_NAME-macos-x86_64"
fi
mkdir -p "$bundle_dir/$ARTIFACT_NAME-ios-arm64"
mkdir -p "$bundle_dir/$ARTIFACT_NAME-ios-sim"
mkdir -p "$bundle_dir/$ARTIFACT_NAME-linux-x86_64"
mkdir -p "$bundle_dir/$ARTIFACT_NAME-linux-aarch64"

echo "=== Copying static libraries ==="
cp "$(lib_for aarch64-apple-darwin)" \
  "$bundle_dir/$ARTIFACT_NAME-macos-arm64/lib${LIB_NAME}.a"

if [[ "$INCLUDE_MACOS_X86_64" == "true" ]]; then
  cp "$(lib_for x86_64-apple-darwin)" \
    "$bundle_dir/$ARTIFACT_NAME-macos-x86_64/lib${LIB_NAME}.a"
fi

cp "$(lib_for aarch64-apple-ios)" \
  "$bundle_dir/$ARTIFACT_NAME-ios-arm64/lib${LIB_NAME}.a"

if [[ "$INCLUDE_IOS_X86_64" == "true" ]]; then
  cp "$(lib_for aarch64-apple-ios-sim)" \
    "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.arm64"
  cp "$(lib_for x86_64-apple-ios)" \
    "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.x86_64"
  echo "=== Creating iOS simulator fat library ==="
  lipo -create \
    "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.arm64" \
    "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.x86_64" \
    -output "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a"
  rm "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.arm64" \
    "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a.x86_64"
else
  cp "$(lib_for aarch64-apple-ios-sim)" \
    "$bundle_dir/$ARTIFACT_NAME-ios-sim/lib${LIB_NAME}.a"
fi

cp "$(lib_for aarch64-unknown-linux-gnu)" \
  "$bundle_dir/$ARTIFACT_NAME-linux-aarch64/lib${LIB_NAME}.a"

cp "$(lib_for x86_64-unknown-linux-gnu)" \
  "$bundle_dir/$ARTIFACT_NAME-linux-x86_64/lib${LIB_NAME}.a"

if [[ -n "$HEADER_PATH" && -d "$HEADER_PATH" ]]; then
  echo "=== Copying headers from $HEADER_PATH ==="
  mkdir -p "$bundle_dir/$ARTIFACT_NAME-headers"
  cp -r "$HEADER_PATH"/* "$bundle_dir/$ARTIFACT_NAME-headers/"
fi

echo "=== Generating info.json ==="
variants=()
variants+=("$(printf '{"path": "%s-macos-arm64/lib%s.a", "supportedTriples": ["arm64-apple-macosx"]}' "$ARTIFACT_NAME" "$LIB_NAME")")
if [[ "$INCLUDE_MACOS_X86_64" == "true" ]]; then
  variants+=("$(printf '{"path": "%s-macos-x86_64/lib%s.a", "supportedTriples": ["x86_64-apple-macosx"]}' "$ARTIFACT_NAME" "$LIB_NAME")")
fi
variants+=("$(printf '{"path": "%s-ios-arm64/lib%s.a", "supportedTriples": ["arm64-apple-ios"]}' "$ARTIFACT_NAME" "$LIB_NAME")")
if [[ "$INCLUDE_IOS_X86_64" == "true" ]]; then
  variants+=("$(printf '{"path": "%s-ios-sim/lib%s.a", "supportedTriples": ["arm64-apple-ios-simulator", "x86_64-apple-ios-simulator"]}' "$ARTIFACT_NAME" "$LIB_NAME")")
else
  variants+=("$(printf '{"path": "%s-ios-sim/lib%s.a", "supportedTriples": ["arm64-apple-ios-simulator"]}' "$ARTIFACT_NAME" "$LIB_NAME")")
fi
variants+=("$(printf '{"path": "%s-linux-x86_64/lib%s.a", "supportedTriples": ["x86_64-unknown-linux-gnu"]}' "$ARTIFACT_NAME" "$LIB_NAME")")
variants+=("$(printf '{"path": "%s-linux-aarch64/lib%s.a", "supportedTriples": ["aarch64-unknown-linux-gnu"]}' "$ARTIFACT_NAME" "$LIB_NAME")")

variants_csv=$(
  IFS=,
  echo "${variants[*]}"
)
cat >"$bundle_dir/info.json" <<EOF
{
  "schemaVersion": "1.0",
  "artifacts": {
    "$BINARY_TARGET_NAME": {
      "type": "staticLibrary",
      "version": "1.0.0",
      "variants": [$variants_csv]
    }
  }
}
EOF

echo "Created $bundle_dir/info.json"

echo "=== Creating zip archive ==="
pushd "$OUTPUT_DIR" >/dev/null
zip -r "${ARTIFACT_NAME}.artifactbundle.zip" "${ARTIFACT_NAME}.artifactbundle"
popd >/dev/null

bundle_zip="$OUTPUT_DIR/${ARTIFACT_NAME}.artifactbundle.zip"
echo "Created $bundle_zip"

echo "=== Computing checksum ==="
checksum=$(swift package compute-checksum "$bundle_zip" 2>/dev/null ||
  shasum -a 256 "$bundle_zip" | awk '{print $1}')
echo "Checksum: $checksum"

{
  echo "bundle-path=$bundle_dir"
  echo "bundle-zip=$bundle_zip"
  echo "checksum=$checksum"
} >>"$GITHUB_OUTPUT"

echo "Artifact bundle complete"
