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

# Strip relative internal `path = "..."` deps from the isolated crate's Cargo.toml,
# keeping the `version` key so they resolve from the registry. rewrite-native-deps
# is supposed to do this in the workspace, but if it left a path (e.g. the core
# crate was not yet on the registry) the out-of-workspace crate would reference a
# sibling dir that does not exist and cargo bails with
# `failed to read .../crates/<core>/Cargo.toml`. No-op when rewrite-native-deps
# already removed the path. Scoped strictly to *dependencies* sections so
# [lib]/[[bin]] `path` keys are never touched.
strip_internal_paths() {
	python3 - "$1" <<'PY'
import re, sys
p = sys.argv[1]
lines = open(p).read().splitlines(keepends=True)
dep_hdr = re.compile(r'^\s*\[(build-|dev-)?dependencies(\.[^\]]+)?\]\s*$')
tgt_dep_hdr = re.compile(r'^\s*\[target\.[^\]]+\.(build-|dev-)?dependencies(\.[^\]]+)?\]\s*$')
any_hdr = re.compile(r'^\s*\[')
path_rel = re.compile(r'(,\s*)?path\s*=\s*"(\.[^"]*|[^"]*/[^"]*)"(\s*,)?')
def repl(m):
    return ',' if (m.group(1) and m.group(3)) else ''
in_deps = False
out = []
for ln in lines:
    if any_hdr.match(ln):
        in_deps = bool(dep_hdr.match(ln) or tgt_dep_hdr.match(ln))
    out.append(path_rel.sub(repl, ln) if in_deps and 'path' in ln else ln)
open(p, 'w').write(''.join(out))
PY
}

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

# Drop any residual internal path-dep so the out-of-workspace crate resolves it
# from the registry instead of a sibling dir that does not exist here.
strip_internal_paths Cargo.toml

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
