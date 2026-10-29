# Verify package contents

The default action checks the existing language-specific filename patterns. Set
`required-notice-files` to additionally compare packaged notices with canonical
release-source bytes. Notice and inventory failures always fail, even with
`strict: "false"`.

```yaml
- uses: xberg-io/actions/verify-package-contents@v1
  with:
    language: java
    artifact-path: packages/java/target/library-1.0.jar
    required-notice-files: THIRD_PARTY_LICENSES.md
    canonical-root: .
    artifact-format: jar
    expected-artifact-count: "1"
```

Check out the release source containing the canonical files before invoking the
action. Run this gate after all repairs and repacks, before uploading those same
artifacts. A publisher that rebuilds after this step needs a check inside its final
publication boundary as well.

| Input                     | Behavior                                                                                                                                                                                             |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `required-notice-files`   | Newline-separated paths relative to `canonical-root`. Empty input keeps legacy behavior; whitespace-only inventories fail. Source files must be regular, nonempty files inside the canonical root.   |
| `canonical-root`          | Release-source directory, default `.`. Its bytes must correspond to the artifact's release, including when helper scripts come from a newer workflow revision.                                       |
| `artifact-format`         | `wheel`, `sdist`, `gem`, `jar`, `nuget`/`nupkg`, `hex`, or `auto`. Empty means `auto`. Explicit formats filter directory scans by extension; an explicit file is checked using the requested format. |
| `expected-artifact-count` | Optional exact positive count after format filtering. Omission allows any nonzero inventory. Zero, invalid counts, empty sweeps and count mismatches fail.                                           |

Format/count options require a nonempty notice inventory. Auto mode recognizes
`.whl`, `.tar.gz`/`.tgz` (sdist), `.gem`, `.jar`, `.nupkg`, and `.tar` (Hex).
Use explicit formats for other archive suffixes.

| Format | Notice payload                                                                                                                                                                                                                                |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| wheel  | `*.dist-info/licenses/<notice>` anchored to the single distribution `METADATA` file.                                                                                                                                                          |
| sdist  | `<distribution>/<notice>`, alongside its actual distribution `pyproject.toml` and `PKG-INFO`; every requested notice must be declared by `project.license-files`. Split-layout Rust dependencies cannot supply a missing distribution notice. |
| gem    | `<notice>` inside the single regular outer `data.tar.gz` member.                                                                                                                                                                              |
| jar    | `META-INF/<notice>`, including source JARs when selected. No root `LICENSE` is implicitly required.                                                                                                                                           |
| nuget  | `<notice>` at the `.nupkg` ZIP root.                                                                                                                                                                                                          |
| hex    | `<notice>` inside the single regular outer `contents.tar.gz` member.                                                                                                                                                                          |

Checks reject altered bytes, missing notices, nonregular entries, duplicate
effective paths and case aliases of expected notice paths. Unrelated
case-sensitive Java payload names remain distinct. Archives are read without
extracting files. Registry-specific envelope, identity, signatures and publication
checks remain the caller's responsibility. The action provisions Python 3.13 only
when notice verification is enabled. Direct helper callers need Python 3.11 or
newer for sdist TOML parsing; the other formats support Python 3.10 or newer.

The pure standard-library helper in `scripts/notices.py` is also available to
publisher scripts:

```python
canonical = load_notices(canonical_root, ["THIRD_PARTY_LICENSES.md"])
verify_archive_bytes(payload, "jar", canonical)
```

`load_notices` returns a `dict[str, bytes]`. `verify_archive_bytes` returns `None`
on success and raises `NoticeVerificationError`, a `ValueError` subclass, on
verification failure. Empty notice sets are errors at this helper boundary.
