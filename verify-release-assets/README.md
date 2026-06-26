# verify-release-assets

After a publish workflow uploads assets, verify the GitHub Release
contains every expected file. Patterns are matched (via Python
`fnmatch`) against the release's asset list, **not the local
filesystem**, so this works as a gate after upload jobs land. Optional
minimum-size check catches empty uploads.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `tag` | yes | — | Git tag for the release. |
| `expected-assets` | yes | — | Newline-separated list of expected asset filenames or fnmatch patterns. Lines starting with `#` are comments. |
| `min-size-bytes` | no | `0` | Fail any asset smaller than this many bytes (0 disables). |
| `dry-run` | no | `false` | Print findings but do not exit non-zero on mismatches. |
| `token` | no | `${{ github.token }}` | GitHub token for `gh release view`. |

## Outputs

| Name | Description |
|---|---|
| `verified-count` | Number of expected patterns that matched at least one asset. |
| `missing` | Newline-separated list of expected patterns with no matching asset. Empty when all matched. |

## Usage

```yaml
- uses: xberg-io/actions/verify-release-assets@v1
  with:
    tag: ${{ needs.prepare.outputs.tag }}
    expected-assets: |
      # CLI binaries
      xberg-cli-*-x86_64-unknown-linux-gnu.tar.gz
      xberg-cli-*-aarch64-unknown-linux-gnu.tar.gz
      xberg-cli-*-aarch64-apple-darwin.tar.gz
      xberg-cli-*-x86_64-pc-windows-msvc.zip
      # C FFI artifacts
      libxberg-*-linux-x86_64.tar.gz
      libxberg-*-darwin-arm64.tar.gz
    min-size-bytes: 1024
```

## Notes

- Exits 1 on any missing pattern unless `dry-run: 'true'`.
- Patterns use shell-glob semantics via `fnmatch.fnmatch`. Use `*` for
  variable segments like version numbers.
- A single pattern matching multiple assets counts as one verified
  pattern, not multiple. Duplicate `expected-assets` lines therefore
  don't change the count.
