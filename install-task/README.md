# install-task

Deprecated: declare `task` in `mise.toml` and use [`setup-mise`](../setup-mise/README.md), so Task's version is
locked and checked against the org baseline like every other tool.

Install the [Task](https://taskfile.dev) CLI through mise and put it on `PATH`. The action installs only the mise
binary (no shims, no repository env), then runs `mise install task@<version>` outside the checkout, so a repository
`mise.toml` neither decides the version nor gets its lock rewritten. It sets `MISE_LOCKED=false` for that install,
since `setup-mise` may have exported `MISE_LOCKED=1` for the repository's lock, and `MISE_HTTP_TIMEOUT=5m` unless
already set. The release lookup and the install are each retried up to 6 times with exponential backoff (5s, 10s,
20s, 40s, 80s).

## Usage

```yaml
- uses: xberg-io/actions/install-task@v1
  with:
    version: "3.54.0"
```

## Inputs

| Name           | Required | Default               | Description                                                                 |
| -------------- | -------- | --------------------- | --------------------------------------------------------------------------- |
| `version`      | no       | `latest`              | Task version, with or without a leading `v`; `latest` resolves through mise. |
| `install-dir`  | no       | `$RUNNER_TEMP/task-bin` | Directory for the binary; a relative path resolves against the step's directory. |
| `github-token` | no       | `${{ github.token }}` | Token for the release lookup and download.                                  |
