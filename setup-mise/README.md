# setup-mise

Install [mise][mise] (pinned to 2026.10.21) through [`jdx/mise-action`][action] and the tools declared in the
repository's `mise.toml`. When `mise.lock`, or the `mise.<env>.lock` of an active `MISE_ENV` profile, sits next to
it, the action exports `MISE_LOCKED=1` for the install and every later step, and the install runs as
`mise install --locked`: a lock that does not cover the declared versions or the runner's platform fails the job
instead of resolving afresh. Later ad-hoc installs in the job (`mise use node@22`) fail too, unless the step sets
`MISE_LOCKED=false`.

Works on GitHub-hosted Ubuntu (x64 and arm64), macOS and Windows runners. Also:

- exports `MISE_RUBY_COMPILE=false` unless already set, so Ruby installs use precompiled builds, and
  `MISE_HTTP_TIMEOUT=5m` unless already set, since the 30s default fails on loaded runners;
- installs into a `MISE_DATA_DIR` already present in the runner environment (self-hosted images with
  preinstalled tools);
- caches the mise data directory keyed on `mise.toml`, `mise.*.toml`, `mise.lock`, `mise.*.lock`, `MISE_ENV`, OS
  and arch. With the default `cache: auto` it skips the cache when `MISE_DATA_DIR` is preset, since a cache keyed
  only on the repository's files could overlay a newer runner image; `true` and `false` force it.

## Usage

```yaml
- uses: xberg-io/actions/setup-mise@v1
```

Install a subset, with a profile that adds CI-only versions from `mise.ci.toml`:

```yaml
- uses: xberg-io/actions/setup-mise@v1
  with:
    install-args: node python
    mise-env: ci
```

## Inputs

| Name                | Required | Default                 | Description                                                      |
| ------------------- | -------- | ----------------------- | ---------------------------------------------------------------- |
| `working-directory` | no       | `.`                     | Directory holding `mise.toml` and `mise.lock`.                   |
| `install-args`      | no       | `""`                    | Arguments for `mise install`, e.g. `node python`.                |
| `mise-env`          | no       | `""`                    | Exported as `MISE_ENV` for this and later steps.                 |
| `github-token`      | no       | `${{ github.token }}`   | Token for GitHub release lookups, avoiding API rate limits.      |
| `config-ref`        | no       | `""`                    | Ref to restore the mise config from when `mise.toml` is missing. |
| `cache`             | no       | `auto`                  | `auto`, `true` or `false`; `auto` skips a preset `MISE_DATA_DIR`. |

## Outputs

| Name    | Description                                                       |
| ------- | ----------------------------------------------------------------- |
| `cache` | `true` or `false`: whether the mise data directory was cached.    |

## Older checkouts

Release and heal jobs that check out a tag predating `mise.toml` pass `config-ref: ${{ github.sha }}`. When the
working directory has no `mise.toml`, the action restores `mise.toml`, `mise.lock`, `mise.*.toml` and `mise.*.lock`
from that ref, leaving out `*.local.*` files. It fetches the ref only when the commit is not already present, and
fetches shallowly only into a shallow checkout, so a full clone keeps its history. The files are written to the
worktree only and added to `.git/info/exclude`, so later `git status` and `git diff` checks stay clean. It fails
when the ref has no `mise.toml` either, and when the fetch fails (keep `actions/checkout`'s
`persist-credentials` enabled).

## Matrix versions

Declare every extra version in a profile file such as `mise.ci.toml` (`yq = ["4.54.1", "4.53.6"]`) and lock it
with `MISE_ENV=ci mise lock`, which writes `mise.ci.lock` beside `mise.lock`. Select a leg's version with job-level
env, so `mise install --locked` and every later step resolve the same version:

```yaml
jobs:
  test:
    strategy:
      matrix:
        yq: ["4.54.1", "4.53.6"]
    env:
      MISE_ENV: ci
      MISE_YQ_VERSION: ${{ matrix.yq }}
    steps:
      - uses: actions/checkout@v7
      - uses: xberg-io/actions/setup-mise@v1
```

A version that the profile's lock does not cover fails the install.

Generate the lock for every CI platform with
`mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64`.

[mise]: https://mise.jdx.dev
[action]: https://github.com/jdx/mise-action
