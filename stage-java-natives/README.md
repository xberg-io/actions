# stage-java-natives

Stage `java-natives-*` artifacts (produced by [build-java-natives](../build-java-natives))
into a Maven resources tree at `{resources-dir}/{classifier}/{libfile}` and
verify every required classifier is present. Pairs with `build-java-natives`
on the build side and `publish-maven` on the publish side.

The action assumes artifacts were downloaded with `merge-multiple: true`,
which leaves the build-java-natives output layout (`native/{classifier}/{libfile}`)
intact at the artifacts-dir root.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `artifacts-dir` | no | `artifacts/java-natives` | Directory the `java-natives-*` artifacts were downloaded into. |
| `resources-dir` | yes | — | Maven resources dir. Libraries are staged as `{resources-dir}/{classifier}/{libfile}`. |
| `required-classifiers` | yes | — | Whitespace-separated list of classifiers that must all be present. |
| `lib-name` | yes | — | Library base name (e.g. `xberg_ffi`). Used to verify each classifier has a matching lib. |

## Usage

```yaml
- uses: actions/download-artifact@v8
  with:
    pattern: java-natives-*
    path: artifacts/java-natives
    merge-multiple: true

- uses: xberg-io/actions/stage-java-natives@v1
  with:
    resources-dir: packages/java/src/main/resources/natives
    required-classifiers: linux-x86_64 linux-aarch64 macos-arm64 macos-x86_64 windows-x86_64 windows-aarch64
    lib-name: ts_pack_core_ffi
```

## Notes

- Uses `merge-multiple: true` on the upstream download — every artifact
  shares the `native/{classifier}/{libfile}` layout, so merging is safe.
- The script copies via `shutil.copy2`, preserving mtimes. Existing files in
  the destination are overwritten silently.
- Verification matches the library by substring on `lib-name`, so it works
  for both `lib{lib_name}.so`/`.dylib` and `{lib_name}.dll`.
