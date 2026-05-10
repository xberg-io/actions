#!/usr/bin/env bash
set -euo pipefail

target="${1:?target required}"
echo "Checking Rust target: $target"

if rustup target list | grep -q "^$target (installed)"; then
  echo "Target $target is already installed"
else
  echo "Installing target: $target"
  rustup target add "$target" || {
    echo "Failed to install target $target"
    echo "Available targets:"
    rustup target list | head -20
    exit 1
  }
  echo "Successfully installed target: $target"
fi

rustup target list | grep "$target"

# Install musl-tools and configure cc-rs env vars for musl targets on Linux
if [[ "$target" == *"-unknown-linux-musl" ]] && [[ "$RUNNER_OS" == "Linux" ]]; then
  echo "Installing musl-tools for target: $target"
  sudo apt-get update && sudo apt-get install -y musl-tools

  # Convert target triple to cc-rs environment variable format
  # e.g., aarch64-unknown-linux-musl -> aarch64_unknown_linux_musl
  cc_rs_var=$(echo "$target" | tr '-' '_')

  # Export environment variables for cc-rs
  echo "Configuring cc-rs environment variables for musl target"
  {
    echo "CC_${cc_rs_var}=musl-gcc"
    echo "AR_${cc_rs_var}=ar"
    echo "CARGO_TARGET_${cc_rs_var^^}_LINKER=musl-gcc"
  } >>"$GITHUB_ENV"

  echo "Set CC_${cc_rs_var}=musl-gcc"
  echo "Set AR_${cc_rs_var}=ar"
  echo "Set CARGO_TARGET_${cc_rs_var^^}_LINKER=musl-gcc"
fi
