# setup-maven

Install Maven through mise, at the version the caller's `mise.toml` and `mise.lock` select. Java must be set up
first, for example with `setup-mise`.

## Inputs

- `version` (default: `""`) — Maven version, matched against the caller's mise locks; empty uses `mise.toml`'s.

## Example

```yaml
- uses: xberg-io/actions/setup-mise@v1
  with:
    tools: java

- uses: xberg-io/actions/setup-maven@v1

- name: Verify setup
  run: |
    mvn --version
    java -version
```

The caller's `mise.toml` declares `maven` (and `java`), e.g. `maven = "3.10.0"`.

## Platforms

Works on `ubuntu-24.04-arm` and other standard GitHub-hosted runners.
