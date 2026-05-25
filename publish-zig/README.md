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
