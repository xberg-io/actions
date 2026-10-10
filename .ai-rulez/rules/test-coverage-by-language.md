---
type: Decision
title: Test Coverage By Language
x-ai-rulez:
  kind: rule
  id: test-coverage-by-language
  metadata:
    priority: critical
---

Every executable script in this repository carries tests in the framework for its language. There is no untested script and no untested language.

- **Shell (`*.sh`)** — Bats, in `<action>/tests/<name>.bats`. Run with `task test:bats`.
- **Python (`*.py`)** — pytest, in the root `tests/` directory as `tests/test_<action_name>.py`. Run with `task test:unit`. Split a suite that exceeds the 1000-line `file-too-long` lint at a natural seam — one file per script under test — rather than exempting it in `poly.toml`.
- **PowerShell (`*.ps1`)** — Pester, in `<action>/tests/<name>.Tests.ps1`. Run with `task test:pester`.

Adding a script means adding its tests in the same change. `task test` runs all three.

**A test must never depend on what the host machine happens to have installed.** This is the rule the others exist to protect, and it is written from a failure that cost a full day: several suites restricted `PATH` to `"$STUB_BIN:/usr/bin:/bin"` and called it isolation. It is not. The scripts under test decide their branch by probing `command -v <tool>`, and `ubuntu-latest` ships `gh`, `gpg2` and `dotnet` in `/usr/bin` where macOS does not — so the probe succeeded, the branch under test never ran, and the suite reported 118/118 green locally while two shipped actions were broken on every runner (`setup-zig` on macOS, `build-swift-package` on Linux). Local green proved nothing.

Isolate by **exclusion, not by allow-list**: mirror the host's command directories into a private directory *minus* the one command whose absence is the point, and assert the mirror really lacks it so a leak fails loudly. An allow-list of "the utilities this script needs" guesses at an implementation detail and breaks on the first indirect dependency — GNU `tar -xzf` shells out to `gzip`, BSD `tar` does not. In pytest, `monkeypatch` every `shutil.which`, subprocess call and environment variable; in Pester, `Mock` the probe. Never rely on a real binary being present or absent.

**Scripts must run under bash 3.2.** macOS ships it as `/bin/bash`, which is what `#!/usr/bin/env bash` resolves to on a macOS runner. No `mapfile`/`readarray`, no `${var^^}`, no associative arrays. Prefer GNU-form utility invocations with a BSD fallback in that order (`stat -c '%Y'` then `stat -f '%m'`): GNU-first fails cleanly on BSD, while BSD-first does *not* fail on GNU — `stat -f` is parsed as `--file-system` and prints filesystem details that flow onward as garbage.

**A green run is not evidence a test works.** Before trusting a test, break the thing it covers and watch it go red. A test that still passes when the code is broken is worse than no test, because it stops anyone looking. When a suite runs only on one platform in CI, say so rather than implying coverage it does not have; `-Skip` with a stated reason is honest, a test that pretends to exercise Windows behaviour on macOS is not.
