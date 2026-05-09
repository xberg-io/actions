# build-java-natives

Build the Rust FFI crate for one Rust target triple and stage the
resulting native library at the Panama FFM-expected resource path,
ready to be packed into a `kreuzberg-natives-{classifier}` JAR.

The action expects the caller to have already checked out the repo and
run `kreuzberg-dev/actions/setup-rust@v1` with the right target
installed. It does not install any toolchains itself.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `target` | yes | — | Rust target triple, e.g. `x86_64-unknown-linux-gnu`. |
| `crate-name` | no | `kreuzberg-ffi` | Cargo package name to build. |
| `lib-name` | no | `crate-name` with `-` → `_` | Base name of the produced library. |
| `classifier` | yes | — | Maven classifier, e.g. `linux-x86_64`, `linux-aarch64-musl`, `darwin-aarch64`, `windows-x86_64`. |
| `output-dir` | no | `dist/java-natives` | Staging root directory. |
| `dry-run` | no | `false` | Skip cargo build and emit a plan only. |

## Outputs

| Name | Description |
|---|---|
| `library-path` | Absolute path to the staged library. |
| `staging-dir` | Absolute path to `{output-dir}/native/{classifier}/`. |

## Usage

```yaml
strategy:
  matrix:
    include:
      - os: ubuntu-latest
        target: x86_64-unknown-linux-gnu
        classifier: linux-x86_64
      - os: ubuntu-latest
        target: aarch64-unknown-linux-gnu
        classifier: linux-aarch64
      - os: macos-latest
        target: aarch64-apple-darwin
        classifier: darwin-aarch64
      - os: windows-latest
        target: x86_64-pc-windows-msvc
        classifier: windows-x86_64
runs-on: ${{ matrix.os }}
steps:
  - uses: actions/checkout@v6
  - uses: kreuzberg-dev/actions/setup-rust@v1
    with:
      target: ${{ matrix.target }}
  - id: natives
    uses: kreuzberg-dev/actions/build-java-natives@v1
    with:
      target: ${{ matrix.target }}
      classifier: ${{ matrix.classifier }}
  - uses: actions/upload-artifact@v7
    with:
      name: java-natives-${{ matrix.classifier }}
      path: ${{ steps.natives.outputs.staging-dir }}
```

## Notes

- Library extension is selected from the target triple: `.dll` for
  Windows, `.dylib` for Apple, `.so` otherwise. The library name is
  `lib{lib-name}` for Unix-like targets and `{lib-name}` for Windows.
- The classifier corresponds to the Maven `<classifier>` element on the
  natives JAR. Make sure the matrix uses consistent values across all
  platforms a release supports.
