# Changelog

All notable changes to kreuzberg-dev/actions are documented in this file.

## [Unreleased]

### Added

### Changed

### Fixed

### Deprecated

### Removed

### Security

## [1.0.4] - 2026-05-23

### Fixed

- `upload-release-assets`: forward `GITHUB_TOKEN` (or `INPUT_TOKEN`) into the `gh release upload` subprocess as `GH_TOKEN` so the call authenticates. The composite step's `${{ secrets.GITHUB_TOKEN }}` was already available in `os.environ`, but `gh` only looks at `GH_TOKEN` and its keyring (which is empty on hosted runners), so the upload returned `HTTP 401: Bad credentials`. Surfaced in liter-llm v1.4.0-rc.30 publish run 26337912364 (Upload PHP extension assets job).

## [1.0.3] - 2026-05-23

### Fixed

- `wait-for-package` (pypi): try both the as-given SemVer version (`1.4.0-rc.30`) AND the PEP 440-normalized form (`1.4.0rc30`) when polling PyPI's JSON endpoint. PyPI's API only resolves the canonical PEP 440 form (`/pypi/<pkg>/1.4.0rc30/json` returns 200 while `/pypi/<pkg>/1.4.0-rc.30/json` returns 404), so callers passing the SemVer-form tag downstream saw `not found on pypi after 20 attempts` even though the package was successfully published. Surfaced in liter-llm v1.4.0-rc.30 publish run 26336349972 — `Verify install Python` job failed after 16 min of polls while `liter-llm@1.4.0rc30` had been live on PyPI the entire time. The new `_pep440_normalize` helper covers `rc/alpha/beta/a/b` prereleases and the unchanged-on-release case.

## [1.0.2] - 2026-05-23

### Fixed

- `setup-gradle`: Bump default `gradle-version` from `"8.11"` to `"8.13"`. Android Gradle Plugin 8.13.0 (consumed by alef-emitted `packages/kotlin-android/build.gradle.kts`) refuses to apply on Gradle <8.13 with `Minimum supported Gradle version is 8.13. Current version is 8.11.` Surfaced as tslp CI Mobile `kotlin-android AAR check` failures across all four ABIs after the alef 0.18.0 regen.

## [1.0.1] - 2026-05-23

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

- `install-alef`: Source-build fallback now invokes `cargo install ... alef` (the single crate produced by alef's post-restructure workspace) instead of the removed `alef-cli` crate. Surfaced as the v0.18.0 release-publish failure when the release-binary download path missed the cache, fell through to `cargo install --git --tag v0.18.0 --locked alef-cli`, and crates.io returned `could not find 'alef-cli' in https://github.com/kreuzberg-dev/alef?branch=main with version '*'`. Updates both `scripts/unix.sh` (Linux/macOS) and `scripts/windows.ps1` to reference the current crate name.
- `publish-crates`: Increase sparse-index propagation timeouts so heavy workspace publishes (e.g. alef's 29-crate run) don't fail when crates.io's CDN lags. `INDEX_POLL_TIMEOUT_SECONDS` 300→600, `PUBLISH_RETRY_ATTEMPTS` 6→10, `PUBLISH_RETRY_DELAY_SECONDS` 30→60. Previous budget (5min wait + 6×30s retries = 8min total) was exhausted on alef v0.17.35 at slot 21/29 (`alef-backend-kotlin-android` couldn't see freshly-published `alef-backend-kotlin` in the index). New budget gives 20min total per dependent — covers observed real-world propagation tail.
- `publish-pypi`: Skip the `uv publish` invocation when the discovered version is already on the registry. The action's `scripts/publish.py` now parses the project name + version from the dist filenames (wheel-name spec + sdist tarball-name spec), queries the PyPI JSON API (`<base>/pypi/<name>/<version>/json`, auto-derived from `repository-url`), and emits `version_published=true` to `$GITHUB_OUTPUT` when the version is already present — gating both the `setup-uv` and `uv publish` steps. Previously, force-republishing a tag failed with `400 File already exists` because PyPI's API is immutable; the action now treats that as a success-equivalent skip. New output: `skipped` (true when version was already published).
- `publish-maven`: Run `actions/setup-java@v5` so the central publishing plugin can resolve credentials from `~/.m2/settings.xml`. Previously the action ran only `setup-maven`, leaving no `<server>` entry in the user's settings.xml — `mvn deploy` failed with `Unable to get publisher server properties for server id: ossrh: Cannot invoke "org.apache.maven.settings.Server.clone()" because "server" is null`. setup-java writes a `<server id="${server-id}">` block keyed on `MAVEN_USERNAME` / `MAVEN_PASSWORD` env vars (which callers already pass to the publish step), so the publishing-plugin resolves them transparently. New inputs: `setup-java` (default `true`), `java-version` (default `25`, matches the current LTS used by spikard), `java-distribution` (default `temurin`), `server-id` (default `ossrh`, matches the alef-generated `<publishingServerId>`).
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
