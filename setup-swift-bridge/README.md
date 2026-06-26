# setup-swift-bridge

Stage the [`swift-bridge`](https://github.com/chinedufn/swift-bridge) cargo
build output into a Swift Package Manager layout. Locates the most recent
`target/<profile>/build/<crate-name>-*/out` directory and copies the
generated `SwiftBridgeCore.{h,swift}` plus binding-specific
`<crate-name>.{h,swift}` into `<packages-dir>/Sources/RustBridgeC` and
`<packages-dir>/Sources/RustBridge` (prepending `import RustBridgeC` to the
Swift sources).

Works on both macOS (`stat -f`) and Linux (`stat -c`). Run after
`cargo build -p <crate-name> --profile <profile>`.

## Usage

```yaml
- uses: xberg-io/actions/setup-swift-bridge@v1
```

With overrides:

```yaml
- uses: xberg-io/actions/setup-swift-bridge@v1
  with:
    profile: release
    crate-name: xberg-swift
    packages-dir: packages/swift
```

## Inputs

| Name           | Required | Default            | Description                                                                                  |
| -------------- | -------- | ------------------ | -------------------------------------------------------------------------------------------- |
| `profile`      | no       | `release`          | Cargo build profile. Maps to `target/<profile>/build/`.                                      |
| `crate-name`   | no       | `kreuzcrawl-swift` | swift-bridge crate name suffix used to match `*<crate-name>-*/out` build directories.        |
| `packages-dir` | no       | `packages/swift`   | Swift package directory. `Sources/RustBridgeC` and `Sources/RustBridge` are created beneath. |

## Notes

- Fails fast if the cargo build output directory is missing or the expected
  `SwiftBridgeCore.{h,swift}` / `<crate-name>.{h,swift}` artefacts cannot be
  located.
- Replaces hand-rolled `scripts/setup-swift-bridge.sh` files in consumer
  repos so the BSD/GNU `stat` portability fix lives in one place.
