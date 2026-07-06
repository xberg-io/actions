#!/usr/bin/env bash
# Test script for build-swift-artifactbundle action's substitution feature
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ACTION_PATH="$SCRIPT_DIR/build-swift-artifactbundle"
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# Test 1: Substitute single __ALEF_SWIFT_CHECKSUM__ placeholder
test_substitute_checksum() {
	local test_name="$1"
	local input="$2"
	local expected="$3"

	# Create a temporary Package.swift
	local pkg_path="$TEMP_DIR/Package.swift"
	echo "$input" >"$pkg_path"

	# Simulate what the action does
	local checksum="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
	sed -i.bak "s/__ALEF_SWIFT_CHECKSUM__/$checksum/g" "$pkg_path"
	rm -f "${pkg_path}.bak"

	# Read result
	local result
	result=$(cat "$pkg_path")

	if [[ "$result" == "$expected" ]]; then
		echo "✓ $test_name"
		return 0
	else
		echo "✗ $test_name"
		echo "  Expected: $expected"
		echo "  Got: $result"
		return 1
	fi
}

# Test 2: Checksum in binary target declaration
test_substitute_checksum \
	"checksum placeholder in binaryTarget" \
	'let package = Package(targets: [.binaryTarget(name: "Html2Md", url: "https://example.com/bundle.zip", checksum: "__ALEF_SWIFT_CHECKSUM__")])' \
	'let package = Package(targets: [.binaryTarget(name: "Html2Md", url: "https://example.com/bundle.zip", checksum: "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6")])'

# Test 3: Substitute checksum + version placeholders together
test_substitute_checksum_and_version() {
	local test_name="$1"
	local input="$2"
	local expected="$3"

	local pkg_path="$TEMP_DIR/Package.swift.multi"
	echo "$input" >"$pkg_path"

	local checksum="checksumvalue123456789"
	local version="0.3.0-rc.52"
	# Match the action's two sed invocations: checksum first, then version
	# (with the `v` prefix baked in to match `v__ALEF_SWIFT_VERSION__`).
	sed -i.bak "s/__ALEF_SWIFT_CHECKSUM__/$checksum/g" "$pkg_path"
	sed -i.bak "s|v__ALEF_SWIFT_VERSION__|v${version}|g" "$pkg_path"
	rm -f "${pkg_path}.bak"

	local result
	result=$(cat "$pkg_path")

	if [[ "$result" == "$expected" ]]; then
		echo "✓ $test_name"
		return 0
	else
		echo "✗ $test_name"
		echo "  Expected: $expected"
		echo "  Got: $result"
		return 1
	fi
}

test_substitute_checksum_and_version \
	"checksum + version placeholders" \
	'checksum: "__ALEF_SWIFT_CHECKSUM__", url: "https://example.com/releases/v__ALEF_SWIFT_VERSION__/bundle.zip"' \
	'checksum: "checksumvalue123456789", url: "https://example.com/releases/v0.3.0-rc.52/bundle.zip"'

# Test 4: File not found error
test_file_not_found() {
	local nonexistent="$TEMP_DIR/does_not_exist/Package.swift"
	if [[ -f "$nonexistent" ]]; then
		echo "✗ file not found test setup failed"
		return 1
	fi

	local checksum="abc123"
	if sed -i.bak "s/__ALEF_SWIFT_CHECKSUM__/$checksum/g" "$nonexistent" 2>/dev/null; then
		echo "✗ file not found test (sed should have failed)"
		return 1
	else
		echo "✓ file not found test (sed correctly failed)"
		return 0
	fi
}

test_file_not_found

echo ""
echo "All bash tests completed"
