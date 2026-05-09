# finalize-release

Post-publish finalization. Edits the GitHub Release from draft → published,
sets or clears the prerelease flag, optionally creates a Go module tag,
and writes a step summary. Idempotent — safe to re-run.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `tag` | yes | — | Git tag for the release. |
| `is-prerelease` | no | `auto` | `true`/`false` to force, or `auto` to derive from tag suffix (`-rc`/`-alpha`/`-beta`/`-pre`). |
| `go-module-path` | no | `""` | If set (e.g. `packages/go/v5`), additionally creates the tag `{path}/{tag}` for Go module consumers. |
| `dry-run` | no | `false` | Print intended actions without modifying the release. |
| `token` | no | `${{ github.token }}` | GitHub token. |

## Outputs

| Name | Description |
|---|---|
| `finalized` | `true` (just finalized), `false` (dry-run), or `already-finalized`. |
| `prerelease-flag` | Resolved prerelease flag as `true` or `false`. |

## Usage

```yaml
- uses: kreuzberg-dev/actions/finalize-release@v1
  with:
    tag: ${{ needs.prepare.outputs.tag }}
    is-prerelease: ${{ needs.prepare.outputs.is_prerelease }}
    go-module-path: packages/go/v5
```

### Auto-derive prerelease from tag

```yaml
- uses: kreuzberg-dev/actions/finalize-release@v1
  with:
    tag: ${{ needs.prepare.outputs.tag }}
    # is-prerelease defaults to "auto" — true for v1.2.3-rc.1, false for v1.2.3
```

## Notes

- The Go module tag is created via `gh api repos/.../git/refs`, mirroring
  the pattern used by `retag-for-republish`. If the tag already exists,
  the action treats this as success.
- Requires `permissions: contents: write` on the calling job.
- Writes a multi-line summary to `$GITHUB_STEP_SUMMARY`.
