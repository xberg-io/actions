# configure-maven-gpg

Prepare the GPG environment for Maven publishing. Two concerns rolled into one action:

1. If `gpg2` is on the runner, shim it as `gpg` on PATH so the Maven GPG plugin invokes the right binary.
2. Patch the legacy two-arg `<arg>--pinentry-mode</arg><arg>loopback</arg>` form in `pom.xml` to the single-arg `<arg>--pinentry-mode=loopback</arg>` form, which works across all Maven GPG plugin versions.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `pom-file` | no | `packages/java/pom.xml` | Path to the `pom.xml` to patch. |
| `patch-pom` | no | `true` | Whether to patch the pom. |
| `prefer-gpg2` | no | `true` | Whether to install a `gpg2` shim. |

## Example

```yaml
- uses: xberg-io/actions/configure-maven-gpg@v1
  with:
    pom-file: packages/java/pom.xml
```
