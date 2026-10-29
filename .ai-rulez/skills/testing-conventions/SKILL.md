---
type: Playbook
title: Testing Conventions
description: "How to test scripts in xberg-io/actions: Bats/pytest/Pester layout, isolating tests from host tools, bash 3.2 portability, proving a test discriminates. Use when writing or fixing tests or when a suite passes locally but fails in CI."
paths:
  - "**/*.sh"
  - "**/*.py"
  - "**/*.ps1"
  - "**/*.bats"
x-ai-rulez:
  kind: skill
  id: testing-conventions
  metadata:
    name: testing-conventions
---

## Testing conventions (xberg-io/actions)

Every action in this repo is a script plus a thin `action.yml`. The scripts are the product; the tests are how we know a change to one does not silently break a consumer's pipeline.

### Which framework, and where

Framework, test location and `mise run` task per language are in the `test-coverage-by-language` rule.

Split a Python suite that exceeds the 1000-line `file-too-long` lint at a natural seam (one file per script under test) rather than exempting it in `poly.toml`.

Python suites live in the root `tests/` rather than beside the action because they share `tests/conftest.py` fixtures (`tmp_path_with_files`, `github_output`). Bats and Pester suites live beside their action, matching how the runner resolves them.

### The failure this repo actually had

Read this before writing a test that touches a tool.

Several Bats suites set `PATH="$STUB_BIN:/usr/bin:/bin"` and treated that as isolation. The scripts under test choose a branch by probing `command -v gh` / `gpg2` / `dotnet`. `ubuntu-latest` ships those in `/usr/bin`; macOS does not. So on CI the probe succeeded, the script took the already-installed branch, and **the branch under test never executed**. The suite reported 118/118 passing on a dev machine while two shipped actions were broken on every runner:

- `setup-zig` used `mapfile`, a bash 4 builtin. macOS ships bash 3.2 as `/bin/bash`, which `#!/usr/bin/env bash` resolves to on a macOS runner. It died with `mapfile: command not found` and then read the resolved URL and version out of an empty array. Broken for every macOS consumer.
- `build-swift-package` tried BSD `stat -f '%m'` before GNU `stat -c '%Y'`. On Linux, GNU `stat` does not reject `-f` — it reads it as `--file-system` and prints filesystem details starting `File: ...`, which reached an arithmetic comparison and aborted under `set -u`. Broken for every Linux consumer.

Both were real product bugs the suite was correctly reporting; they had been dismissed as "flaky platform-specific tests".

### Isolating from the host

**Exclude, do not allow-list.** Mirror the host's command directories into a private directory *minus* the one command whose absence is the point, then assert the mirror really lacks it so a leak fails loudly instead of quietly restoring the host's copy.

An allow-list ("link in the utilities this script needs") guesses at an implementation detail and breaks on the first indirect dependency: GNU `tar -xzf` shells out to `gzip`, BSD `tar` does not, so a curated bin that omits `gzip` fails on Linux and passes on macOS.

```bash
# helpers in bats-lib/xberg-bats (bats_load_library xberg-bats); see ensure-gh/tests/unix.bats
setup_file() { bats_load_library xberg-bats; xberg_shadow_system_path_without gh; }
setup() { bats_load_library xberg-bats; xberg_setup_isolated; }
run env PATH="$(xberg_isolated_path)" ...   # stubs ahead of the mirror, minus gh
```

In pytest, `monkeypatch` every `shutil.which`, every `subprocess.run`, and every environment variable the script reads; prove it by running the suite with `env PATH=/nonexistent`. In Pester, `Mock` the probe (`Mock Get-Command`, `Mock Invoke-WebRequest`) rather than touching the real `PATH`.

### Portability constraints for scripts

- **bash 3.2 is the floor** (forbidden constructs listed in the rule). Derive with `tr` instead of `^^`.
- **GNU form first, BSD fallback second.** `stat -c '%Y' || stat -f '%m'`. GNU-first fails cleanly on BSD; BSD-first silently succeeds on GNU and emits garbage.
- Verify with `bash --version` on a macOS runner, not locally, unless your local `/bin/bash` is genuinely 3.2.

### Proving a test discriminates

A green run is not evidence. Before trusting a test, break what it covers and watch it fail:

```bash
# python: mutate the script, run, restore, run
# bats:   break one assertion, confirm red, restore
```

Mutation-test the whole set when you add a suite. Two recent examples of why: one pytest suite had a test that still passed when the guard it covered was deleted, because control fell through to a different guard emitting superset stderr — fixed by asserting stderr exactly. A Bats fix was read as "unchanged" because the same test number kept failing, when it had actually moved from failing at line 54 to line 74 for a different reason.

### Honesty about coverage

Pester suites run on `windows-latest` in CI. Locally on macOS or Linux, cover the portable logic (parsing, URL and filename construction, arch mapping, error paths) and mark genuinely Windows-dependent behaviour `-Skip` with a stated reason. A skipped test that says why is honest. A test that pretends to exercise Windows behaviour on macOS is not, and it will be believed.

When a CI-only failure shows an assertion and no reason, the runner is not printing test output: Bats needs `--print-output-on-failure`, Pester needs `Output.Verbosity = 'Detailed'` in its configuration (`-Output Detailed` on the command line). Both are set in the workflows; keep them.
