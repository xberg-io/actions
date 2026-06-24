# setup-maven

Install Maven and Java runtime in a cross-platform way.

## Inputs

- `version` (default: `"3.9.11"`) — Maven version to install
- `java-version` (default: `"21"`) — Java version to install

## Example

```yaml
- uses: xberg-io/actions/setup-maven@v1
  with:
    version: "3.9.11"
    java-version: "21"

- name: Verify setup
  run: |
    mvn --version
    java -version
```

## Platforms

Works on `ubuntu-24.04-arm` and other standard GitHub-hosted runners.
