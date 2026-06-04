# publish-zig

"Publish" a Zig package via Git tag with release asset tarball and Zig content hash.

Zig has no central package registry. Consumers reference packages via
`zig fetch --save <tarball-url>` against a release asset tarball, with a
`hash` field in their `build.zig.zon`. This action:

1. Validates `build.zig.zon` syntax.
2. Creates a deterministic package tarball from the working directory.
3. Uploads it as a GitHub release asset.
4. Computes the Zig content multihash via `zig fetch` from a fresh directory.
5. Optionally appends a `build.zig.zon` snippet to the release notes.

The tarball is created with reproducible settings (`gzip -n` and sorted file lists)
so that identical source trees produce identical tarballs.

## Usage

```yaml
jobs:
  publish-zig:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: kreuzberg-dev/actions/publish-zig@v1
        with:
          working-directory: packages/zig
          update-release-notes: 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

When `update-release-notes: 'true'` and a `GH_TOKEN` is in scope, the
action appends a Zig fetch snippet to the GitHub release body so users
can copy-paste the URL + hash into their own `build.zig.zon`.

## Outputs

| Name | Description |
|---|---|
| `tarball-url` | Release-asset tarball URL suitable for `zig fetch --save` |
| `zig-hash` | Zig content multihash for `build.zig.zon` `.hash` field |
| `tarball-sha256` | SHA-256 of the gzipped tarball (secondary reference) |
| `package-name` | Resolved package name (from input or `build.zig.zon` `.name`) |

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `working-directory` | no | `.` | Path to `build.zig.zon`. |
| `package-name` | no | (parsed from `.name` in `build.zig.zon`) | Package name for the tarball; overrides auto-detection. |
| `tag` | no | `${GITHUB_REF_NAME}` (when on a tag) | Git tag to publish. |
| `zig-version` | no | `0.16.0` | Zig version (`mlugg/setup-zig`). |
| `setup-zig` | no | `true` | Install Zig if not present. |
| `update-release-notes` | no | `false` | Append fetch snippet to GH release body. Requires `GH_TOKEN`. |
| `update-existing` | no | `false` | Pass `--clobber` to `gh release upload` (overwrite existing asset). |
| `dry-run` | no | `false` | Skip asset upload and release-notes update. |
| `use-alef-package` | no | `false` | Use `alef publish package_zig` for single-target packaging. Requires `target`, `ffi-library-path`, `ffi-header-path`. Mutually exclusive with `multi-platform-ffi-dir`. |
| `multi-platform-ffi-dir` | no | `""` | Directory containing per-RID FFI artifacts (`{rid}/{libs}` + `include/*.h`). When set, the action bundles each platform's libs into `<working-directory>/lib/<canonical-target-triple>/`, patches `build.zig.zon` `.paths` to allowlist `lib`/`include`, and overwrites `build.zig` with a target-aware build script that selects the right `lib/<rid>` subdir from Zig's compile-time target. Single multi-platform tarball; consumer's `zig fetch --save` works on any supported target. |
| `module-name` | no (yes when `multi-platform-ffi-dir` set) | `""` | Zig module name exported from the rewritten `build.zig` (e.g., `liter_llm`). |
| `ffi-lib-name` | no (yes when `multi-platform-ffi-dir` set) | `""` | FFI shared-library basename without `lib` prefix or extension (e.g., `liter_llm_ffi`). Used both for `linkSystemLibrary` and to locate the file inside `multi-platform-ffi-dir`. |

## Multi-platform packaging

When you have FFI libraries pre-built for multiple Rust target triples and want a
single Zig tarball that consumers can `zig fetch --save` on any supported host, set
`multi-platform-ffi-dir` instead of `use-alef-package`. The dir must look like:

```text
ffi-artifacts/
  linux-x64/        libfoo_ffi.so
  linux-arm64/      libfoo_ffi.so
  osx-arm64/        libfoo_ffi.dylib
  win-x64/          foo_ffi.dll
  include/          foo.h
```

The action maps each Rust RID into a canonical Zig target subdir (e.g., `linux-x64`
→ `lib/x86_64-linux-gnu/`) and writes a `build.zig` whose `ridDir(target)` switch
picks the right one based on the consumer's compile target. This avoids the
publish-time mistake of shipping the in-tree `build.zig` whose `../../target/release`
paths only exist in dev mode and fail with `unable to find dynamic system library
'foo_ffi'` for any `zig fetch` consumer.

Example:

```yaml
- uses: actions/download-artifact@v7
  with:
    pattern: ffi-*
    path: ffi-artifacts
    merge-multiple: true
- uses: kreuzberg-dev/actions/publish-zig@v1
  with:
    working-directory: packages/zig
    multi-platform-ffi-dir: ffi-artifacts
    module-name: liter_llm
    ffi-lib-name: liter_llm_ffi
    package-name: liter-llm-zig
    update-release-notes: 'true'
```
