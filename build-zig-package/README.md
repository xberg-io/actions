# build-zig-package

Build the workspace FFI crate the Zig package links against and run
`zig build` as a smoke check. Zig packages publish via Git tag tarballs, so
this action verifies that the FFI artifact and `zig build` are healthy
rather than producing an upload artifact. Pair with
`xberg-io/actions/publish-zig@v1` for the tarball-and-tag flow.

## Usage

```yaml
- uses: actions/checkout@v4
- uses: xberg-io/actions/setup-rust@v1
- uses: xberg-io/actions/build-zig-package@v1
  id: zig_build
  with:
    ffi-crate: xberg-ffi
    package-dir: packages/zig
- run: echo "FFI lib at ${{ steps.zig_build.outputs.ffi-library-path }}"
```

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `ffi-crate` | no | `xberg-ffi` | Workspace FFI crate Zig links against. |
| `package-dir` | no | `packages/zig` | Directory containing `build.zig` and `build.zig.zon`. |
| `build-profile` | no | `release` | Cargo profile for the FFI crate (`release`, `dev`, or custom). |
| `setup-zig` | no | `true` | Install Zig via `mlugg/setup-zig`. |
| `zig-version` | no | `0.16.0` | Zig version, passed to `mlugg/setup-zig`. |
| `dry-run` | no | `false` | Print the planned commands and exit without building. |

## Outputs

| Name | Description |
|---|---|
| `ffi-library-path` | Absolute path to the built FFI library that Zig links against. |

## Notes

- The action assumes the caller already ran `actions/checkout` and a Rust
  toolchain action (e.g. `xberg-io/actions/setup-rust@v1`).
- After `cargo build` succeeds, `zig build` runs in `package-dir`. If
  `build.zig` declares a `test` step (`b.step("test", ...)`), `zig build
  test` runs as well.
- The FFI library name follows Cargo's convention: dashes in the crate
  name become underscores (`xberg-ffi` -> `libxberg_ffi.{so,dylib}`,
  `xberg_ffi.dll`).
- `dev`/`debug` profiles map to `target/debug/`; everything else maps to
  `target/<profile>/`.
- Zig publication still happens via `publish-zig`; this action does not
  upload anything.
