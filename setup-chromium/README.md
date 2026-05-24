# setup-chromium

Install non-snap Chromium for headless browser e2e tests on Ubuntu runners.

## Why separate from setup-chrome?

The standard `setup-chrome` action delegates to `browser-actions/setup-chrome@v1` on x86_64 Ubuntu runners, which may pull the snap-wrapped `chromium` package from apt. Snap-wrapped Chromium rejects command-line flags:

```text
error: unknown command "----disable-features=..." see 'snap help'.
error: unknown flag `no-sandbox'
error: unknown flag `headless'
```

This action uses Playwright's browser installer to provision a native, non-sandboxed Chromium binary that accepts all standard launch flags.

## Inputs

None required.

## Outputs

| Output | Description |
|--------|-------------|
| `chromium-path` | Absolute path to the Chromium binary |

## Example Usage

### With direct binary execution

```yaml
- uses: kreuzberg-dev/actions/setup-chromium@v1
  id: chromium

- name: Run headless tests
  run: |
    "${{ steps.chromium.outputs.chromium-path }}" \
      --headless \
      --no-sandbox \
      --disable-features=TranslateUI \
      --dump-dom https://example.com
```

### With environment variable

```yaml
- uses: kreuzberg-dev/actions/setup-chromium@v1
  id: chromium

- name: Run e2e tests
  env:
    CHROMIUM_BIN: ${{ steps.chromium.outputs.chromium-path }}
  run: |
    task brew:e2e:test
```

## Supported Platforms

- Linux (amd64, arm64)
- macOS (x64, arm64)
- Windows

## How It Works

1. Sets up Node.js 20 (required for Playwright tooling)
2. Installs Playwright test framework via npm (which downloads bundled Chromium)
3. Extracts and verifies the Chromium binary path
4. Outputs the path for downstream consumption
5. Verifies the binary accepts headless flags

The Chromium binary is cached by Playwright across runs and does not require network access after the initial install.
