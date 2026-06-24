# build-csharp-natives

Build the Rust FFI crate for one Rust target triple and stage the
resulting native library at the NuGet RID-specific resource path
(`runtimes/{rid}/native/`), ready for `dotnet pack`. NuGet's runtime
asset selection requires this exact path layout.

The action expects the caller to have already checked out the repo and
run `xberg-io/actions/setup-rust@v1` with the right target
installed.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `target` | yes | — | Rust target triple, e.g. `x86_64-unknown-linux-gnu`. |
| `crate-name` | no | `kreuzberg-ffi` | Cargo package name to build. |
| `lib-name` | no | `crate-name` with `-` → `_` | Base name of the produced library. |
| `rid` | yes | — | .NET RID, e.g. `linux-x64`, `linux-arm64`, `linux-musl-x64`, `osx-arm64`, `win-x64`. |
| `output-dir` | no | `dist/csharp-natives` | Staging root directory. |
| `dry-run` | no | `false` | Skip cargo build and emit a plan only. |

## Outputs

| Name | Description |
|---|---|
| `library-path` | Absolute path to the staged native library. |
| `staging-dir` | Absolute path to `{output-dir}/runtimes/{rid}/native/`. |

## Usage

```yaml
strategy:
  matrix:
    include:
      - os: ubuntu-latest
        target: x86_64-unknown-linux-gnu
        rid: linux-x64
      - os: ubuntu-latest
        target: aarch64-unknown-linux-gnu
        rid: linux-arm64
      - os: macos-latest
        target: aarch64-apple-darwin
        rid: osx-arm64
      - os: windows-latest
        target: x86_64-pc-windows-msvc
        rid: win-x64
runs-on: ${{ matrix.os }}
steps:
  - uses: actions/checkout@v6
  - uses: xberg-io/actions/setup-rust@v1
    with:
      target: ${{ matrix.target }}
  - id: natives
    uses: xberg-io/actions/build-csharp-natives@v1
    with:
      target: ${{ matrix.target }}
      rid: ${{ matrix.rid }}
  - uses: actions/upload-artifact@v7
    with:
      name: csharp-natives-${{ matrix.rid }}
      path: ${{ steps.natives.outputs.staging-dir }}
```

## Notes

- Library extension is selected from the target triple: `.dll` for
  Windows, `.dylib` for Apple, `.so` otherwise. The library name is
  `lib{lib-name}` for Unix-like targets and `{lib-name}` for Windows.
- The `runtimes/{rid}/native/` layout is the standard NuGet Runtime
  Identifier (RID) graph layout. dotnet automatically selects the right
  asset at consumer build time.
