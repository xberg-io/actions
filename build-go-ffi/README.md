# build-go-ffi

Build a Rust FFI crate for one Rust target triple and bundle the resulting
shared library together with the C header into a tar.gz that the Go cgo
binding can unpack at install time.

The action expects the caller to have already checked out the repository and
run `xberg-io/actions/setup-rust@v1` (with the right target installed).
It does not install any toolchains itself.

## Contract for Go `go generate` consumers

Archives produced by this action have a standardized layout for consumption by
`go generate` scripts:

1. Archive filename: `{lib-name}-{rust-target}.tar.gz` (e.g., `html_to_markdown_ffi-aarch64-apple-darwin.tar.gz`)
2. Archive expands to: `{lib-name}-{rust-target}/` containing:
   - `lib{lib-name}.{ext}` (Unix: `.dylib`/`.so`, Windows: `.dll`)
   - `{lib-name}.h` (C header)
3. Go `go generate` scripts should:
   - Download the archive from a GitHub Release for the current `GOOS`/`GOARCH`
   - Unpack into `.lib/{rid}/` (e.g., `.lib/macos-arm64/`)
   - Ensure headers and binaries are present before cgo compilation

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `target` | yes | — | Rust target triple, e.g. `x86_64-unknown-linux-gnu`. |
| `crate-name` | no | `xberg-ffi` | Cargo package name to build. |
| `lib-name` | no | `crate-name` with `-` → `_` | Base name of the produced library. |
| `header-path` | no | `crates/xberg-ffi/include/xberg.h` | C header to bundle alongside the library. |
| `output-dir` | no | `dist/go-ffi` | Directory for the staging tree and archive. |
| `archive-name` | no | `{lib-name}-{target}.tar.gz` | Override the default archive filename. |
| `dry-run` | no | `false` | Skip cargo build and emit a plan only. |

## Outputs

| Name | Description |
|---|---|
| `archive-path` | Absolute path to the produced tar.gz archive. |
| `archive-sha256` | Hex-encoded SHA256 digest of the archive. |

## Usage

### Generic template

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
      - uses: xberg-io/actions/setup-rust@v1
        with:
          target: ${{ matrix.target }}
      - id: ffi
        uses: xberg-io/actions/build-go-ffi@v1
        with:
          target: ${{ matrix.target }}
      - uses: actions/upload-artifact@v7
        with:
          name: go-ffi-${{ matrix.target }}
          path: ${{ steps.ffi.outputs.archive-path }}
```

### html-to-markdown example

```yaml
- id: ffi
  uses: xberg-io/actions/build-go-ffi@v1
  with:
    target: ${{ matrix.target }}
    crate-name: html-to-markdown-ffi
    lib-name: html_to_markdown_ffi
    header-path: crates/html-to-markdown-ffi/include/html_to_markdown.h
    output-dir: dist/go-ffi
```

The resulting archive `html_to_markdown_ffi-{target}.tar.gz` should be uploaded to
a GitHub Release for the alef Go backend to download during `go generate`.

## Notes

- The action invokes `cargo build -p <crate> --release --target <triple>`. It
  does not pass any features — set `CARGO_*` env or rely on the crate's default
  features.
- The library extension is selected from the target triple: `.dll` for Windows,
  `.dylib` for Apple, `.so` otherwise. The library name is `lib{lib-name}` for
  Unix-like targets and `{lib-name}` for Windows.
- The archive expands to a single top-level directory `{lib-name}-{target}/`
  containing the library and the header.
