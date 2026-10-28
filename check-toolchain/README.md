# check-toolchain

Fail when a repository's `mise.toml` drifts from the [xberg-io/toolchains][toolchains] baseline. Reads `baseline`
from `toolchains.toml`, shallow-clones the toolchains repository at that tag and runs its
`scripts/toolchains.py check`. Overrides recorded in `toolchains.toml` are honoured by that script.

Exit codes follow the checker: 1 on drift, 2 when nothing could be checked. A missing `toolchains.toml` or a
missing `baseline` key fails before the clone.

Runs on Linux and macOS runners; it needs `git` and Python 3.11 or newer, both present on GitHub-hosted images.

## Usage

```yaml
- uses: actions/checkout@v7
- uses: xberg-io/actions/check-toolchain@v1
```

## Inputs

| Name                | Required | Default | Description                                         |
| ------------------- | -------- | ------- | --------------------------------------------------- |
| `working-directory` | no       | `.`     | Repository root holding `mise.toml` and `toolchains.toml`. |

[toolchains]: https://github.com/xberg-io/toolchains
