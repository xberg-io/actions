# setup-wasm-pack

Install `wasm-pack` at a pinned version with OS/arch detection. Downloads
the matching prebuilt release from [rustwasm/wasm-pack][upstream] and places
the binary on `PATH`.

Supported targets:

- Linux x86_64 → `x86_64-unknown-linux-musl`
- Linux aarch64 → `aarch64-unknown-linux-musl`
- macOS x86_64 → `x86_64-apple-darwin`
- macOS aarch64 → `aarch64-apple-darwin`
- Windows x86_64 → `x86_64-pc-windows-msvc`

No-ops if the requested version is already on `PATH`.

## Usage

```yaml
- uses: xberg-io/actions/setup-wasm-pack@v1
```

With overrides:

```yaml
- uses: xberg-io/actions/setup-wasm-pack@v1
  with:
    wasm-pack-version: "0.13.1"
```

## Inputs

| Name                | Required | Default  | Description                                   |
| ------------------- | -------- | -------- | --------------------------------------------- |
| `wasm-pack-version` | no       | `0.13.1` | wasm-pack version (without the leading `v`).  |

[upstream]: https://github.com/rustwasm/wasm-pack
