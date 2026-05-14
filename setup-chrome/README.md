# setup-chrome

Install Google Chrome for headless browser tests across Linux (including
`ubuntu-24.04-arm`), macOS, and Windows.

- **linux-arm64**: downloads the official
  [`chrome-for-testing`](https://googlechromelabs.github.io/chrome-for-testing/)
  Linux ARM64 build from Google's storage bucket and links it as
  `/usr/local/bin/google-chrome`. The Ubuntu apt `chromium` package on
  `noble` is a snap shim that rejects standard Chrome flags
  (`--use-mock-keychain`, `--disable-sync`, `--user-data-dir`,
  `--disable-client-side-phishing-detection`) and breaks
  chromiumoxide-style automation, so we install the real Chrome instead.
- **everything else**: delegates to [`browser-actions/setup-chrome`][upstream].

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

| Name             | Required | Default  | Description                                                                                                                          |
| ---------------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `chrome-version` | no       | `stable` | Chrome channel (`stable`, `beta`, `dev`) or an explicit Chrome-for-Testing version. On linux-arm64 channels resolve via the chrome-for-testing last-known-good-versions feed. |

[upstream]: https://github.com/browser-actions/setup-chrome
