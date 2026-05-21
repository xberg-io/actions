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

- `finalize-release`: Set `GH_REPO` env var so `gh release view`/`edit` resolve the target repo without needing a local git checkout. The finalize job typically runs without `actions/checkout` (no source code needed), so previously `gh` had no git remote to auto-detect from and silently fell back to a 404 — `Release v0.15.2 not found` even though the release was visible to anyone with the URL. The retry-loop fix from the earlier patch was masking this misconfiguration; with `GH_REPO` set, the first attempt now succeeds.
- `publish-maven`, `publish-maven-gradle`: Replace the armor-header prefix grep with an unconditional try-armored-then-try-base64 import. GitHub Actions log-masks any substring that matches a registered secret, including the literal `-----BEGIN PGP PRIVATE KEY BLOCK-----` pattern in the script when the secret value begins with that header — visible in logs as `if echo "$MAVEN_GPG_PRIVATE_KEY" | head -1 | grep -q "***"`. The masking is display-only, but the prefix detection itself was also brittle to leading/trailing whitespace or CR characters. The new approach pipes the raw value to `gpg --batch --import` first, falls back to `base64 -d | gpg --batch --import`, and surfaces the actual gpg stderr in the failure message so future format mismatches are diagnosable.
- `publish-nuget`: Fix three protocol bugs in the OIDC trusted-publishing token exchange — endpoint was `/api/v2/OidcToken` (now `/api/v2/token`), audience was `nuget` (now `https://www.nuget.org`), and the OIDC token was being sent in the JSON body (now sent as `Authorization: Bearer <token>` with the request body carrying `{"username": "<nuget-user>", "tokenType": "ApiKey"}`). Matches the protocol used by the official `NuGet/login@v1` action. New required input `nuget-user` (or env `INPUT_NUGET_USER`) carries the nuget.org profile name; OIDC fails fast with a clear error if unset.
- `publish-rubygems`: Recover the rubygems push credential from `BUNDLE_GEM__PUSH_KEY` (and `RUBYGEMS_API_KEY`) when `GEM_HOST_API_KEY` is empty. `rubygems/configure-rubygems-credentials@v2` exports all three env vars, but the caller's step-level `GEM_HOST_API_KEY: ${{ secrets.RUBYGEMS_API_KEY }}` with an empty secret shadows the value, so `gem push` saw an empty key and got back `Access Denied`. The fallback uses whichever non-empty var is available and passes it explicitly to the child process.
- `publish-maven`: Import the `MAVEN_GPG_PRIVATE_KEY` into the keyring before invoking `mvn deploy`. Previously the action passed `MAVEN_GPG_PASSPHRASE` through but never imported the key, so `maven-gpg-plugin` failed with `gpg: no default secret key: No secret key` whenever the caller workflow hadn't run `setup-java@v5` with `gpg-private-key`. Accepts both armored OpenPGP and base64-encoded armored (auto-detected). Step is skipped when `MAVEN_GPG_PRIVATE_KEY` is unset, so callers that already imported via `setup-java` remain compatible.
- `publish-maven-gradle`: Accept base64-encoded GPG private keys in addition to armored PGP format — auto-detects format and decodes as needed to handle secrets stored base64-encoded to avoid newline corruption.
- `finalize-release`: Retry release lookup up to 6 times with 5s sleep between attempts to handle propagation race where release was created but API hasn't caught up yet.
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
