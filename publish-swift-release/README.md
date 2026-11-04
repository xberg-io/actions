# publish-swift-release

Publish a prepared Swift artifact bundle against a release tag that already pins its checksum.
SwiftPM consumers resolve `from:`/`exact:` versions to the core `vX.Y.Z` tag, so that tag's root
`Package.swift` must carry the final checksum; rewriting the tag after publication starts changes the
signed release source. This action only verifies the tag and never creates, moves or deletes one.

Before anything is uploaded or pushed it requires:

- the tag exists on the remote; its tagged root manifest holds no `__ALEF_*__` placeholder, exactly one
  SHA-256 `checksum:` and the binaryTarget URL `https://github.com/<repository>/releases/download/<tag>/<asset>`;
- the supplied bundle's SHA-256 equals that checksum (and the optional receipt's repository, archive, digest,
  version, triples and source agree; the source must be an ancestor of the tagged commit, which needs a full
  checkout, `fetch-depth: 0`);
- the release exists (published or draft; `gh` falls back to a draft for the tag) and any asset of that name
  already on it has the same bytes;
- the legacy branch is absent or already points at the tagged commit.

It then re-reads the tag, creates the legacy branch only if it is absent (a create-only push that fails if
another run created it meanwhile), uploads the bundle only if the release lacks it, and confirms the tag
object and peeled commit did not change. Every partial state it can leave (branch created, asset not yet
uploaded) is one a rerun accepts and completes, so rerun to recover; a rerun after success changes nothing.

## Release order

1. On the version-bump commit, build the bundle with `build-swift-artifactbundle` and `receipt-version`. The
   receipt records `github.repository`, the HEAD commit, the version and the ZIP digest.
2. On that clean tree (alef rejects uncommitted or untracked changes), run alef's version sync with the ZIP and
   receipt in `dist/swift-artifactbundle/`; it pins the checksum into the root `Package.swift`. Commit that.
3. Preserve that exact ZIP, for example as a workflow artifact or a draft release asset. The ZIP is not
   reproducible: a rebuild yields different bytes and fails the checksum check.
4. Tag the finalized commit.
5. Publish with this action, passing the same ZIP or leaving `bundle-zip` empty to reuse the release asset.

## Inputs

| Name            | Required | Default                    | Description                                                                           |
| --------------- | -------- | -------------------------- | ------------------------------------------------------------------------------------- |
| `tag`           | yes      | —                          | Release tag whose manifest pins the checksum.                                         |
| `bundle-zip`    | no       | `""`                       | Prepared `.artifactbundle.zip`; empty reuses the existing release asset.              |
| `receipt`       | no       | `""`                       | Preparation receipt to cross-check.                                                   |
| `manifest-path` | no       | `Package.swift`            | Root manifest path inside the tagged tree.                                            |
| `legacy-branch` | no       | `release/swift/{version}`  | Branch created at the tagged commit; `{version}` is the tag without `v`. Empty skips. |
| `remote`        | no       | `origin`                   | Git remote holding the tag.                                                           |
| `repository`    | no       | `${{ github.repository }}` | Release repository and binaryTarget URL owner.                                        |
| `dry-run`       | no       | `false`                    | Verify and report without uploading or pushing.                                       |
| `token`         | no       | `${{ github.token }}`      | Token for the release asset lookup and upload.                                        |

The checkout's own credentials push the legacy branch, so check out with a token that can write refs.

## Outputs

| Name             | Description                                 |
| ---------------- | ------------------------------------------- |
| `checksum`       | SHA-256 pinned by the tagged manifest.      |
| `commit`         | Commit the tag peels to.                    |
| `tag-object`     | Object the tag ref names, unchanged.        |
| `asset-uploaded` | Whether this run uploaded the bundle.       |
| `branch-created` | Whether this run created the legacy branch. |

## Usage

```yaml
- uses: actions/checkout@v7
  with:
    ref: ${{ needs.prepare.outputs.tag }}
    fetch-depth: 0
    token: ${{ steps.app-token.outputs.token }}
- uses: actions/download-artifact@v8
  with:
    name: swift-artifactbundle
    path: dist/swift-artifactbundle
- uses: xberg-io/actions/publish-swift-release@v1
  with:
    tag: ${{ needs.prepare.outputs.tag }}
    bundle-zip: dist/swift-artifactbundle/Example-rs.artifactbundle.zip
    dry-run: ${{ needs.prepare.outputs.dry_run }}
    token: ${{ steps.app-token.outputs.token }}
```
