#!/usr/bin/env bash
#MISE description="Run Pester suites for PowerShell action scripts"
set -euo pipefail

PESTER_VERSION="6.2.0"

if ! command -v pwsh >/dev/null 2>&1; then
  echo "pwsh is required for the Pester suites. Install PowerShell 7 or newer." >&2
  exit 1
fi
if ! pwsh -NoProfile -Command \
  "exit [int](@(Get-Module -ListAvailable Pester).Version -notcontains [version]'$PESTER_VERSION')"; then
  echo "Pester $PESTER_VERSION is missing. Install it with:" \
    "Install-Module Pester -RequiredVersion $PESTER_VERSION -Scope CurrentUser" >&2
  exit 1
fi

# -PassThru and an explicit exit: a plain Invoke-Pester prints the failures and still
# returns 0, which would leave this task green with a red suite. ~keep
#
# Suites are DISCOVERED, not listed. `bats --recursive .` picks up a new action's tests with
# zero registration and Pester must behave the same way -- a hand-maintained path list is
# how a suite ends up written, committed, and never run. `git ls-files` also keeps .venv and
# every other untracked tree out of the walk without needing an exclude list. ~keep
# shellcheck disable=SC2016 # $suites is PowerShell's, expanded by pwsh, not bash
pwsh -NoProfile -Command '
  $suites = @(git ls-files "*.Tests.ps1")
  if ($suites.Count -eq 0) { throw "no *.Tests.ps1 suites found" }
  exit (Invoke-Pester -Path $suites -Output Detailed -PassThru).FailedCount'
