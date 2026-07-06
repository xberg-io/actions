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

# Strip relative internal `path = "..."` deps from an isolated crate's Cargo.toml,
# keeping the `version` key so they resolve from the registry. rewrite-native-deps
# is supposed to do this in the workspace, but if it left a path (e.g. the core
# crate was not yet on the registry) the isolated tree — which only copies the
# package + binding crate, not the core crate — would reference a sibling dir that
# does not exist and cargo bails with `failed to read .../crates/<core>/Cargo.toml`.
# No-op when rewrite-native-deps already removed the path. Scoped strictly to
# *dependencies* sections so [lib]/[[bin]] `path` keys are never touched.
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
		# Split layout: python sources live in the package dir, the Rust crate lives
		# elsewhere (pyproject's [tool.maturin] manifest-path). Building in place lets
		# cargo climb to the repo-root workspace, which drags every sibling member
		# into `cargo metadata`. If two members declare the same `links` value (e.g. a
		# core crate path-deps a `links`-bearing native crate while the binding crate
		# pins the same crate to a registry version), cargo aborts with a duplicate
		# `links` conflict. Instead, assemble an isolated workspace tree containing
		# only the package dir + the crate, rooted at a synthetic [workspace] whose
		# sole member is the binding crate — sibling members never enter the graph.
		echo "Split layout detected; isolating $FULL_PACKAGE_DIR + crate into a single-member workspace"
		if [[ ! "$OUTPUT_DIR" =~ ^/ ]]; then
			abs_output_dir="$WORKSPACE_ROOT/$OUTPUT_DIR"
		else
			abs_output_dir="$OUTPUT_DIR"
		fi

		# Resolve the crate directory from pyproject's [tool.maturin] manifest-path.
		rel_manifest=$(sed -n 's/^[[:space:]]*manifest-path[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
			"$FULL_PACKAGE_DIR/pyproject.toml" | head -1)
		if [ -z "$rel_manifest" ]; then
			echo "Error: split layout but no [tool.maturin] manifest-path in $FULL_PACKAGE_DIR/pyproject.toml" >&2
			exit 1
		fi
		CRATE_DIR=$(cd "$FULL_PACKAGE_DIR" && cd "$(dirname "$rel_manifest")" && pwd)

		# Preserve each tree's path relative to the workspace root so the pyproject
		# manifest-path (e.g. ../../crates/<name>/Cargo.toml) still resolves.
		pkg_rel=$(python3 -c "import os,sys;print(os.path.relpath(sys.argv[1],sys.argv[2]))" "$FULL_PACKAGE_DIR" "$WORKSPACE_ROOT")
		crate_rel=$(python3 -c "import os,sys;print(os.path.relpath(sys.argv[1],sys.argv[2]))" "$CRATE_DIR" "$WORKSPACE_ROOT")

		ISO="$BUILD_TEMP/iso"
		mkdir -p "$ISO/$(dirname "$pkg_rel")" "$ISO/$(dirname "$crate_rel")"
		cp -r "$FULL_PACKAGE_DIR" "$ISO/$pkg_rel"
		cp -r "$CRATE_DIR" "$ISO/$crate_rel"
		# The core crate is deliberately NOT copied into the isolated tree; drop any
		# residual internal path-dep so the binding crate resolves it from the registry.
		strip_internal_paths "$ISO/$crate_rel/Cargo.toml"

		# Synthesize the isolated workspace root. Carry over [workspace.package] and
		# [workspace.dependencies] so any `field.workspace = true` /
		# `dep = { workspace = true }` inheritance still resolves, but strip `path =`
		# from the workspace deps so inherited internal crates resolve from their
		# registry version key instead of climbing out of the isolated tree.
		python3 - "$WORKSPACE_ROOT/Cargo.toml" "$ISO/Cargo.toml" "$crate_rel" <<'PY'
import re, sys

src, dst, member = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(src).read()


def section(name):
    m = re.search(r'(?m)^\[' + re.escape(name) + r'\][ \t]*$', text)
    if not m:
        return ''
    start = m.end()
    nxt = re.search(r'(?m)^\[', text[start:])
    return text[start: start + nxt.start()] if nxt else text[start:]


pkg = section('workspace.package')
deps = section('workspace.dependencies')
# Drop `path = "..."` (with any adjacent comma) — the version key remains, so
# inherited internal crates resolve from the registry.
deps = re.sub(r'path[ \t]*=[ \t]*"[^"]*"[ \t]*,[ \t]*', '', deps)
deps = re.sub(r'[ \t]*,?[ \t]*path[ \t]*=[ \t]*"[^"]*"', '', deps)

out = ['[workspace]', 'resolver = "2"', f'members = ["{member}"]', '']
if pkg.strip():
    out += ['[workspace.package]', pkg.strip('\n'), '']
if deps.strip():
    out += ['[workspace.dependencies]', deps.strip('\n'), '']
open(dst, 'w').write('\n'.join(out) + '\n')
PY

		# Seed the lockfile from the workspace so transitive pins survive, then
		# reconcile against the single-member manifest.
		if [ -f "$WORKSPACE_ROOT/Cargo.lock" ]; then
			cp "$WORKSPACE_ROOT/Cargo.lock" "$ISO/Cargo.lock"
		fi
		(cd "$ISO" && (cargo generate-lockfile || {
			rm -f Cargo.lock
			cargo generate-lockfile
		}))

		cd "$ISO/$pkg_rel"
		# No -m: let the sdist filename derive from pyproject's [project] name so it
		# matches the PyPI Trusted Publisher project (passing -m derives it from the
		# Rust crate name and trips a 400 on publish).
		maturin sdist --out "$abs_output_dir"
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

# Seed lockfile from workspace so transitive deps stay pinned at the versions
# the workspace lock froze. Without this seed, the lockfile that ships inside
# the sdist would resolve every dep to the latest semver-compatible version on
# a consumer's `pip install` (e.g. broken `brotli-decompressor 5.0.1` over the
# pinned `5.0.0`).
if [ -f "$WORKSPACE_ROOT/Cargo.lock" ]; then
	cp "$WORKSPACE_ROOT/Cargo.lock" Cargo.lock
fi

# Drop any residual internal path-dep so a consumer unpacking the sdist resolves
# it from the registry instead of a sibling dir that does not exist off-workspace.
strip_internal_paths Cargo.toml

# Generate fresh lockfile. With the seed above present, cargo's
# `resolve_with_previous` reuses every entry that still satisfies the
# (workspace-stripped) manifest.
cargo generate-lockfile

# Run maturin.
maturin sdist --out "$OUTPUT_DIR"
