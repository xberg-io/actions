# build-swift-package

Build a Swift Package that wraps a Rust binding crate via
[swift-bridge](https://github.com/chinedufn/swift-bridge). The action runs
`cargo build` against the named binding crate, locates the swift-bridge
generated headers and Swift sources under
`target/<profile>/build/<crate>-*/out/`, and syncs them into the Swift
package's `Sources/RustBridgeC/` (combined C header) and `Sources/RustBridge/`
(Swift wrappers with `import RustBridgeC` prepended). After this action
runs, the package is ready for a Git tag.

## Usage

```yaml
- uses: actions/checkout@v4
- uses: kreuzberg-dev/actions/setup-rust@v1
- uses: kreuzberg-dev/actions/build-swift-package@v1
  with:
    package-dir: packages/swift
    crate-name: kreuzberg-swift
- run: swift build --package-path packages/swift --configuration release
```

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `package-dir` | no | `packages/swift` | Directory containing `Package.swift`. |
| `crate-name` | no | `kreuzberg-swift` | Cargo crate name of the Rust binding crate. |
| `build-profile` | no | `release` | Cargo profile (`release`, `dev`, or a custom named profile). |
| `dry-run` | no | `false` | Print the planned commands and exit without building or syncing. |

## Outputs

| Name | Description |
|---|---|
| `package-dir` | Passthrough of the `package-dir` input. |

## Notes

- Sync layout follows `packages/swift/BUILDING.md`:
  - `out/SwiftBridgeCore.h` + `out/<crate>/<crate>.h` -> `Sources/RustBridgeC/RustBridgeC.h`
    (concatenated; mirrors the `cat ... > RustBridgeC.h` step in the docs).
  - Each `*.swift` in `out/` and `out/<crate>/` is prefixed with
    `import RustBridgeC\n` and written to `Sources/RustBridge/`.
- If multiple `<crate>-*` build directories exist (cargo retains old hashes),
  the most recently modified `out/` is selected.
- Missing files emit a warning rather than failing — the swift-bridge
  generator may emit a different file set across versions, and the action
  should not block a release on a renamed core file.
- The action does not invoke `swift build` itself; the caller decides whether
  to compile the Swift target. Many publish flows only need the synced
  sources committed and tagged.
