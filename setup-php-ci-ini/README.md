# setup-php-ci-ini

Generate a `php.ini` for CI that loads a locally-built
[`ext-php-rs`](https://github.com/davidcole1340/ext-php-rs) extension and
preloads bundled extensions required by `phpunit` (`dom`, `mbstring`,
`tokenizer`, etc.). Detects the runner OS to pick the right shared-library
suffix, locates the built extension under `target/release` or
`target/debug`, and discovers the active PHP runtime's `extension_dir` so
`php -c <ini> vendor/bin/phpunit` resolves bundled extensions correctly.

Run after `cargo build --package <crate-name>`. Then invoke phpunit with
`php -c <ini> vendor/bin/phpunit`.

## Usage

```yaml
- uses: xberg-io/actions/setup-php-ci-ini@v1
  id: php-ini
  with:
    crate-name: kreuzcrawl-php

- run: php -c "${{ steps.php-ini.outputs.ini-path }}" vendor/bin/phpunit
```

With overrides:

```yaml
- uses: xberg-io/actions/setup-php-ci-ini@v1
  with:
    crate-name: kreuzberg-php
    output-name: php-kreuzberg.ini
    extensions: "ctype dom libxml mbstring tokenizer xml xmlwriter json"
    build-dir-priority: "target/release target/debug"
```

## Inputs

| Name                 | Required | Default                                       | Description                                                                                  |
| -------------------- | -------- | --------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `crate-name`         | yes      | —                                             | ext-php-rs crate name (`kreuzcrawl-php`). Library file derived via `s/-/_/g` plus OS suffix. |
| `output-dir`         | no       | `.`                                           | Directory to write the ini into.                                                             |
| `output-name`        | no       | `php-kreuzcrawl.ini`                          | Ini filename written under `output-dir`.                                                     |
| `extensions`         | no       | `ctype dom libxml mbstring tokenizer xml xmlwriter` | Space-separated PHP bundled extensions to preload.                                  |
| `build-dir-priority` | no       | `target/release target/debug`                 | Space-separated build dirs to search. First hit wins.                                        |

## Outputs

| Name       | Description                            |
| ---------- | -------------------------------------- |
| `ini-path` | Absolute path to the generated ini.    |

## Notes

- Linux runners use `lib<crate>.so`, macOS `lib<crate>.dylib`, Windows
  `<crate>.dll` (crate name with `-` replaced by `_`).
- Discovers `extension_dir` via `php -r 'echo ini_get("extension_dir");'`
  first, falling back to `php-config --extension-dir`.
- Fails fast if the extension cannot be located or `extension_dir` cannot
  be resolved.
