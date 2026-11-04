# prepare-swift-release

The pre-tag half of an immutable Swift release. SwiftPM resolves `from:`/`exact:` versions to the core
`vX.Y.Z` tag, so that tag's root `Package.swift` must already pin the checksum of the bundle it downloads. This
action commits the checksum before the tag exists and creates the tag once on that commit; it never moves,
deletes or force-pushes a ref. Callers normally use it through
[`reusable-swift-release-prepare.yml`](../.github/workflows/reusable-swift-release-prepare.yml), and publish
afterwards with [`publish-swift-release`](../publish-swift-release/README.md).

Each call runs one `command`:

| Command    | What it does                                                                                                                                                                                                                                                                                                                                                                       |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `resolve`  | Reads the version from `cargo-toml` (`[workspace.package]` or `[package]`), derives `v<version>` (a given `tag` must match), fails if the tag already exists or the checkout is not the tip of `branch`.                                                                                                                                                                           |
| `targets`  | Derives `MACOSX_DEPLOYMENT_TARGET` from Package.swift's `.macOS` minimum and `IPHONEOS_DEPLOYMENT_TARGET` from its `.iOS` minimum and exports them. An explicit macOS target must equal the manifest's; an explicit iOS target may lower it (for a dependency that links older runtime symbols), never raise it.                                                                   |
| `pin`      | On a clean tree, runs `alef sync-versions --regen` with the ZIP and receipt in `bundle-dir`, fails if it left `Package.swift` unchanged, and restores every other re-rendered path from HEAD with a `::warning::` listing them (alef#884).                                                                                                                                         |
| `verify`   | Requires the receipt to describe this ZIP, HEAD, version and repository and the ZIP's own triples (and `expected-triples` when set); the ZIP to be one safe, CRC-clean artifact bundle; and the tree to differ from HEAD only in `Package.swift`, byte for byte (line endings and file mode included) apart from its one checksum value, with the binaryTarget URL naming the tag. |
| `finalize` | Pushes the pin commit to `branch` and an annotated tag at it in one non-forced `git push --atomic`. A rerun recognises an earlier run by content: a tag or branch tip that is the single child of the source changing only `Package.swift` to the same bytes is completed, not recreated. A moved branch or a different tag fails.                                                 |

Python 3.11 or later must be on `PATH`. `resolve`, `verify` and `finalize` need a full-history checkout of the
source commit.

## Two-step Swift release

1. Land the version bump on `main`, then dispatch **Prepare Swift release** (the caller of the reusable workflow)
   on `main`. Its `build` job builds the bundle once on macOS with a receipt, pins the checksum, verifies the pin
   and uploads the ZIP, receipt and `Package.swift` as the `swift-release-prepared` artifact. `finalize` pushes the
   pin commit and the tag together, and `release` creates a draft release (`--verify-tag`) and attaches the exact
   ZIP (through `publish-swift-release`) and the receipt. A dry run stops after the build and prints the ref plan.
2. Dispatch **Publish Release** on the tag. It verifies the tagged manifest against the attached ZIP and receipt
   with `publish-swift-release` (`bundle-zip: ""`) and never rebuilds the bundle.

The bundle is not reproducible, so recover a failed run with **Re-run failed jobs**: the later jobs download
the same bytes and complete any partial state (pin pushed without the tag, tag without the draft, draft without
the asset). Re-running the build after the tag exists fails, by design.

## Caller

```yaml
name: Prepare Swift release

on:
  workflow_dispatch:
    inputs:
      dry-run:
        type: boolean
        default: false

concurrency:
  group: prepare-swift-release
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  swift:
    uses: xberg-io/actions/.github/workflows/reusable-swift-release-prepare.yml@v1
    with:
      dry-run: ${{ inputs.dry-run }}
      crate-name: example-swift
      artifact-name: Example-rs
    secrets:
      app-id: ${{ secrets.BOT_APP_ID }}
      app-private-key: ${{ secrets.BOT_APP_PRIVATE_KEY }}
```

The app needs contents write on the caller and must be allowed to push to the protected branch and create tags
(a ruleset bypass); the pin commit touches only `Package.swift`, so workflows write is not needed. A caller whose
build needs generated sources from another job of its run passes `setup-artifact` and `setup-artifact-path`.
