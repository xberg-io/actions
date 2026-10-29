#!/usr/bin/env bash
# Runs a consumer's docs task through mise when its mise config defines it, else the given fallback command.
#
#   docs-runner.sh run <task> <fallback>...
set -euo pipefail

mise_defines() {
  command -v mise >/dev/null 2>&1 && mise tasks info "$1" >/dev/null 2>&1
}

run_docs_task() {
  local name="$1"
  shift
  if mise_defines "$name"; then
    echo "Running mise task $name"
    mise run "$name"
  else
    echo "No $name task in mise; running: $*"
    "$@"
  fi
}

case "${1:-}" in
run)
  shift
  [ "$#" -ge 2 ] || {
    echo "usage: docs-runner.sh run <task> <fallback command>..." >&2
    exit 2
  }
  run_docs_task "$@"
  ;;
*)
  echo "usage: docs-runner.sh run <task> <fallback command>..." >&2
  exit 2
  ;;
esac
