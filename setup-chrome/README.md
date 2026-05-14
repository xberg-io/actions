# setup-chrome

Install a Chrome-compatible browser for headless tests across Linux
(including `ubuntu-24.04-arm`), macOS, and Windows.

- **linux-arm64**: installs `chromium` via `apt-get` and symlinks it as
  `/usr/local/bin/google-chrome` and `/usr/local/bin/chrome`. Google
  does **not** ship Chrome for Testing on linux-arm64 — the
  [chrome-for-testing manifest][cft-manifest] only covers `linux64`,
  `mac-arm64`, `mac-x64`, `win32`, and `win64`, so `apt` chromium is
  the only available option on this runner architecture.
- **everything else**: delegates to [`browser-actions/setup-chrome`][upstream].

## Known limitation: chromium flag rejection on linux-arm64

The `chromium` package on Ubuntu `noble` is a snap-shim wrapper that
**rejects several flags real Chrome accepts**, including
`--use-mock-keychain`, `--disable-sync`, `--user-data-dir`, and
`--disable-client-side-phishing-detection`. Test harnesses that drive
Chrome with these flags (chromiumoxide, Puppeteer with default args,
etc.) will fail to launch on linux-arm64.

Consumers running browser tests on linux-arm64 should filter the
unsupported flags before invoking chromium, or skip the affected tests
on this architecture. There is no upstream fix available until Google
publishes arm64 Chrome for Testing builds.

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

| Name             | Required | Default  | Description                                                                                                                                |
| ---------------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `chrome-version` | no       | `stable` | Chrome channel (`stable`, `beta`, `dev`) or an explicit Chrome-for-Testing version. Ignored on linux-arm64, where chromium is installed via apt. |

[upstream]: https://github.com/browser-actions/setup-chrome
[cft-manifest]: https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json
