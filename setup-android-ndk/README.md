# setup-android-ndk

Composite action that prepares a GitHub Actions runner for Rust Android cross-compilation:

1. Resolves a preinstalled Android NDK (autodetect-latest under `$ANDROID_HOME/ndk/`, or explicit version)
2. Exports `ANDROID_NDK_HOME`, `ANDROID_NDK_ROOT`, `NDK_HOME` to subsequent steps via `$GITHUB_ENV`
3. Prepends the NDK host toolchain bin directory (e.g. `<ndk>/toolchains/llvm/prebuilt/linux-x86_64/bin`) to `$GITHUB_PATH`
4. Adds the requested Rust Android targets via `rustup target add`
5. Optionally installs `cargo-ndk`

Designed for reuse across `kreuzberg-dev` Rust libraries with Android binding targets. Assumes a Rust toolchain is already installed (e.g. via `xberg-io/actions/setup-rust@v1`).

## Inputs

| Name | Default | Description |
|------|---------|-------------|
| `ndk-version` | `""` | Specific NDK directory under `$ANDROID_HOME/ndk/`. Empty picks the highest semver-sorted dir. |
| `targets` | `aarch64-linux-android,x86_64-linux-android` | Comma-separated Rust targets to add via `rustup`. |
| `install-cargo-ndk` | `true` | Install `cargo-ndk` (no-op if already present). |
| `cargo-ndk-version` | `""` | Specific `cargo-ndk` version; empty uses the latest stable. |

## Outputs

| Name | Description |
|------|-------------|
| `ndk-home` | Absolute path to the resolved NDK root. |

## Example

```yaml
jobs:
  android-check:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        abi: [arm64-v8a, x86_64]
    steps:
      - uses: actions/checkout@v6
      - uses: xberg-io/actions/setup-rust@v1
      - uses: xberg-io/actions/setup-android-ndk@v1
      - run: cargo ndk --target ${{ matrix.abi }} --platform 21 -- check -p my-crate
```

## Notes

- On GitHub `ubuntu-latest`, the Android SDK is preinstalled at `/usr/local/lib/android/sdk` with `ANDROID_HOME` already set. The action picks the highest NDK version found.
- On macOS (local or self-hosted), the action falls back to `/opt/homebrew/share/android-ndk` (Homebrew Cask) when `ANDROID_HOME` is empty.
- For Rust crates whose build scripts invoke CMake (e.g. tesseract, leptonica, openssl-sys), exporting `ANDROID_NDK_HOME` is critical — CMake's `Android-Determine.cmake` requires it to locate the NDK toolchain file.
