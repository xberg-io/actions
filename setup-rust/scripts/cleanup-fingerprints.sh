#!/usr/bin/env bash
set -euo pipefail

echo "=== Cleaning Cargo Fingerprints ==="

echo "Cleaning general Cargo state..."

if [ -d "target/.cargo-ok" ]; then
	rm -rf target/.cargo-ok
	echo "  Removed target/.cargo-ok"
fi

if [ -d "target/incremental" ]; then
	rm -rf target/incremental
	echo "  Removed incremental compilation cache"
fi

for profile in debug release; do
	if [ -d "target/$profile/incremental" ]; then
		rm -rf "target/$profile/incremental"
		echo "  Removed $profile incremental cache"
	fi
done

for target_dir in target/*/; do
	if [ -d "${target_dir}incremental" ]; then
		rm -rf "${target_dir}incremental"
		echo "  Removed ${target_dir}incremental"
	fi
done

if [[ "${RUNNER_OS:-}" == "Windows" ]] || [[ "${OS:-}" == "Windows_NT" ]]; then
	echo "Detected Windows platform - performing Windows-specific cleanup..."

	if [ -d ~/.cargo/registry/index ]; then
		rm -rf ~/.cargo/registry/index
		echo "  Removed cargo registry index"
	fi

	rm -f ~/.cargo/registry/cache/.cargo-ok 2>/dev/null || true
	echo "  Removed registry cache marker"

	echo "  Forcing cargo to rebuild registry state..."
	cargo metadata --quiet 2>/dev/null || true
fi

if [ -d "target" ]; then
	find target -name ".cargo-ok" -delete 2>/dev/null || true
	find target -type f -name "*.json" -path "*fingerprint*" -delete 2>/dev/null || true
	echo "  Cleaned fingerprint metadata"
fi

echo "Verifying Cargo state..."
if ! cargo --version &>/dev/null; then
	echo "ERROR: Cargo is broken after cleanup!"
	exit 1
fi

echo "Fingerprint cleanup completed successfully"
