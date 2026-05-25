# Changelog

All notable changes to kreuzberg-dev/actions are documented in this file.

## [Unreleased]

### Added

### Changed

### Fixed

- `build-csharp-natives`, `build-java-natives`, `build-elixir-natives`: inject
  `RUSTFLAGS="-C target-feature=-crt-static"` into the Alpine Docker build for
  `*-linux-musl` targets. The default musl rust toolchain enables `+crt-static`,
  which silently drops the `cdylib` crate type with
  `warning: dropping unsupported crate type cdylib for target *-linux-musl`,
  leaving no `.so` for the staging step to find. Disabling `crt-static` restores
  cdylib output while keeping the bin/staticlib crate types working. The merged
  `env_vars` dict still wins, so callers can override.

### Deprecated

### Removed

- `publish-swift`: remove the metadata-only Swift Package Index ping action.
  Swift packages are distributed directly from Git tags, so downstream release
  workflows should keep package build/smoke checks and drop SPI ping jobs.

### Security

## [1.6.11] - 2026-05-25

### Fixed

- `build-elixir-natives`: resolve the built NIF library's release directory from
  `cargo metadata`'s `target_directory` instead of assuming `<crate>/target`. The
  NIF crate builds into its own `target/` only when its `Cargo.toml` is a
  standalone workspace; when its path-deps (or the `rewrite-native-deps`
  prepublish step) make it a member of the parent workspace — or when
  `CARGO_TARGET_DIR`/`.cargo/config.toml` redirect it — the lib lands in the
  parent's `target/`, so the crate-relative assumption (v1.6.x) failed with
  `built NIF library not found`. Now queried from cargo, with a crate-local
  fallback when `cargo metadata` is unavailable.

## [1.6.10] - 2026-05-25

### Fixed

- `verify-package-contents`: accept a directory as `artifact-path` and iterate
  over all supported archive types inside it. Previously the script only accepted
  a single archive file; kreuzberg's publish workflow passes `dist/` directories
  containing multiple `.whl` and `.tar.gz` files, causing the script to fail with
  `Unsupported artifact extension: dist`. The script now detects whether `artifact-path`
  is a file or directory, finds all archives matching supported extensions (`.whl`,
  `.jar`, `.nupkg`, `.zip`, `.tar.gz`, `.tgz`, `.crate`, `.gem`, `.tar`) via recursive
  glob, verifies each archive, and aggregates results. Single-file callers remain
  backward compatible. Fixes v5.0.0-rc.1 publish-pypi verification blocking.
- `build-elixir-natives`: fix release directory lookup for NIF crates with
  workspace Cargo.toml. When the NIF crate declares its own `[workspace]`
  section, cargo writes the compiled library to `<crate-path>/target/<triple>/release/`
  instead of the repository root `target/<triple>/release/`. The script now
  resolves the release directory relative to `nif_crate_path` rather than the
  repository root, fixing failures on Windows (and potentially other platforms)
  when the NIF crate has its own workspace configuration.
- `build-csharp-natives`, `build-java-natives`, `build-elixir-natives`: fix
  musl linker detection in Alpine container. The `rust:1-alpine3.21` image is
  itself musl-based, so plain `gcc` produces musl-linked binaries. However,
  `rustc` was defaulting to the linker binary `musl-gcc`, which does not exist
  in the container, causing builds to fail with `error: linker \`musl-gcc\` not
  found`. Set `CARGO_TARGET_<TARGET>_LINKER=gcc` as a target-specific env var
  in the inline docker build command so rustc routes to the available linker.

## [1.6.5] - 2026-05-25

### Added

- `package-php-pie`: `dry-run` input that passes `--dry-run` through to `alef
  publish package`. In dry-run mode alef short-circuits before the
  `assert_no_member_path_deps` validation, so the binding crate's `Cargo.toml`
  does not need to be rewritten to registry version-deps (which is impossible
  before the core crate is on crates.io). The action gracefully exits without
  producing an archive when `dry-run: true`; callers must gate their downstream
  `upload-artifact` on the same dry-run flag. Closes the last chicken-and-egg
  gap in the source-build publish path: previously a dry-run that left path
  deps unrewritten (correct, since the version is not yet published) would
  fail the path-dep assertion inside `alef publish package`.

