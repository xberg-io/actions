# setup-mise

Install [mise][mise] (pinned to 2026.10.21) through [`jdx/mise-action`][action] and the tools declared in the
repository's `mise.toml`. When a `mise.lock` sits next to it, the install runs as `mise install --locked`: a lock
that does not cover the declared versions or the runner's platform fails the job instead of resolving afresh.

Works on GitHub-hosted Ubuntu (x64 and arm64), macOS and Windows runners. Also:

- exports `MISE_RUBY_COMPILE=false` unless already set, so Ruby installs use precompiled builds;
- respects a `MISE_DATA_DIR` already present in the runner environment (self-hosted images with preinstalled
  tools) and caches that directory instead of the default one;
- caches the mise data directory keyed on the mise config and lock files, `MISE_ENV`, OS and arch.

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
| `cache`             | no       | `true`                  | Cache the mise data directory.                                   |

Generate the lock for every CI platform with
`mise lock --platform linux-x64,linux-arm64,macos-arm64,windows-x64`.

[mise]: https://mise.jdx.dev
[action]: https://github.com/jdx/mise-action
