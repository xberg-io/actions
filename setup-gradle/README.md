# setup-gradle

Install Gradle and Java via [`gradle/actions/setup-gradle`][upstream] with
xberg-io defaults. Works on `ubuntu-24.04-arm` and the other standard
GitHub-hosted runners.

## Usage

```yaml
- uses: xberg-io/actions/setup-gradle@v1
```

With overrides:

```yaml
- uses: xberg-io/actions/setup-gradle@v1
  with:
    gradle-version: "8.11"
    java-version: "21"
    cache-cleanup: "on-success"
```

## Inputs

| Name             | Required | Default      | Description                                                         |
| ---------------- | -------- | ------------ | ------------------------------------------------------------------- |
| `gradle-version` | no       | `8.11`       | Gradle version installed by the upstream action.                    |
| `java-version`   | no       | `21`         | Java version to install via Temurin.                                |
| `cache-cleanup`  | no       | `on-success` | Cache cleanup policy forwarded to `gradle/actions/setup-gradle@v4`. |

[upstream]: https://github.com/gradle/actions/tree/main/setup-gradle
