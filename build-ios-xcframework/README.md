# build-ios-xcframework

Cross-compile a Rust crate for all iOS targets (device arm64, simulator
arm64+x86_64) and bundle into an XCFramework, ready for integration into
Xcode projects or Swift Package Manager distributions.

The action expects the caller to have already checked out the repo and run
`xberg-io/actions/setup-rust@v1`. It does not install any toolchains itself.
Must run on `macos-latest`.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `crate-name` | yes | — | Cargo package name to build. |
| `lib-name` | no | `crate-name` with `-` → `_` | Base name of the produced library. |
| `xcframework-name` | no | `lib-name` PascalCase | XCFramework name. |
| `header-path` | no | — | Optional path to C header directory to embed. |
| `output-dir` | no | `dist/ios-xcframework` | Output directory for the XCFramework. |
| `build-profile` | no | `release` | Cargo build profile (dev, release, or custom). |
| `dry-run` | no | `false` | Skip build steps and emit a plan only. |

## Outputs

| Name | Description |
|---|---|
| `xcframework-path` | Absolute path to the created `.xcframework` directory. |
| `xcframework-zip` | Absolute path to the zipped `.xcframework`. |
| `checksum` | SHA256 checksum for Swift Package Manager. |

## Usage

```yaml
runs-on: macos-latest
steps:
  - uses: actions/checkout@v6
  - uses: xberg-io/actions/setup-rust@v1
  - id: xcfw
    uses: xberg-io/actions/build-ios-xcframework@v1
    with:
      crate-name: my-crate
      lib-name: my_lib
      header-path: include/
      output-dir: dist/ios
  - uses: actions/upload-artifact@v7
    with:
      name: ios-xcframework
      path: ${{ steps.xcfw.outputs.xcframework-zip }}
```

## Notes

- The XCFramework is built for three architectures: `aarch64-apple-ios` (device),
  `aarch64-apple-ios-sim` and `x86_64-apple-ios` (simulator).
- The simulator arm64 and x86_64 libraries are combined into a fat library before
  bundling.
- C headers can be embedded by providing a `header-path` pointing to a directory
  containing `.h` files.
- The checksum is computed using `swift package compute-checksum` and is suitable
  for Swift Package Manager binary targets.
