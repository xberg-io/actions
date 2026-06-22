#!/bin/bash
# Build a Rust crate out-of-workspace to avoid Cargo `links` conflicts.
# Usage: build-out-of-workspace.sh <crate-name> <lib-name> <workspace-root>

set -euo pipefail

CRATE_NAME="$1"
LIB_NAME="$2"
WORKSPACE_ROOT="$3"

# Resolve crate directory (try crates/ first, then packages/)
CRATE_DIR="${WORKSPACE_ROOT}/crates/${CRATE_NAME}"
if [ ! -d "$CRATE_DIR" ]; then
  CRATE_DIR="${WORKSPACE_ROOT}/packages/${CRATE_NAME}"
fi

if [ ! -d "$CRATE_DIR" ]; then
  echo "Error: crate directory not found at $CRATE_DIR" >&2
  exit 1
fi

# Create temp directory for out-of-workspace build.
BUILD_TEMP=$(mktemp -d)
trap 'rm -rf "$BUILD_TEMP"' EXIT

# Copy crate to temp dir.
cp -r "$CRATE_DIR" "$BUILD_TEMP/crate"
cd "$BUILD_TEMP/crate"

# Strip workspace inheritance to avoid cross-workspace dep conflicts.
if grep -q 'workspace = true' Cargo.toml 2>/dev/null; then
  # Read workspace.package values from root Cargo.toml.
  ws_version=""
  ws_edition=""
  ws_license=""

  if grep -q "^\[workspace\.package\]" "$WORKSPACE_ROOT/Cargo.toml"; then
    # Extract values after [workspace.package]
    ws_section=$(sed -n '/^\[workspace\.package\]/,/^\[/p' "$WORKSPACE_ROOT/Cargo.toml" | head -n -1)
    ws_version=$(echo "$ws_section" | grep "^version" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
    ws_edition=$(echo "$ws_section" | grep "^edition" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
    ws_license=$(echo "$ws_section" | grep "^license" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
  fi

  # Replace workspace = true lines with explicit values.
  sed -i.bak \
    -e '/^edition = /d' \
    -e '/^version = /d' \
    -e '/^license = /d' \
    -e 's/workspace = true//' \
    Cargo.toml

  # Add back explicit values if we found them.
  if [ -n "$ws_version" ] && ! grep -q "^version =" Cargo.toml; then
    sed -i.bak "s/^\[package\]/[package]\nversion = \"$ws_version\"/" Cargo.toml
  fi
  if [ -n "$ws_edition" ] && ! grep -q "^edition =" Cargo.toml; then
    sed -i.bak "s/^\[package\]/[package]\nedition = \"$ws_edition\"/" Cargo.toml
  fi
  if [ -n "$ws_license" ] && ! grep -q "^license =" Cargo.toml; then
    sed -i.bak "s/^\[package\]/[package]\nlicense = \"$ws_license\"/" Cargo.toml
  fi

  rm -f Cargo.toml.bak
  echo "Stripped workspace inheritance from binding crate Cargo.toml"
fi

# Seed lockfile from workspace so transitive deps stay pinned at the versions
# the workspace lock froze. Without this seed, the lockfile this temp crate
# ships to consumers would resolve every dep to the latest semver-compatible
# version (e.g. broken `brotli-decompressor 5.0.1` over the pinned `5.0.0`).
if [ -f "$WORKSPACE_ROOT/Cargo.lock" ]; then
  cp "$WORKSPACE_ROOT/Cargo.lock" Cargo.lock
fi

# Generate fresh lockfile for out-of-workspace build. With the seed above
# present, cargo's `resolve_with_previous` reuses every entry that still
# satisfies the (workspace-stripped) manifest; only newly-needed entries are
# resolved against the registry.
cargo generate-lockfile

# Pin `time` to 0.3.47 to avoid the trait-impl conflict between `time` 0.3.48
# and `cookie` 0.18.1 (E0119: conflicting `From<HourBase>` for `ModifierValue::Type`).
# `|| true` covers the case where `time` is not in the resolved graph.
cargo update -p time --precise 0.3.47 || true

# Build the crate.
cargo build --locked --release

# Copy built artifact back to workspace target dir.
mkdir -p "$WORKSPACE_ROOT/target/release"

# Determine OS and copy appropriate artifact.
if [[ "${RUNNER_OS:-}" == "macOS" ]] || [[ "$(uname)" == "Darwin" ]]; then
  cp "$BUILD_TEMP/crate/target/release/lib${LIB_NAME}.dylib" "$WORKSPACE_ROOT/target/release/"
  echo "$WORKSPACE_ROOT/target/release/lib${LIB_NAME}.dylib"
else
  cp "$BUILD_TEMP/crate/target/release/lib${LIB_NAME}.so" "$WORKSPACE_ROOT/target/release/"
  echo "$WORKSPACE_ROOT/target/release/lib${LIB_NAME}.so"
fi
