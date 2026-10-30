# setup-wasm-pack

Install `wasm-pack` through mise, at the version the caller's `mise.toml` and `mise.lock` select, and put it on
`PATH`. The caller declares it by its backend, since mise's registry has no `wasm-pack` entry:

```toml
[tools]
"github:rustwasm/wasm-pack" = "0.15.0"
```

## Usage

```yaml
- uses: xberg-io/actions/setup-wasm-pack@v1
```

With an override, matched against the caller's mise locks and installed unlocked when no lock covers it:

```yaml
- uses: xberg-io/actions/setup-wasm-pack@v1
  with:
    wasm-pack-version: "0.15.0"
```

## Inputs

| Name                | Required | Default | Description                                             |
| ------------------- | -------- | ------- | ------------------------------------------------------- |
| `wasm-pack-version` | no       | `""`    | wasm-pack version; empty uses the caller's `mise.toml`. |
