# Publish Hex packages

The default path preserves the existing Mix publishing behavior. Set `required-notice-files` to enable final-byte
publication of a prebuilt package through Hex's public HTTP API:

```yaml
with:
  tarball-path: packages/elixir/xberg-1.2.3.tar
  expected-package: xberg
  expected-version: ${{ needs.prepare.outputs.version }}
  canonical-root: .
  required-notice-files: |
    THIRD_PARTY_LICENSES
```

Guarded mode requires a single version-3 Hex tarball, `expected-package`, `expected-version` and regular canonical
notice files. It verifies the outer envelope checksum, parses embedded metadata with Erlang's data-only
`:file.consult`, checks the package name/version, and compares canonical notice bytes inside `contents.tar.gz`.
It sends the exact same tarball bytes to `https://hex.pm/api/packages/NAME/releases`; it does not run a Mix build,
fetch dependencies or regenerate native files. Only public Hex package publication with `HEX_API_KEY` is supported;
private repositories and OAuth are outside this mode. `replace` is forwarded to the API. Documentation is not
published by this package-only path.

A guarded dry run performs all validation and sends no registry requests. Missing or stale notices, malformed
metadata, mismatched versions and registry conflicts fail the action. A conflict is never treated as success merely
because a package version exists. Release tags may include a leading `v` or a `-dryrun-<sha>` suffix.