## [1.6.4] - 2026-05-24

### Fixed

- `lint-docs`: fix prek binary extraction from tarball. The `Install prek` step
  downloaded the tarball correctly but extracted it to the wrong path: the prek
  release tarball has structure `prek-<target>/prek`, but the extraction command
  was unpacking directly to `$HOME/.local/bin`, resulting in `$HOME/.local/bin/prek-<target>/prek`.
  Added `--strip-components=1` to tar so the binary lands at `$HOME/.local/bin/prek`
  as expected. Fixes CI docs runs failing with `chmod: cannot access /home/runner/.local/bin/prek`.

## [1.6.3] - 2026-05-24

### Fixed

- `lint-docs`: install `prek` (pre-commit wrapper) before running `task docs:lint:prose`, which
  internally invokes `prek run textlint`. The action previously installed Task, lychee, and
  textlint, but omitted prek, causing exit code 127 (command not found) when docs:lint:prose
  ran prek hooks on the prose linter.

## [1.6.2] - 2026-05-24

### Fixed

- `build-python-wheels`: case-insensitively compare `runner.arch` when
  deciding whether to set `CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER`.
  `runner.arch` resolves to `ARM64` (uppercase) on GitHub-hosted arm64
  runners, so the previous lowercase compare always missed and the
  linker override was never emitted into `CIBW_ENVIRONMENT`. Python
  wheel builds on `ubuntu-24.04-arm` failed inside the manylinux
  container with `error: linker \`aarch64-linux-gnu-gcc\` not found`
  because cargo defaulted to the cross-compiler binary name even on
  native arm64. The compare now lowercases the value first so the
  override fires on every arm64-on-Linux runner.

## [1.6.1] - 2026-05-24

### Fixed

- `build-csharp-natives`, `build-java-natives`, `build-elixir-natives`:
  switch musl Docker image from `alpine:3.21` to `rust:1-alpine3.21`. The
  bare alpine image lacks `rustup` and `cargo`, so the in-container
  `rustup target add ...` call returned exit code 127 and aborted every
  musl native build. `rust:1-alpine3.21` ships with the toolchain
  pre-installed; the existing `apk add` line still provides the C build
  deps the cdylib link step needs.

## [1.6.0] - 2026-05-24

### Added

- `publish-hex`: new optional input `tarball-path` accepts a pre-built Hex
  source tarball (.tar) from `build-elixir-hex@v1`, allowing publish without
  rebuilding. When set, publishes the tarball directly via `mix hex.publish
  package <tarball-path>` instead of rebuilding from source. Preserves
  dry-run and idempotency (already-published) handling.

## [1.5.1] - 2026-05-24

### Fixed

- `build-elixir-natives`: build the NIF crate named by `nif-crate-name` instead
  of the hardcoded `kreuzberg_nif`. The musl/alpine build rewrite left a literal
  `cargo build -p kreuzberg_nif` in `scripts/build.py`, so every consumer whose
  crate is not named `kreuzberg_nif` (e.g. `spikard_nif`) failed with cargo exit
  101. Added a unit test asserting the configured crate name is threaded through.

## [1.5.0] - 2026-05-24

### Removed

- `build-homebrew-bottle`: removed the synthetic single-binary bottle action.
  Use `homebrew-build-bottles` for real Homebrew bottles generated by `brew`.
- `publish-homebrew`: removed the legacy single-formula bottle updater. Use
  `publish-homebrew-source-formulas` for formula rendering and
  `homebrew-merge-bottles` for bottle DSL updates.

## [1.4.0] - 2026-05-24

### Added

