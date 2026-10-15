# Archive Python distributions

Permanently mirror wheels and sdists on a **public** GitHub Release before publishing to PyPI.
The action downloads every uploaded distribution anonymously and checks its SHA256 and byte size,
then generates a PEP 503 index with normalized package names and `data-requires-python` metadata.
Existing assets are never overwritten; a conflicting asset fails verification.

Inputs are `packages-dir`, `repository` (default current repository), `tag`, `expected-version`,
`output-dir` (default `python-index`), optional `existing-manifests-dir`, and `token`.
The token needs `contents: write` for the source release repository. Create or publish the release
first: draft release assets cannot serve public installers.

Outputs are `index-dir`, `manifest` (a JSON receipt for the current distributions), and `file-count`.
`index-only: "true"` rebuilds the complete index without distribution inputs or uploads.
The CLI equivalent is `archive.py --index-only --repository OWNER/REPO --output-dir FRESH_DIR`.
The output directory contains `simple/index.html`, `simple/<normalized-name>/index.html`, `.nojekyll`,
and manifests. Deploy `simple/` to the central `xberg-io/python-wheels` Pages site, preserving manifests
from every source repository. `existing-manifests-dir` merges those other sources into the rendered
index. Serialize deployments and use compare-and-swap branch updates to prevent lost concurrent updates.
All historical public-release archive manifests in the source repository are included automatically.
For the central repository deployment, use index-only mode with its release manifests as the sole
source. Optional `existing-manifests-dir` imports are trusted local data: their records receive
schema and conflict validation, but this option does not independently download their assets.
Do not use imported local manifests as evidence for a PyPI deletion decision.

Run exactly one combined wheel-and-sdist archive writer per package and release tag. Assemble all
platform distributions before invoking the action, and serialize that writer with a workflow
concurrency group. The per-package release manifest uses read/merge/replace; concurrent writers
for the same package and tag can lose manifest entries.

Each receipt has a `files` array of records with `name`, `version`, `filename`, `sha256`, `size`,
`requires_python`, and the direct GitHub Release asset `url`. Per-package manifests are attached to
source releases as `python-archive-<name>.json`; retain them and their distributions permanently.
Historical backfill can use the same action by supplying historical distributions and their exact
version. This action never removes files from PyPI or GitHub.

Continue using `publish-pypi` normally. Its optional `fallback-index-url` input accepts the deployed
`https://xberg-io.github.io/python-wheels/simple/` URL. It attempts PyPI first. Only HTTP 400 project
storage quota errors can fall back, and only after every local distribution has a matching public
index link, hash, downloaded bytes, and distribution Python requirement. Authentication, invalid packages,
network failures, missing archives, and all other errors remain fatal. The `fallback` output is true
when the archive was used; `published` is false in that case.

Install historical releases with:

```sh
pip install xberg --extra-index-url https://xberg-io.github.io/python-wheels/simple/
uv pip install xberg --extra-index-url https://xberg-io.github.io/python-wheels/simple/
```

For PyPI retention, preserve every version in the current minor series and the latest stable patch
in each older minor series. If an older minor has no stable version, retain its latest prerelease.
Before removing anything, inventory the exact candidate files, verify a complete public byte-for-byte
archive and a working deployed index, and obtain explicit approval for that exact deletion plan.
Deletion is irreversible and existing PyPI filenames cannot be reused.
