---
type: Playbook
title: Release Workflow
description: How to cut a release of the xberg-io/actions repo — clean-tree + poly/tests preconditions, CHANGELOG rollover, commit and push to main, then the two-tag scheme this repo uses (create a NEW immutable `vX.Y.Z` annotated tag AND force-move the floating major `v1` tag to the same commit so every consumer pinning `@v1` picks up the release). Load when cutting/releasing a new version of the actions repo, or when the floating `v1` tag needs to be advanced.
x-ai-rulez:
  kind: skill
  id: release-workflow
  metadata:
    name: release-workflow
---

## Release workflow (xberg-io/actions)

This repo publishes reusable composite actions and workflows consumed by every other xberg-io repo as `uses: xberg-io/actions/<action>@v1` and `uses: xberg-io/actions/.github/workflows/<wf>.yml@v1`. Consumers pin the **floating major tag `v1`**, so a release is only visible to them once `v1` is moved to the new commit.

### Tag scheme

- **Immutable version tags** — `vX.Y.Z` (annotated). Never re-pointed once pushed. Determine the latest version with `git tag --list 'v1.*' --sort=-version:refname`.
- **Floating major tag** — `v1` (annotated). Deliberately force-updated on every release to point at the newest release commit. This is the ref consumers pin.

Both are annotated tag objects (`git cat-file -t v1` → `tag`), so create/move them with `-a`.

### Preconditions (must pass before releasing)

Run from a clean checkout of `main`:

```bash
git switch main
git fetch origin
git status --porcelain            # must be EMPTY — no uncommitted/untracked changes
git log --oneline origin/main -1  # confirm local main == remote tip

poly fmt --check .                # formatting clean
poly lint .                       # lint clean (also: task lint)
task test                         # unit tests — runs `uv run pytest -v` across configured testpaths
```

Do not proceed if the tree is dirty or any check fails. `task validate` (== `task lint`) runs actionlint + shellcheck + shfmt via poly; the action test workflows in `.github/workflows/test-*.yml` are the CI gate — they must be green on `main`.

### 1. Roll the CHANGELOG and commit

`CHANGELOG.md` is hand-maintained with a `## [Unreleased]` section. Move the accumulated `Unreleased` entries under a new dated version heading:

```markdown
## [Unreleased]

## [vX.Y.Z] - YYYY-MM-DD

### Added
- ... (entries that were under Unreleased)
```

Then commit and push the release commit to `main` (direct commit if you have rights, otherwise land it via PR and pull the merged `main`):

```bash
git add CHANGELOG.md
git commit -m "chore(release): vX.Y.Z"
git push origin main
```

Re-run `git fetch origin && git log --oneline origin/main -1` and make sure local `main` is exactly the commit you just pushed — the tags below must point at the **pushed** release commit.

### 2. Create the new immutable version tag (AFTER pushing)

Pick the next version by bumping the latest `v1.Y.Z` (patch for fixes, minor for new actions/inputs). Create it at the release commit and push it:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"   # tags current HEAD (the pushed release commit)
git push origin vX.Y.Z
```

### 3. Move the floating major tag `v1` to the new release

Record the current remote tag object using `git ls-remote origin refs/tags/v1`.
Use that exact object as `<previous-remote-tag-object>` in the lease below.
Update `v1` to point at the same commit/tag, then force-push the `v1` ref so `@v1` consumers pick up the release:

```bash
git tag -f -a v1 -m "v1 -> vX.Y.Z" vX.Y.Z   # re-point annotated v1 at the new version tag
git push origin v1 --force-with-lease=refs/tags/v1:<previous-remote-tag-object>
```

`git tag -f v1 <ref>` + `git push origin v1 --force-with-lease=refs/tags/v1:<previous-remote-tag-object>` is the established method for advancing the floating major. `<ref>` can be the new version tag (`vX.Y.Z`) or the release commit SHA — both resolve to the same commit.

> This tag move is the sanctioned exception to the shared-branch force-push rule.
> The explicit lease rejects a concurrent update to `v1`. Never force-move an immutable
> `vX.Y.Z` tag or a shared branch.

### 4. Verify

```bash
git fetch origin --tags --force
git rev-parse 'v1^{}'             # target commit must equal:
git rev-parse 'vX.Y.Z^{}'         # target commit of the new version tag
```

Both must resolve to the release commit. Consumers pinning `@v1` now resolve to `vX.Y.Z`.
