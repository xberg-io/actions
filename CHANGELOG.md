# Changelog

All notable changes to kreuzberg-dev/actions are documented in this file.

## [Unreleased]

### Added

- `install-alef`: Cache the installed alef binary inside the composite action via `actions/cache@v4`, keyed on host triple + resolved version. Cache hits skip the download/build entirely. For `version: main`, the cache key embeds the current `kreuzberg-dev/alef` HEAD commit's short SHA, so a new main commit invalidates the cache automatically.
- `install-alef`: New `scripts/resolve.sh` factored out of `unix.sh` — resolves `latest`/`main`/tag to a stable cache key and install ref before any download/build runs, so the cache lookup can fire before the slow path.
- `setup-php`: Add `tools` input to install global PHP tools (phpstan, psalm, composer, etc.) via shivammathur/setup-php
- `setup-maven`: Add `java-version` input (default `"21"`) to install Java via `actions/setup-java`
- `setup-gradle`: Add `java-version` input (default `"21"`) to install Java via `actions/setup-java`

### Changed

- `install-alef`: On release-binary download failure, the source-build fallback (`cargo install --git --tag v<X.Y.Z> --locked alef-cli`) now writes the produced binary into the cache, so subsequent jobs in the same workflow that share the cache key skip the cargo build entirely. Previously every job re-built from source whenever the release assets were late.
- `install-alef`: PATH wiring moved out of the platform install scripts into the composite action itself so it runs on cache hits too.

### Fixed

- `reusable-validate-issues`: Soft-fail project-board add when token lacks org-level Projects: write scope
- `install-alef`: `resolve.sh` no longer aborts the workflow when the GitHub Commits/Releases API request fails or returns no matching JSON. The intended fallback (`resolved_version=main` / explicit error on `latest`) now runs because `set -e`/`pipefail` are scoped narrowly around the curl pipeline.
- `publish-swift`: Skip the "Verify tag is fetchable" check during dry-runs. The dry-run mode is exercised before the tag is pushed, so requiring the tag on origin always fails. The check still runs for real publishes.
- `publish-hex`: Run `mix deps.get` (and install `rebar` locally) before `mix hex.publish`. Without this, the publish step failed with `Unchecked dependencies for environment dev: ex_doc, rustler_precompiled, credo, rustler — the dependency is not available, run "mix deps.get"`.
- `publish-pypi`: Switch from `pypa/gh-action-pypi-publish@release/v1` to `uv publish --trusted-publishing automatic`. The pypa action's `create-docker-action.py` reads `GITHUB_ACTION_REPOSITORY`, which inside a composite is the composite's repo (`kreuzberg-dev/actions`), so it tries to pull `ghcr.io/kreuzberg-dev/actions:v1` and fails with `denied`. `uv publish` performs the OIDC token exchange in-process — no Docker.
- `publish-npm`: Strip empty `NODE_AUTH_TOKEN` env and `_authToken=` lines from `.npmrc` before invoking `npm publish`. When a caller writes `NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}` and the secret is undefined, the previous behavior forced classic-token auth with an empty token and 404'd at the registry PUT. With this fix, an empty token triggers npm CLI v11+ OIDC trusted publishing automatically.
- `publish-rubygems`: Invoke `rubygems/configure-rubygems-credentials@v2.0.0` when `GEM_HOST_API_KEY` is empty/unset and not in dry-run. This exchanges the GHA OIDC token for a short-lived RubyGems credential, enabling trusted publishing without a static API key. Classic API-key flow is preserved when the secret is set.

### Deprecated

### Removed

### Security
