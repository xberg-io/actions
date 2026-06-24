# setup-swift

Install the Swift toolchain on Linux (including `ubuntu-24.04-arm`), macOS,
and Windows. Wraps [`SwiftyLab/setup-swift`][upstream], which supports
aarch64 Linux runners. The widely-used `swift-actions/setup-swift@v2`
currently returns a corrupted binary on `ubuntu-24.04-arm`, so prefer this
action everywhere.

No-ops if `swift` is already resolvable on `PATH`.

## Usage

```yaml
- uses: xberg-io/actions/setup-swift@v1
```

With overrides:

```yaml
- uses: xberg-io/actions/setup-swift@v1
  with:
    swift-version: "6.0"
```

## Inputs

| Name            | Required | Default | Description                              |
| --------------- | -------- | ------- | ---------------------------------------- |
| `swift-version` | no       | `6.0`   | Swift version passed to SwiftyLab setup. |

[upstream]: https://github.com/SwiftyLab/setup-swift
