# build-go-ffi

Build a Rust FFI crate for one Rust target triple and bundle the resulting
shared library together with the C header into a tar.gz that the Go cgo
binding can unpack at install time.

The action expects the caller to have already checked out the repository and
run `kreuzberg-dev/actions/setup-rust@v1` (with the right target installed).
It does not install any toolchains itself.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `target` | yes | — | Rust target triple, e.g. `x86_64-unknown-linux-gnu`. |
| `crate-name` | no | `kreuzberg-ffi` | Cargo package name to build. |
| `lib-name` | no | `crate-name` with `-` → `_` | Base name of the produced library. |
| `header-path` | no | `crates/kreuzberg-ffi/include/kreuzberg.h` | C header to bundle alongside the library. |
| `output-dir` | no | `dist/go-ffi` | Directory for the staging tree and archive. |
| `archive-name` | no | `{lib-name}-{target}.tar.gz` | Override the default archive filename. |
| `dry-run` | no | `false` | Skip cargo build and emit a plan only. |

## Outputs

| Name | Description |
|---|---|
| `archive-path` | Absolute path to the produced tar.gz archive. |
| `archive-sha256` | Hex-encoded SHA256 digest of the archive. |

## Usage

```yaml
jobs:
  build-go-ffi:
    strategy:
      matrix:
        include:
          - os: ubuntu-latest
            target: x86_64-unknown-linux-gnu
          - os: macos-latest
            target: aarch64-apple-darwin
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v6
      - uses: kreuzberg-dev/actions/setup-rust@v1
        with:
          target: ${{ matrix.target }}
      - id: ffi
        uses: kreuzberg-dev/actions/build-go-ffi@v1
        with:
          target: ${{ matrix.target }}
      - uses: actions/upload-artifact@v7
        with:
          name: go-ffi-${{ matrix.target }}
          path: ${{ steps.ffi.outputs.archive-path }}
```

## Notes

- The action invokes `cargo build -p <crate> --release --target <triple>`. It
  does not pass any features — set `CARGO_*` env or rely on the crate's default
  features.
- The library extension is selected from the target triple: `.dll` for Windows,
  `.dylib` for Apple, `.so` otherwise. The library name is `lib{lib-name}` for
  Unix-like targets and `{lib-name}` for Windows.
- The archive expands to a single top-level directory `{lib-name}-{target}/`
  containing the library and the header.
