# Shared Bats helper library

`xberg-bats/load.bash` is the one copy of the setup, stubbing, and assertion helpers that every
xberg-io Bats suite uses. This directory is the **source of truth**; consumer repositories carry a
committed copy.

## Using it

```bash
setup() {
  bats_load_library xberg-bats
  xberg_setup
}
```

`bats_load_library` searches `$BATS_LIB_PATH` and nothing else — despite an error message that
mentions the test file's directory, `bats_load_library_safe` only ever iterates `BATS_LIB_PATH`.
Set it two ways, and set both, or a suite passes locally and fails in CI:

| Where     | How                                                                             |
| --------- | ------------------------------------------------------------------------------- |
| mise task | `env = { BATS_LIB_PATH = "{{config_root}}/tests/lib" }` on the `test:bats` task |
| CI        | `lib-path: tests/lib` on the `run-bats` step                                    |

## Why consumers vendor a copy instead of fetching it

Two reasons, both load-bearing:

- **`install-bats` refuses to run outside GitHub Actions.** It writes `$GITHUB_PATH` and errors
  when that variable is unset, so a library shipped inside the action would make
  `bats scripts/tests` impossible on a laptop.
- **CI and the developer must load identical bytes.** A helper resolved from one place locally and
  another in CI reintroduces exactly the local-green/CI-red class that
  `xberg_shadow_system_path_without` exists to kill.

Refresh a vendored copy with `mise run test:scripts:lib:sync` (the xberg-io/toolchains `bats-lib`
task set); `mise run test:scripts:lib:check` fails when it has drifted from the pinned
`xberg-io/actions` ref.

## Choosing a PATH strategy

This is the decision the library exists to make explicit, and getting it wrong produces a suite
that passes against broken code.

- **`xberg_setup`** prepends a stub directory to the host `PATH`. Correct when the test is about
  what the script _does_ and the host's real utilities are fine.
- **`xberg_setup_isolated` + `xberg_shadow_system_path_without <cmd>`** mirrors the host's system
  bins minus one command. Required when the script _probes_ for a command (`command -v gh`) and
  the branch it takes is the thing under test.

`PATH="$STUB_BIN:/usr/bin:/bin"` is the broken middle ground. It states nothing about what the
host supplies: `ensure-gh`'s suite used it, ubuntu-latest ships `gh` in `/usr/bin` and macOS does
not, so the probe found a real `gh` on CI and took the already-installed branch instead of the one
under test. Green locally, red in CI.

`xberg_shadow_system_path_without` asserts both of its own preconditions — that no excluded
command leaked into the mirror, and that the mirror is not implausibly small. A mirror of nothing
would make every test in the file pass for the wrong reason.

## `run` forks — this will bite you

`run` executes in a subshell. A function that communicates by `export` therefore appears to export
nothing when called through `run`:

```bash
run setup_onnx_paths          # WRONG: the export is discarded with the subshell
[ "$LD_LIBRARY_PATH" = "/opt/ort:" ]   # passes against a function that exports nothing

setup_onnx_paths >/dev/null   # RIGHT: call it directly
[ "$LD_LIBRARY_PATH" = "/opt/ort:" ]
```

Use `run` only where the status or the output _is_ the contract.

## Stub bodies do not get `set -eu`

`xberg_stub` writes the shebang but deliberately not `set -eu`. A stub's job is to emit canned
output and an exit code, and errexit turns an intentionally-false test (`[ "$1" = run ]`) into a
surprise exit that reads as the script under test misbehaving. A stub that genuinely wants errexit
can open its own body with it.

Note that bats 1.14.0 changed `run` to honour `set -e` inside called functions, which earlier
versions suppressed. Suites written against an older bats may surface new failures on upgrade.

## Linting

`poly` has no engine for the `.bats` extension, so these files are invisible to `poly lint`.
`mise run lint:bats` runs `shfmt -ln bats` and `shellcheck -s bash` over them instead. Four codes are
disabled there, all structural to Bats: `SC2016`/`SC2183` (a stub body is single-quoted on
purpose) and `SC2030`/`SC2031` (`run` forks, so every `setup()` export reads as subshell-local).

`**/*.bats` stays in `poly.toml`'s `file_safety` exclude for a measured reason: poly reports a
newly added `.bats` file as non-executable even when it is staged `100755`, while a `.sh` staged
identically passes. Without the exclude, every commit that introduces a suite is blocked.
