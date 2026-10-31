# setup-mise

Install [mise][mise] (pinned to 2026.10.24) through [`jdx/mise-action`][action] and the tools declared in the
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

| Name                | Required | Default               | Description                                                                        |
| ------------------- | -------- | --------------------- | ---------------------------------------------------------------------------------- |
| `working-directory` | no       | `.`                   | Directory holding `mise.toml` and `mise.lock`.                                     |
| `install-args`      | no       | `""`                  | Arguments for `mise install`, e.g. `node python`.                                  |
| `install`           | no       | `true`                | `false` sets up mise without installing tools.                                     |
| `tools`             | no       | `""`                  | Install only these tools, each `tool` or `tool=version`; see below.                |
| `mise-env`          | no       | `""`                  | Exported as `MISE_ENV` for this and later steps.                                   |
| `github-token`      | no       | `${{ github.token }}` | Token for GitHub release lookups, avoiding API rate limits.                        |
| `config-ref`        | no       | `""`                  | Ref to restore the mise config and `mise-tasks/` from when `mise.toml` is missing. |
| `cache`             | no       | `auto`                | `auto`, `true` or `false`; `auto` skips a preset `MISE_DATA_DIR`.                  |

When `install-args` or `tools` names some tools, or `install` is `false`, the action exports
`MISE_TASK_RUN_AUTO_INSTALL=false` (unless already set), so a later `mise run` uses exactly the installed tools
instead of installing the rest of `mise.toml` first.
On Windows runners it also exports `MISE_WINDOWS_DEFAULT_INLINE_SHELL_ARGS` for Git Bash (unless already set), so
inline `run` tasks execute under the same POSIX shell as on Linux and macOS instead of `cmd /c`.

## Selected tools

`tools` installs only the tools it names, for jobs and actions that need a few of them, and puts the selected
versions first on `PATH` for later steps (with `JAVA_HOME` for Java):

```yaml
- uses: xberg-io/actions/setup-mise@v1
  with:
    tools: python=${{ matrix.python }} uv
```

- `tool` installs the version the config selects: `mise.toml`, the active `MISE_ENV` profiles, or a
  `MISE_<TOOL>_VERSION` the job exports. A tool the config does not declare fails the step, unless a fallback root
  is set (see below).
- `tool=version` is matched against `mise.lock` and the active profile locks first: `python=3.12` selects the
  newest locked `3.12.x` and installs with `--locked`, whatever `MISE_LOCKED` the job set. A version no lock covers
  installs unlocked with a notice; declare it in a profile such as `mise.ci.toml` and lock it to verify its
  checksums. A leading `v` and a trailing `.x` are dropped, so `3.x` and `v0.17.0` work; a channel such as
  `latest`, `stable`, `lts` or `nightly` fails, since it names no version a lock can pin.
- A short name finds the backend the config declares: `wasm-pack` resolves to `github:rustwasm/wasm-pack`.

The composites in this repository that need a language or tool install it the same way, through
`scripts/install-tools.sh`, and take their version inputs as `tool=version`.

### Fallback root

`INSTALL_TOOLS_FALLBACK_ROOT` names a directory with its own `mise.toml` and `mise.lock`. A tool requested without a
version that the caller's config does not declare then installs the one version that directory's `mise.toml`
selects, `--locked` against its `mise.lock`, with a notice. The composites that install a tool callers may not
declare (helm, uv, cargo-llvm-cov) pass this repository's root, whose `mise.toml` follows the toolchains baseline.

mise reads the fallback root with only its own config: the caller's `MISE_ENV`, `MISE_<TOOL>_VERSION`,
`MISE_CONFIG_FILE`, `MISE_GLOBAL_CONFIG_FILE`, `MISE_OVERRIDE_CONFIG_FILENAMES`, `MISE_DEFAULT_CONFIG_FILENAME`,
`MISE_LOCKFILE` and `MISE_CONFIG_DIR` are unset there, and no config above the root applies. The step fails when
that lock lacks the selected version or the runner's platform for it, when the config selects more than one
version, or when a short name matches more than one of its tools.

### Trust

The script trusts the caller's working directory for its own mise calls through `MISE_TRUSTED_CONFIG_PATHS`, never
persisting it; a `MISE_TRUSTED_CONFIG_PATHS` the job sets is appended to, not replaced. It does so only on `push`,
`pull_request`, `schedule`, `workflow_dispatch`, `release`, `merge_group` and `workflow_call` runs, or with no
`GITHUB_EVENT_NAME` (a local run). On any other event, such as `pull_request_target` or `workflow_run`, an untrusted
config fails the step until the job sets `MISE_TRUSTED_CONFIG_PATHS` itself.

## Outputs

| Name    | Description                                                    |
| ------- | -------------------------------------------------------------- |
| `cache` | `true` or `false`: whether the mise data directory was cached. |

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
