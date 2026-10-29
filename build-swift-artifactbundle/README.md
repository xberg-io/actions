# build-swift-artifactbundle

Build a Swift Package Manager SE-0305 artifact bundle containing static Rust
libraries for multiple platforms (macOS arm64/x86_64, iOS device/simulator,
Linux arm64/x86_64). The bundle can be distributed via Swift Package Index
as a `.binaryTarget`.

## Overview

This action:

1. Adds required Rust targets for cross-compilation
2. Builds the Rust crate for all Apple platforms (macOS, iOS) using native `cargo`
3. Builds Linux targets using the `cross` CLI
4. Creates a fat binary for iOS simulator (arm64 + x86_64 via `lipo`)
5. Assembles an SE-0305 artifact bundle with `info.json` metadata
6. Zips the bundle and computes a SHA256 checksum

The artifact bundle is suitable for distribution via Swift Package Manager:

```swift
.binaryTarget(name: "MyLib", url: "https://example.com/MyLib.artifactbundle.zip",
              checksum: "abc123...")
```

## Prerequisites

- **macOS runner** (e.g. `macos-26`): required for Apple target compilation
- **Rust setup** (e.g. via `xberg-io/actions/setup-rust@v1`)
- **Cross CLI** installed (action handles this automatically)

## Usage

```yaml
- uses: actions/checkout@v4
- uses: xberg-io/actions/setup-rust@v1
- uses: xberg-io/actions/build-swift-artifactbundle@v1
  with:
    crate-name: my-rust-crate
    lib-name: my_rust_crate
    artifact-name: MyRustLib
```

## Inputs

| Name                       | Required | Default                     | Description                                                               |
| -------------------------- | -------- | --------------------------- | ------------------------------------------------------------------------- |
| `crate-name`               | no       | `xberg-swift`               | Cargo package name.                                                       |
| `lib-name`                 | no       | crate-name with `-` → `_`   | Library base name for the static `.a` file.                               |
| `artifact-name`            | no       | PascalCase of lib-name      | Artifact bundle name without extension.                                   |
| `header-path`              | no       | ``                          | Optional path to C headers directory to embed in bundle.                  |
| `additional-license-files` | no       | ``                          | Newline-separated required notice files relative to the caller workspace. |
| `output-dir`               | no       | `dist/swift-artifactbundle` | Output directory for the artifact bundle.                                 |
| `build-profile`            | no       | `release`                   | Cargo profile (`release`, `dev`, or custom named profile).                |
| `dry-run`                  | no       | `false`                     | Print the planned commands and exit without building.                     |

## Outputs

| Name          | Description                                           |
| ------------- | ----------------------------------------------------- |
| `bundle-path` | Absolute path to the `.artifactbundle` directory.     |
| `bundle-zip`  | Absolute path to the `.artifactbundle.zip` file.      |
| `checksum`    | SHA256 checksum of the artifact bundle zip (for SPM). |

## Additional license files

List required notices on the bundle-assembly job, including when assembling from `prebuilt-libs-dir`:

```yaml
- uses: xberg-io/actions/build-swift-artifactbundle@v1
  with:
    additional-license-files: |
      THIRD_PARTY_LICENSES.md
      licenses/NOTICE.txt
```

The action resolves each path from `GITHUB_WORKSPACE` and preserves its relative path and exact bytes inside the
`.artifactbundle`. It checks the actual ZIP members and bytes before calculating the checksum. Missing, empty,
escaping or colliding files fail the action. Absolute paths, dot/parent components, backslashes and drive prefixes
are rejected; case-insensitive destination collisions are rejected on every host.

Blank lines are ignored and surrounding whitespace is trimmed. An explicitly whitespace-only list fails. Empty
input retains existing behavior. Dry runs describe the files without reading or copying them; split build-only jobs
validate declared files but leave staging and ZIP verification to the final assembly job. Python 3.10 or newer is
required when this input is set.

## Bundle Structure

The artifact bundle is organized by target platform and architecture:

```text
MyRustLib.artifactbundle/
  info.json
  MyRustLib-macos-arm64/libmy_rust_crate.a
  MyRustLib-macos-x86_64/libmy_rust_crate.a
  MyRustLib-ios-arm64/libmy_rust_crate.a
  MyRustLib-ios-sim/libmy_rust_crate.a       (fat: arm64 + x86_64)
  MyRustLib-linux-x86_64/libmy_rust_crate.a
  MyRustLib-linux-aarch64/libmy_rust_crate.a
  MyRustLib-headers/                          (optional)
    - C headers if header-path was provided
```

The `info.json` follows SE-0305 and declares:

- **Artifact name**: matches `artifact-name` input
- **Type**: `staticLibrary`
- **Variants**: per-platform triples and library paths

Example `info.json`:

```json
{
  "schemaVersion": "1.0",
  "artifacts": {
    "MyRustLib": {
      "type": "staticLibrary",
      "version": "1.0.0",
      "variants": [
        {
          "path": "MyRustLib-macos-arm64/libmy_rust_crate.a",
          "supportedTriples": ["arm64-apple-macosx"]
        },
        {
          "path": "MyRustLib-ios-sim/libmy_rust_crate.a",
          "supportedTriples": ["arm64-apple-ios-simulator", "x86_64-apple-ios-simulator"]
        }
      ]
    }
  }
}
```

## Platforms & Targets

| Platform      | Target Triple                 | Library                              |
| ------------- | ----------------------------- | ------------------------------------ |
| macOS         | `aarch64-apple-darwin`        | `aarch64-apple-darwin/libXXX.a`      |
| macOS         | `x86_64-apple-darwin`         | `x86_64-apple-darwin/libXXX.a`       |
| iOS           | `aarch64-apple-ios`           | `aarch64-apple-ios/libXXX.a`         |
| iOS Simulator | `aarch64-apple-ios-simulator` | arm64 component of fat lib           |
| iOS Simulator | `x86_64-apple-ios-simulator`  | x86_64 component of fat lib          |
| Linux         | `aarch64-unknown-linux-gnu`   | `aarch64-unknown-linux-gnu/libXXX.a` |
| Linux         | `x86_64-unknown-linux-gnu`    | `x86_64-unknown-linux-gnu/libXXX.a`  |

## Dry Run

Use the `dry-run: true` input to preview the planned build without actually
compiling:

```yaml
- uses: xberg-io/actions/build-swift-artifactbundle@v1
  with:
    crate-name: my-crate
    dry-run: "true"
```

Output will show the planned cargo/cross commands and bundle assembly steps,
then exit cleanly.

## Notes

- **iOS Simulator**: the action uses `lipo` to create a universal binary
  combining arm64 and x86_64 simulators into a single fat library.
- **Linux targets**: require the `cross` CLI for cross-compilation from macOS.
  The action installs it automatically.
- **Checksum**: computed via `swift package compute-checksum` if available,
  falling back to `shasum -a 256`.
- **Custom profiles**: support named Cargo profiles (e.g. `--profile profiling`).
  The action handles the path lookup automatically.