- `publish-homebrew-source-formulas`: New composite action for rendering one or
  more Homebrew formulas from per-formula `.rb.tmpl` templates with `${tag}` /
  `${version}` / per-asset `${<sha_key>}` substitution, downloading release
  tarballs via `gh release download` and computing their SHA256 digests.
  Tolerant of dry-run releases: when
  `dry-run: true` and an asset is missing, it substitutes the zero-SHA
  placeholder + emits a warning so dry-run pipelines can still render and diff
  formulas before the real release exists. Replaces the per-repo
  `scripts/publish/update-homebrew-formula.sh` boilerplate (e.g.
  html-to-markdown's 184-line dual-formula updater) with a thin shared
  invocation + a JSON config + templates. Ships with a
  `test-publish-homebrew-source-formulas` integration workflow exercising the
  dry-run placeholder path end-to-end. Surfaced by html-to-markdown
  3.5.0-rc.2 publish dry-run, where the inline script failed at
  `gh release download` with "release not found" against the synthesized
  dry-run tag — blocking the entire bottle pipeline (which `needs` the
  formula update to succeed) from exercising even in dry-run mode.

## [1.3.1] - 2026-05-24

### Fixed

- `build-ruby-gem`: Added a `dry-run` input that, when `true`, skips the embedded
  `rewrite-native-deps` step — closing the last gap in the source-build action
  family (now consistent with `build-elixir-natives`, `build-elixir-hex`,
  `build-php-extension`, `build-python-sdist`). Source-build Ruby gem builds in
  publish dry-run mode now succeed without requiring the rc version to be on
  crates.io. Surfaced during the v1.4.0-rc.31 publish dry-run audit, which
  showed three call sites (Ruby native-gem, Elixir NIF, Ruby source-gem) using
  the un-gated `rewrite-native-deps` directly in liter-llm's `publish.yaml`.

## [1.3.0] - 2026-05-24

### Added

- `build-elixir-hex`: New composite action — the Hex source-package analog of
  `build-python-sdist` / `build-ruby-gem`. It rewrites the Rustler NIF crate's
  workspace path-dependencies to registry version-dependencies (via
  `rewrite-native-deps`, default-on) and then runs `mix hex.build`, so the
  published tarball compiles standalone on a consumer machine instead of failing
  on missing workspace paths. On `dry-run: true` it skips the rewrite (the rc
  version is not yet on crates.io) and falls back to `cargo generate-lockfile`
  in the NIF crate directory so the `mix.exs` `files` list still finds the
  required `<nif-crate-path>/Cargo.lock`. Replaces the hand-rolled inline
  `mix deps.get` + `mix hex.build` step across the polyglot repos and bakes in
  the dependency rewrite so it cannot be omitted. Ships with a
  `test-build-elixir-hex` integration workflow that exercises the dry-run
  lockfile fallback path end-to-end against a Rustler fixture. Surfaced by
  html-to-markdown 3.5.0-rc.2 publish dry-run, which failed in `mix hex.build`
  with `Missing files: native/html_to_markdown_nif/Cargo.lock` because the
  ungenerated lockfile (gitignored) was never produced by an inline step.

## [1.2.1] - 2026-05-24

### Fixed

- `build-php-extension`, `build-python-sdist`: Added a `dry-run` input that, when
  `true`, skips the embedded `rewrite-native-deps` step. Dry-run publish workflows
  run before the core `liter-llm` crate is on crates.io, so the rewrite's
  `--require-registry` lookup hard-failed (`failed to select a version for the
  requirement liter-llm = "^X.Y.Z-rc.N"`) and blocked the entire PHP PIE matrix
  (and would do the same for the Python sdist build) from going green in dry-run.
  Mirrors the existing `dry-run` guard on `build-elixir-natives`. Surfaced in
  liter-llm v1.4.0-rc.31 publish dry-run.

## [1.2.0] - 2026-05-24

### Added

- `build-python-sdist`: New composite action — the python-sdist analog of
  `build-ruby-gem`. It rewrites the binding crate's workspace path-dependencies to
  registry version-dependencies (via `rewrite-native-deps`, default-on) and then runs
  `maturin sdist`, so the source distribution compiles standalone on a consumer machine
  instead of failing on missing workspace paths. Supports both package-dir mode
  (`cd <package-dir> && maturin sdist`) and manifest-path mode (`maturin sdist -m
  <Cargo.toml>`), a `maturin-version` pin (default `>=1.5,<2.0`), and writes the sdist to
  a repo-relative or absolute `output-dir`. Replaces the hand-rolled inline `maturin
  sdist` step across the polyglot repos and bakes in the dependency rewrite so it cannot
  be omitted. Ships with a `test-build-python-sdist` integration workflow.

## [1.1.0] - 2026-05-24

### Added

- `rewrite-native-deps`: New composite action that rewrites a source-build language package's workspace path-dependencies to registry version-dependencies via `alef publish prepare --lang <lang> [--require-registry]`. Source-build packages (Ruby gem, Python sdist, Elixir NIF, PHP extension, Swift) ship a `Cargo.toml` whose core-crate deps point at workspace paths that no longer exist once the package is unpacked on a consumer machine — breaking `gem install`, source `pip install`, and SPM builds. The action strips those paths and pins the published version so the shipped manifest resolves. Requires alef >= 0.19.0. Inputs: `lang` (required, comma-separated), `alef-version` (default `latest`), `require-registry` (default `true`), `working-directory` (default `.`). The `lang` value is charset-validated before reaching the CLI.

### Changed

- `build-ruby-gem`, `build-php-extension`, `build-elixir-natives`: Run `rewrite-native-deps` before the native build by default, so the artifacts these actions produce resolve their core-crate dependencies from the registry rather than the workspace. New inputs `rewrite-native-deps` (default `true`) and `alef-version` (default `latest`); set `rewrite-native-deps: false` to build against the local workspace in non-release CI. The Elixir build additionally skips the rewrite on `dry-run`. Because the rewrite passes `--require-registry`, the core crates must already be published to the registry when these actions run during a release.
- Bumped dev dependencies (`uv.lock`) and pre-commit hook revisions (`kreuzberg-dev/pre-commit-hooks` v1.1.13 → v1.1.18, `ruff-pre-commit` v0.15.13 → v0.15.14).

### Fixed

- `publish-github-release`: Replaced the stale `build_create_flags` tests (the gh-CLI flag helper was removed when the action moved to the GitHub REST API) with tests that assert the `create_release()` REST payload and endpoint.
- `publish-npm`: Hoisted the `SETUP_NODE_PLACEHOLDER` sentinel to a module-level constant (ruff `N806`).
- `detect-private-key`: Excluded `CHANGELOG.md` and `publish-maven/action.yml`, whose only matches are documentation references to the `-----BEGIN PGP PRIVATE KEY BLOCK-----` armor header, not real keys.
- Applied `ruff-format` and `rumdl` formatting to previously-undrifted scripts and READMEs.

## [1.0.9] - 2026-05-24

### Fixed

- `publish-npm`: Auto-upgrade npm CLI to v11+ before publish when the host npm is older. OIDC trusted publishing requires npm v11.5.1+; Node 22 (currently the LTS default in `actions/setup-node@v6`) ships npm 10.9.x, which falls through to classic-token auth and surfaces as `ENEEDAUTH … This command requires you to be logged in` when no static `NODE_AUTH_TOKEN` is configured. The action now runs `npm install -g npm@latest` before invoking the publish script when `npm --version | cut -d. -f1 < 11`. No-op on hosts that already ship npm 11+. Surfaced in liter-llm v1.4.0-rc.30 publish runs (`Publish Node packages`, `Publish WASM package`) — the v1.0.8 placeholder-strip got us past the setup-node sentinel, only for npm 10 to refuse OIDC.

## [1.0.8] - 2026-05-24

### Fixed

- `publish-npm`: Treat `NODE_AUTH_TOKEN='XXXXX-XXXXX-XXXXX-XXXXX'` as unset for OIDC purposes. `actions/setup-node@v6` exports the literal 23-char placeholder string `XXXXX-XXXXX-XXXXX-XXXXX` as `NODE_AUTH_TOKEN` (see `authutil.ts`'s `core.exportVariable('NODE_AUTH_TOKEN', process.env.NODE_AUTH_TOKEN || 'XXXXX-XXXXX-XXXXX-XXXXX')`) whenever the caller hasn't already set the env var. The placeholder is intended as a sentinel that lets `.npmrc`'s `_authToken=${NODE_AUTH_TOKEN}` resolve to something non-empty so npm doesn't complain about a missing token at config-read time — but at publish time, npm sends that literal placeholder string to the registry as the real auth credential and the registry returns `404 Not Found` (shadowing OIDC trusted publishing). The script now treats the placeholder the same as "unset": it pops the env var, strips `_authToken=` lines from `.npmrc`, and lets npm CLI v11+ exchange the GHA OIDC token automatically. Surfaced in liter-llm v1.4.0-rc.30 publish runs (`Publish Node packages`, `Publish WASM package`) which kept 404'ing after `NODE_AUTH_TOKEN` was removed from the workflow's `env:` blocks — setup-node was still injecting the placeholder.

## [1.0.7] - 2026-05-24

### Fixed

- `publish-npm`: Strip `_authToken=` lines from EVERY candidate `.npmrc` (`$NPM_CONFIG_USERCONFIG`, `$HOME/.npmrc`, and `$PWD/.npmrc`) regardless of the value's form when `NODE_AUTH_TOKEN` is unset. The v1.0.6 fix targeted the wrong file — `actions/setup-node@v6` writes the placeholder line to `$NPM_CONFIG_USERCONFIG=/home/runner/work/_temp/.npmrc`, not `$HOME/.npmrc`. Because `Path.home() / ".npmrc"` was the only path probed when `NPM_CONFIG_USERCONFIG` happened to be unset on that environment fork, the strip silently no-op'd and the `_authToken=${NODE_AUTH_TOKEN}` placeholder line stayed in the actual `.npmrc` that `npm publish` read. The script now walks all three locations, prints which one it acted on, and additionally relaxes the matcher to strip ANY `_authToken=...` line on the empty-token path — we're committing to OIDC trusted publishing in that branch, so any leftover `_authToken` line would shadow OIDC. Adds diagnostic logging so future regressions surface without needing log forensics.

## [1.0.6] - 2026-05-24

### Fixed

- `publish-npm`: Strip `//<registry>/:_authToken=${NODE_AUTH_TOKEN}` placeholder lines from `.npmrc` (in addition to the post-expansion empty form `_authToken=`). `actions/setup-node@v6` writes the literal placeholder string `_authToken=${NODE_AUTH_TOKEN}` to `.npmrc` and defers env-var expansion to npm CLI at read time. When the caller's job doesn't set `NODE_AUTH_TOKEN` (because they're relying on OIDC trusted publishing), npm expands the placeholder to an empty token at PUT time → `404 Not Found` from the npm registry, with no fallback to OIDC. The previous `_strip_empty_npm_auth_token` only matched the post-expansion empty case (`=` then EOL); the new regex also matches the unexpanded `=${NODE_AUTH_TOKEN}` form so OIDC trusted publishing actually takes over. Surfaced in liter-llm v1.4.0-rc.30 publish run 26339094710 (`Publish Node packages` and `Publish WASM package` both 404'd after provenance signing succeeded — trusted publisher config on npmjs.org was correct, the line was just shadowing OIDC).

## [1.0.5] - 2026-05-23

### Fixed

- `publish-hex`: Treat Hex.pm's `inserted_at: can only modify a release up to one hour after publication` error as a success-equivalent skip. Hex allows in-place re-uploads only within a one-hour window after the first publish; after that, a re-run of the same version (e.g. when retrying a partial publish run that failed on a sibling registry) returns the validation error above with non-zero exit. The release is already live on hex.pm, so the action now matches this string in the same skip-grep as `already published` / `version already exists`. Surfaced in liter-llm v1.4.0-rc.30 publish run 26339094710 (`liter_llm 1.4.0-rc.30` had been on hexpm since the first publish dispatch hours earlier).

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
