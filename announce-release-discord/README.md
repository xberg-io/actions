# announce-release-discord

Post a release announcement to a Discord channel via webhook, with the
behaviors the publish workflows rely on:

- **Prerelease tags are skipped.** Only `vMAJOR.MINOR.PATCH` tags announce.
  Anything containing a `-` suffix (`-rc.1`, `-alpha`, `-beta`, `-pre`) is
  ignored.
- **Release-log body.** The announcement uses the release log, not language
  install snippets. When a GitHub Release body has been replaced by Swift
  instructions or appended with the Zig fetch block, the action strips those
  sections and regenerates GitHub release notes if no release log remains.
- **Idempotent.** After a successful post, the action uploads a
  `discord-announced.marker` marker asset to the GitHub Release. Subsequent runs
  on the same tag (e.g. after a tag delete + recreate + republish) detect
  the marker and skip — no double announcements.

## Authentication

Pass the Discord webhook URL via an org or repo secret named
`DISCORD_WEBHOOK_URL`. The action also needs `contents: write` permission
on the calling job to upload the dedup marker asset.

```yaml
permissions:
  contents: write
steps:
  - uses: kreuzberg-dev/actions/announce-release-discord@v1
    with:
      tag: ${{ needs.prepare.outputs.tag }}
      webhook-url: ${{ secrets.DISCORD_WEBHOOK_URL }}
      project-name: html-to-markdown
```

## Usage

Wire as a final job in your publish workflow, gated on every `publish-*`
job succeeding (or being skipped — `check-*` may decide a registry is
already up to date, which is success for this purpose).

```yaml
announce-discord:
  name: Announce release on Discord
  needs:
    - prepare
    - publish-pypi
    - publish-npm
    # ... all other publish-* jobs
  if: |
    always() &&
    !cancelled() &&
    needs.prepare.outputs.is_tag == 'true' &&
    needs.prepare.outputs.dry_run != 'true' &&
    needs.prepare.outputs.is_prerelease != 'true' &&
    !contains(needs.*.result, 'failure')
  runs-on: ubuntu-latest
  permissions:
    contents: write
  steps:
    - uses: kreuzberg-dev/actions/announce-release-discord@v1
      with:
        tag: ${{ needs.prepare.outputs.tag }}
        webhook-url: ${{ secrets.DISCORD_WEBHOOK_URL }}
        project-name: my-project
```

The in-script regex is a belt-and-braces check against the
`is_prerelease` workflow gate, so the action stays safe even when called
from a workflow that doesn't pre-compute that flag.

### Dry run

```yaml
- uses: kreuzberg-dev/actions/announce-release-discord@v1
  with:
    tag: v1.2.3
    webhook-url: ${{ secrets.DISCORD_WEBHOOK_URL }}
    dry-run: 'true'
```

Prints the payload it would POST and skips both the network call and the
marker upload.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `tag` | yes | — | Tag like `v1.2.3`. Anything else is treated as prerelease and skipped. |
| `webhook-url` | yes | — | Discord webhook URL — pass via secrets. |
| `repo` | no | `${{ github.repository }}` | `owner/name`, used for the release URL and embed footer. |
| `project-name` | no | repo name | Display name in the embed title. |
| `notes` | no | empty | Override the release body. When empty, fetched from the GitHub Release log. |
| `color` | no | `0x5865F2` | Embed accent color (decimal, `0xHEX`, or `#HEX`). |
| `dry-run` | no | `false` | Render the payload to logs without posting. |
| `token` | no | `${{ github.token }}` | Used by `gh release view` and the marker asset upload. |

## Outputs

| Name | Description |
|---|---|
| `posted` | `true`, `false` (dry-run), `skipped-prerelease`, or `skipped-already-announced`. |

## Dedup mechanics

After a successful POST the action runs:

```sh
gh release upload "$TAG" discord-announced.marker --clobber
```

On the next run for the same tag, the action checks
`gh release view $TAG --json assets` and exits early if the marker is
present. This works because the existing `Ensure GitHub Release exists`
step in publish workflows only **creates** the release if missing — it
never deletes — so the marker survives tag retag/republish cycles.

If you ever need to force a re-announcement (e.g. content was wrong),
manually delete the `discord-announced.marker` asset from the GitHub Release
and rerun the workflow.
