# setup-gradle

Install Java and Gradle through mise, at the versions the caller's `mise.toml` and `mise.lock` select, and
configure Gradle's dependency and build caches with [`gradle/actions/setup-gradle`][upstream]. Works on
`ubuntu-24.04-arm` and the other standard GitHub-hosted runners.

## Usage

```yaml
- uses: xberg-io/actions/setup-gradle@v1
```

The caller's `mise.toml` declares both tools:

```toml
[tools]
java = "temurin-25.0.5+8.0.LTS"
gradle = "9.6.0"
```

With overrides, matched against the caller's mise locks and installed unlocked when no lock covers them:

```yaml
- uses: xberg-io/actions/setup-gradle@v1
  with:
    gradle-version: "9.6.0"
    java-version: "21"
    cache-cleanup: "on-success"
```

## Inputs

| Name             | Required | Default      | Description                                                                 |
| ---------------- | -------- | ------------ | --------------------------------------------------------------------------- |
| `gradle-version` | no       | `""`         | Gradle version; empty uses the caller's `mise.toml`.                        |
| `java-version`   | no       | `""`         | Temurin Java version (`21` selects `temurin-21`); empty uses `mise.toml`'s. |
| `cache-cleanup`  | no       | `on-success` | Cache cleanup policy forwarded to `gradle/actions/setup-gradle@v6`.         |

[upstream]: https://github.com/gradle/actions/tree/main/setup-gradle
