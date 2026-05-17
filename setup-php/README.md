# setup-php

Install PHP runtime with Composer and optional global tools.

## Inputs

- `php-version` (default: `"8.4"`) — PHP version to install
- `coverage` (default: `"none"`) — Coverage driver: `none`, `xdebug`, or `pcov`
- `extensions` (default: `""`) — Comma-separated PHP extensions to install (e.g., `pdo_sqlite,curl`)
- `tools` (default: `""`) — Comma-separated list of global tools to install (e.g., `phpstan,psalm,composer`)

## Example

```yaml
- uses: kreuzberg-dev/actions/setup-php@v1
  with:
    php-version: "8.2"
    coverage: "pcov"
    extensions: "pdo_sqlite"
    tools: "phpstan,psalm"

- name: Verify tools
  run: |
    phpstan --version
    psalm --version
```
