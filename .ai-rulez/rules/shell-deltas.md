---
type: Decision
title: Shell Deltas
paths:
  - "**/*.sh"
  - "**/*.bash"
  - "**/*.bats"
x-ai-rulez:
  kind: rule
  id: shell-deltas
  metadata:
    priority: high
---

Actions-specific exception to the shared `shell` rule: the xberg-bats helpers are authored here in `bats-lib/xberg-bats`, not vendored. Suites load them with `bats_load_library xberg-bats` with `BATS_LIB_PATH` set to `bats-lib/` (`task test:bats`; `lib-path: bats-lib` in CI). Do not add a `tests/lib/xberg-bats` copy.
