---
type: Decision
title: Test Coverage By Language
paths:
  - "**/*.sh"
  - "**/*.py"
  - "**/*.ps1"
  - "**/*.bats"
x-ai-rulez:
  kind: rule
  id: test-coverage-by-language
  metadata:
    priority: critical
---

- Every executable script carries tests in its language's framework; adding a script means adding its tests in the same change.
- Shell `*.sh`: Bats in `<action>/tests/<name>.bats` (`mise run test:bats`).
- Python `*.py`: pytest in root `tests/test_<action_name>.py` (`mise run test:unit`).
- PowerShell `*.ps1`: Pester in `<action>/tests/<name>.Tests.ps1` (`mise run test:pester`).
- `mise run test` runs all three.
- A test never depends on what the host has installed: isolate by exclusion, not by a `PATH` allow-list.
- Scripts run under bash 3.2 (macOS `/bin/bash`): no `mapfile`/`readarray`, `${var^^}`, or associative arrays; GNU utility form first, BSD fallback second.
- Break the covered code and watch the test go red before trusting it.
- Call `load_skill` with `name: testing-conventions` for the isolation recipe, the history behind these rules, and coverage-honesty guidance.
