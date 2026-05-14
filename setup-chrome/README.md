# setup-chrome

Install Google Chrome / Chromium via [`browser-actions/setup-chrome`][upstream].
Works on Linux (including `ubuntu-24.04-arm`), macOS, and Windows.

## Usage

```yaml
- uses: kreuzberg-dev/actions/setup-chrome@v1
```

With overrides:

```yaml
- uses: kreuzberg-dev/actions/setup-chrome@v1
  with:
    chrome-version: "stable"
```

## Inputs

| Name             | Required | Default  | Description                                                                              |
| ---------------- | -------- | -------- | ---------------------------------------------------------------------------------------- |
| `chrome-version` | no       | `stable` | Chrome channel (`stable`, `beta`, `dev`) or an explicit Chromium build version. |

[upstream]: https://github.com/browser-actions/setup-chrome
