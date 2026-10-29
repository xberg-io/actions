#!/usr/bin/env bash
#MISE description="Format-check and lint Bats suites"
set -euo pipefail

# poly has no engine for the .bats extension, so these files are invisible to `poly lint`.
# shfmt 3.14 has a bats dialect and shellcheck parses `@test "x" { }` as bash, so both
# tools work here -- they just have to be invoked directly.
#
# Four codes are disabled, all of them structural to how Bats suites are written:
#   SC2016/SC2183  a stub body is single-quoted on purpose -- the expansion and the format
#                  string belong to the STUB, which runs later, not to the line writing it.
#   SC2030/SC2031  `run` forks, so shellcheck sees every export in setup() as "modified in
#                  a subshell". That fork is real and load-bearing (it is why a suite must
#                  call an exporting function directly rather than through `run`), but the
#                  warning fires on correct code 62 times and cannot distinguish the two.
# Everything else stays on. ~keep
suites=()
while IFS= read -r suite; do
  suites+=("$suite")
done < <(git ls-files "*.bats")
if [ "${#suites[@]}" -eq 0 ]; then
  echo "no *.bats suites found" >&2
  exit 1
fi
shfmt -ln bats -d "${suites[@]}"
shellcheck -s bash -e SC2016,SC2183,SC2030,SC2031 "${suites[@]}"
