#!/bin/bash
# Usage: verify-tap-push.sh <tap-repo> <formulas> <version>
# contains the expected version string, proving the push succeeded
# and RC versions are properly accessible.

set -euo pipefail

TAP_REPO="${1:-}"
FORMULAS="${2:-}"
VERSION="${3:-}"

if [[ -z "$TAP_REPO" || -z "$FORMULAS" || -z "$VERSION" ]]; then
	echo "::error::Usage: verify-tap-push.sh <tap-repo> <formulas> <version>"
	exit 1
fi

echo "Verifying Homebrew tap push for $VERSION..."
echo "Tap repo: $TAP_REPO"
echo "Formulas: $FORMULAS"

VERIFY_DIR=$(mktemp -d)
trap 'rm -rf "$VERIFY_DIR"' EXIT

echo "Cloning tap repository for verification..."
git clone --depth=1 "https://github.com/${TAP_REPO}.git" "$VERIFY_DIR" 2>&1 | grep -v "warning:"

while IFS= read -r formula_name; do
	[[ -z "$formula_name" ]] && continue
	formula_file="$VERIFY_DIR/Formula/${formula_name}.rb"

	if [[ ! -f "$formula_file" ]]; then
		echo "::error::Formula file not found after push: $formula_file"
		exit 1
	fi

	if ! grep -q "version \"${VERSION}\"" "$formula_file"; then
		echo "::error::Formula $formula_name does not contain version $VERSION"
		echo "File contents:"
		cat "$formula_file"
		exit 1
	fi

	echo "✓ $formula_name contains version $VERSION"
done <<<"$FORMULAS"

echo "✓ Tap push verification succeeded — all formulas contain the correct version"
