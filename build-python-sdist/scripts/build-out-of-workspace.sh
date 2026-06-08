#!/bin/bash
# Build a Python sdist out-of-workspace to avoid Cargo `links` conflicts.
# Usage: build-out-of-workspace.sh <manifest-path-or-package-dir> <output-dir> <workspace-root>

set -euo pipefail

INPUT="${1:-}"
OUTPUT_DIR="${2:-.}"
WORKSPACE_ROOT="${3:-.}"

if [ -z "$INPUT" ]; then
  echo "Error: missing input (manifest-path or package-dir)" >&2
  exit 1
fi

# Create temp directory for out-of-workspace build.
BUILD_TEMP=$(mktemp -d)
trap 'rm -rf "$BUILD_TEMP"' EXIT

WORKSPACE_ROOT="$(cd "$WORKSPACE_ROOT" && pwd)"
mkdir -p "$OUTPUT_DIR"

# Determine if INPUT is a manifest path (file) or package dir.
if [ -f "$WORKSPACE_ROOT/$INPUT" ]; then
  # Manifest path: copy parent directory.
  FULL_MANIFEST_PATH="$WORKSPACE_ROOT/$INPUT"
  PARENT_DIR=$(dirname "$FULL_MANIFEST_PATH")

  cp -r "$PARENT_DIR" "$BUILD_TEMP/crate"
  cd "$BUILD_TEMP/crate"

  echo "Building sdist from manifest: $INPUT"
else
  # Package directory: copy entire directory.
  FULL_PACKAGE_DIR="$WORKSPACE_ROOT/$INPUT"

  if [ ! -d "$FULL_PACKAGE_DIR" ]; then
    echo "Error: input not found at $FULL_PACKAGE_DIR (neither file nor dir)" >&2
    exit 1
  fi

  # Split layout: package dir holds pyproject.toml + py source but the Rust crate
  # lives elsewhere (typical for monorepos: packages/python -> crates/<name>/Cargo.toml
  # via pyproject's [tool.maturin] manifest-path). Out-of-workspace isolation can't
  # work — maturin needs both the python sources and the crate, and they're in
  # different roots. Fall back to in-workspace build from workspace root with the
  # resolved -m manifest-path. rewrite-native-deps already ran in the workspace,
  # so the crate's path-deps are registry deps.
  if [ ! -f "$FULL_PACKAGE_DIR/Cargo.toml" ]; then
    if [ ! -f "$FULL_PACKAGE_DIR/pyproject.toml" ]; then
      echo "Error: $FULL_PACKAGE_DIR has neither Cargo.toml nor pyproject.toml" >&2
      exit 1
    fi
    manifest_rel=$(awk '
      /^\[tool\.maturin\]/ { in_section=1; next }
      /^\[/ { in_section=0 }
      in_section && /^manifest-path[[:space:]]*=/ {
        sub(/^manifest-path[[:space:]]*=[[:space:]]*"/, "")
        sub(/".*$/, "")
        print
        exit
      }
    ' "$FULL_PACKAGE_DIR/pyproject.toml")
    if [ -z "$manifest_rel" ]; then
      echo "Error: no Cargo.toml in $FULL_PACKAGE_DIR and no [tool.maturin] manifest-path in pyproject.toml" >&2
      exit 1
    fi
    resolved_manifest="$(cd "$FULL_PACKAGE_DIR" && cd "$(dirname "$manifest_rel")" && pwd)/$(basename "$manifest_rel")"
    echo "Split layout detected; building sdist in-workspace via -m $resolved_manifest"
    cd "$WORKSPACE_ROOT"
    maturin sdist -m "$resolved_manifest" --out "$OUTPUT_DIR"
    exit 0
  fi

  cp -r "$FULL_PACKAGE_DIR" "$BUILD_TEMP/package"
  cd "$BUILD_TEMP/package"

  echo "Building sdist from package: $INPUT"
fi

# Strip workspace inheritance.
if [ -f Cargo.toml ] && grep -q 'workspace = true' Cargo.toml 2>/dev/null; then
  # Read workspace.package values from root Cargo.toml.
  ws_version=""
  ws_edition=""
  ws_license=""

  if grep -q "^\[workspace\.package\]" "$WORKSPACE_ROOT/Cargo.toml"; then
    ws_section=$(sed -n '/^\[workspace\.package\]/,/^\[/p' "$WORKSPACE_ROOT/Cargo.toml" | head -n -1)
    ws_version=$(echo "$ws_section" | grep "^version" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
    ws_edition=$(echo "$ws_section" | grep "^edition" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
    ws_license=$(echo "$ws_section" | grep "^license" | head -1 | sed 's/.*= *"\([^"]*\)".*/\1/')
  fi

  # Remove workspace = true and conflicting fields.
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

# Generate fresh lockfile.
cargo generate-lockfile

# Run maturin.
maturin sdist --out "$OUTPUT_DIR"
