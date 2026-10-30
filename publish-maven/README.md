# Publish Maven artifacts

The default path runs the project's existing Maven deployment. With `setup-java: true` (the default) the action
installs Java through mise, from the caller's `mise.toml` unless `java-version` is set, and writes the
`~/.m2/settings.xml` server entry for `server-id` that `actions/setup-java` wrote, with `${env.MAVEN_USERNAME}` and
`${env.MAVEN_PASSWORD}` references. Set `required-notice-files` to enable a final-byte gate:

```yaml
with:
  pom-file: packages/java/pom.xml
  maven-profile: publish
  expected-version: ${{ needs.prepare.outputs.version }}
  server-id: ossrh
  extra-args: -DskipTests
  canonical-root: .
  required-notice-files: |
    THIRD_PARTY_LICENSES
```

Guarded mode supports one release component using the Central publishing extension **0.12.0**, with the standard
main, sources and javadoc JARs plus POM. Maven's ordinary deploy plugin must have `skip=true`. The effective POM is
checked before deployment; snapshots, reactors, alternate providers, execution-specific Central configuration,
implicit `.mvn` configuration, custom bundle paths and unsupported plugins fail closed. Extra arguments are limited
to `-DskipTests` and `-Dmaven.test.skip` boolean properties. Missing `expected-version` fails.

The build uses `-DskipUpload=true` with credential-free user/global Maven settings and removes Central credentials
from the Maven environment. GPG signing remains available. The final bundle must contain the four expected artifacts,
four detached signatures and sixteen checksum files. Every checksum and signature is verified. Required notice bytes
must equal the canonical files under `META-INF/` in the main and sources JARs; javadoc is checked for inventory and
signature integrity without imposing a root LICENSE requirement.

Central parameter properties in the effective POM are rejected, including deprecated parameters and output overrides.
Set supported publication and waiting options explicitly in the Central plugin configuration.

The verified bundle is retained in memory and uploaded once through Central's public API. Effective `autoPublish`,
`waitUntil`, `waitMaxTime` and `waitPollingInterval` settings control automatic versus staged publication and waiting.
Manual deployments are never automatically released. Registry conflicts and failed validation fail the guarded run;
there is no broad already-published-success fallback. A guarded dry run builds and validates the bundle without upload.

Authentication uses the existing `MAVEN_USERNAME`, `MAVEN_PASSWORD` and `MAVEN_GPG_PASSPHRASE` environment variables.
Canonical notices and the shared archive verifier come from the checked-out Actions revision; no source is rewritten.
