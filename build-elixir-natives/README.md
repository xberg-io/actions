# build-elixir-natives

Cross-compile a Rustler NIF for one Rust target triple, package it as a
RustlerPrecompiled-compatible `tar.gz`, and emit checksum metadata. The
output filename is compatible with the `generate-elixir-checksums`
action's `build_nif_artifact_name` so the per-target archives can be
fed into the aggregate checksum file later.

The action expects the caller to have run `setup-rust@v1` (with the
target installed) and `setup-elixir@v1`.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `target` | yes | — | Rust target triple, e.g. `x86_64-unknown-linux-gnu`. |
| `nif-crate-name` | no | `kreuzberg_nif` | Cargo package name of the NIF crate. |
| `nif-crate-path` | no | `packages/elixir/native/kreuzberg_nif` | Path to the NIF crate's manifest directory. |
| `package-dir` | no | `packages/elixir` | Path to the Elixir package (containing `mix.exs`). |
| `nif-version` | yes | — | Package version embedded in the artifact name (e.g. `5.0.0`). |
| `nif-api-version` | no | `""` | Erlang NIF API version (e.g. `2.16`). Empty → auto-detect via `erl`. |
| `output-dir` | no | `dist/elixir-natives` | Directory for the staging tree and archive. |
| `dry-run` | no | `false` | Skip cargo build and emit a plan only. |

## Outputs

| Name | Description |
|---|---|
| `archive-path` | Absolute path to the produced `.tar.gz`. |
| `archive-sha256` | Hex-encoded SHA256 of the archive. |
| `archive-name` | Filename of the archive (RustlerPrecompiled-conformant). |

## Usage

```yaml
strategy:
  matrix:
    include:
      - os: ubuntu-latest
        target: x86_64-unknown-linux-gnu
      - os: ubuntu-latest
        target: aarch64-unknown-linux-gnu
      - os: macos-latest
        target: aarch64-apple-darwin
      - os: windows-latest
        target: x86_64-pc-windows-msvc
runs-on: ${{ matrix.os }}
steps:
  - uses: actions/checkout@v6
  - uses: kreuzberg-dev/actions/setup-rust@v1
    with:
      target: ${{ matrix.target }}
  - uses: kreuzberg-dev/actions/setup-elixir@v1
  - id: nif
    uses: kreuzberg-dev/actions/build-elixir-natives@v1
    with:
      target: ${{ matrix.target }}
      nif-version: ${{ needs.prepare.outputs.version }}
  - uses: actions/upload-artifact@v7
    with:
      name: elixir-nif-${{ matrix.target }}
      path: ${{ steps.nif.outputs.archive-path }}
```

## Notes

- Filename pattern: `lib{nif-crate-name}-v{nif-version}-nif-{nif-api-version}-{target}.{so|dylib|dll}.tar.gz`.
  This matches `generate-elixir-checksums`'s expectation exactly.
- The platform extension is per-target (`.so` linux, `.dylib` darwin,
  `.dll` windows), not a single hardcoded value. Aligns with the
  `build_nif_artifact_name` helper in `generate-elixir-checksums`.
- The interior of the tar contains the library at its renamed
  RustlerPrecompiled name, with no enclosing directory.
- NIF API version is auto-detected via `erl` when `nif-api-version` is
  empty. For dry runs, the placeholder `<auto>` is used.
