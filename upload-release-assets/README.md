# upload-release-assets

Generic GitHub Release asset uploader. Glob-expands a list of paths or
patterns and uploads each matching file to a tag's GitHub Release with
`gh release upload --clobber`. Idempotent — re-running simply re-uploads
the same files. Replaces the per-purpose `upload-cli-binaries.sh`,
`upload-c-ffi-artifacts.sh`, `upload-go-libraries.sh`, and
`upload-homebrew-bottles.sh` scripts.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `tag` | yes | — | Git tag for the release. |
| `assets` | yes | — | Newline- or comma-separated list of file paths or glob patterns. Lines starting with `#` are comments. |
| `clobber` | no | `true` | Pass `--clobber` to `gh release upload` (overwrite existing assets). |
| `fail-if-empty` | no | `true` | Exit 1 when no files match. When `false`, log a warning and exit 0. |
| `working-directory` | no | `.` | Base directory for resolving relative paths and globs. |
| `dry-run` | no | `false` | Print intended uploads without invoking gh. |
| `token` | no | `${{ github.token }}` | GitHub token for authentication. |

## Outputs

| Name | Description |
|---|---|
| `uploaded-count` | Number of files uploaded (0 in dry-run mode). |
| `uploaded-paths` | Newline-separated list of uploaded file paths. |

## Usage

```yaml
- uses: xberg-io/actions/upload-release-assets@v1
  with:
    tag: ${{ needs.prepare.outputs.tag }}
    assets: |
      dist/cli/*.tar.gz
      dist/cli/*.zip
      dist/cli/SHA256SUMS
```

### With dry-run

```yaml
- uses: xberg-io/actions/upload-release-assets@v1
  with:
    tag: v1.2.3
    assets: dist/**/*.tar.gz
    dry-run: 'true'
```

## Notes

- Patterns are interpreted as `pathlib.Path.glob()` patterns relative to
  `working-directory`. Plain literal paths that exist as files are
  uploaded directly without glob expansion.
- Duplicate files (after path resolution) are uploaded once.
- The action requires `permissions: contents: write` on the calling job
  to upload to GitHub Releases.
