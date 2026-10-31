# Build Node NAPI bindings

`build-node-napi` builds one NAPI-RS target, stages its platform package and optionally packs it for release.

For `target: aarch64-unknown-linux-gnu` with `use-napi-cross: "true"`, the action uses the caller's
mise-pinned `zig` and `github:rust-cross/cargo-zigbuild`. Declare and lock both tools in the caller repository.
Other targets retain their existing cross-compilation behavior.

The NAPI target and npm platform package stay `aarch64-unknown-linux-gnu` and `linux-arm64-gnu`.
An action-owned Cargo subprocess adapter selects `aarch64-unknown-linux-gnu.2.17` only for `cargo zigbuild`,
retaining the glibc 2.17 runtime floor without the old NAPI GCC linker's Rust metadata warnings.
The adapter does not change the parent environment, Cargo metadata calls, warning policies or other Rust flags.

Normal project `.cargo/config.toml` target linker defaults are overridden by cargo-zigbuild's managed linker.
Explicit linker/compiler environment overrides, linker-selecting Rust flags, and file-based Cargo `--config`
overrides fail closed in this mode; inline config unrelated to linker selection remains supported.

Run the action's subprocess contract tests with:

```bash
mise exec -- uv run pytest tests/test_build_node_napi_gnu_arm.py
```
