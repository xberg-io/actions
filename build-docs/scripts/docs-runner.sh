#!/usr/bin/env bash
# Picks the runner for a consumer's docs task while repositories move from go-task to mise tasks.
#
#   docs-runner.sh needs-task <task>...       print "true" when go-task must be installed to run any of them
#   docs-runner.sh run <task> <fallback>...   run the task with mise, then go-task, else run the fallback
#
# A task defined in mise wins. go-task is only considered when a Taskfile exists in the working directory or
# above it (where go-task looks), and only for a task that Taskfile lists. Everything else runs the fallback.
set -euo pipefail

mise_defines() {
  command -v mise >/dev/null 2>&1 && mise tasks info "$1" >/dev/null 2>&1
}

taskfile_present() {
  local dir="$PWD" name
  while :; do
    for name in Taskfile.yml taskfile.yml Taskfile.yaml taskfile.yaml \
      Taskfile.dist.yml taskfile.dist.yml Taskfile.dist.yaml taskfile.dist.yaml; do
      [ -f "$dir/$name" ] && return 0
    done
    [ "$dir" = "/" ] && return 1
    dir="$(dirname "$dir")"
  done
}

task_defines() {
  command -v task >/dev/null 2>&1 && taskfile_present &&
    task --list-all --json 2>/dev/null | grep -Fq "\"name\": \"$1\""
}

needs_task() {
  local name
  if command -v task >/dev/null 2>&1; then
    echo false
    return
  fi
  for name in "$@"; do
    if ! mise_defines "$name" && taskfile_present; then
      echo true
      return
    fi
  done
  echo false
}

run_docs_task() {
  local name="$1"
  shift
  if mise_defines "$name"; then
    echo "Running mise task $name"
    mise run "$name"
  elif task_defines "$name"; then
    echo "Running go-task task $name"
    task "$name"
  else
    echo "No $name task in mise or a Taskfile; running: $*"
    "$@"
  fi
}

case "${1:-}" in
needs-task)
  shift
  needs_task "$@"
  ;;
run)
  shift
  [ "$#" -ge 2 ] || {
    echo "usage: docs-runner.sh run <task> <fallback command>..." >&2
    exit 2
  }
  run_docs_task "$@"
  ;;
*)
  echo "usage: docs-runner.sh needs-task <task>... | run <task> <fallback command>..." >&2
  exit 2
  ;;
esac
