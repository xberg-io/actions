#!/usr/bin/env bash
set -euo pipefail

error() {
  echo "::error::$*" >&2
  exit 1
}

is_within_directory() {
  local path="$1"
  local parent="$2"

  [[ "$path" == "$parent" || "$path" == "$parent/"* ]]
}

if ! command -v bats >/dev/null 2>&1; then
  error "bats is not on PATH. Run install-bats before run-bats."
fi

workspace_input="${GITHUB_WORKSPACE:-$PWD}"
if ! workspace="$(cd "$workspace_input" && pwd -P)"; then
  error "GitHub workspace does not exist: ${workspace_input}."
fi

working_directory_input="${INPUT_WORKING_DIRECTORY:-}"
if [[ -z "$working_directory_input" ]]; then
  working_directory_input="$PWD"
elif [[ "$working_directory_input" != /* ]]; then
  working_directory_input="$PWD/${working_directory_input}"
fi
if ! working_directory="$(cd "$working_directory_input" && pwd -P)"; then
  error "Working directory does not exist: ${working_directory_input}."
fi
if ! is_within_directory "$working_directory" "$workspace"; then
  error "Working directory must be inside GITHUB_WORKSPACE."
fi

test_path_input="${INPUT_PATH:-tests}"
if [[ -z "$test_path_input" ]]; then
  error "Bats test path must not be empty."
fi
if [[ "$test_path_input" == /* ]]; then
  candidate_path="$test_path_input"
else
  candidate_path="${working_directory}/${test_path_input}"
fi

if [[ ! -e "$candidate_path" ]]; then
  error "Bats test path does not exist: ${test_path_input}."
fi
if [[ -L "$candidate_path" ]]; then
  error "Bats test path must not be a symbolic link."
fi

if [[ -d "$candidate_path" ]]; then
  test_path="$(cd "$candidate_path" && pwd -P)"
else
  test_parent="$(cd "$(dirname "$candidate_path")" && pwd -P)"
  test_path="${test_parent}/$(basename "$candidate_path")"
fi

if ! is_within_directory "$test_path" "$workspace"; then
  error "Bats test path must be inside GITHUB_WORKSPACE."
fi
if ! is_within_directory "$test_path" "$working_directory"; then
  error "Bats test path must be inside the working directory."
fi

lib_path_input="${INPUT_LIB_PATH:-}"
if [[ -n "$lib_path_input" ]]; then
  if [[ "$lib_path_input" == /* ]]; then
    lib_candidate="$lib_path_input"
  else
    lib_candidate="${working_directory}/${lib_path_input}"
  fi

  if [[ ! -d "$lib_candidate" ]]; then
    error "Bats library path does not exist: ${lib_path_input}."
  fi
  if [[ -L "$lib_candidate" ]]; then
    error "Bats library path must not be a symbolic link."
  fi

  lib_path="$(cd "$lib_candidate" && pwd -P)"

  if ! is_within_directory "$lib_path" "$workspace"; then
    error "Bats library path must be inside GITHUB_WORKSPACE."
  fi
  if ! is_within_directory "$lib_path" "$working_directory"; then
    error "Bats library path must be inside the working directory."
  fi
  # BATS_LIB_PATH is colon-delimited, so a colon anywhere in the resolved path would split
  # into two entries that each resolve to nothing, and `bats_load_library` would report a
  # missing library rather than a malformed path. ~keep
  if [[ "$lib_path" == *:* ]]; then
    error "Bats library path must not contain a colon."
  fi

  export BATS_LIB_PATH="${lib_path}${BATS_LIB_PATH:+:${BATS_LIB_PATH}}"
fi

bats_args=()
if [[ -n "${INPUT_ARGS:-}" ]]; then
  while IFS= read -r argument || [[ -n "$argument" ]]; do
    if [[ -z "$argument" ]]; then
      error "args must be newline-delimited arguments without empty lines."
    fi
    bats_args+=("$argument")
  done <<<"$INPUT_ARGS"
fi

# `args` defaults to "", so bats_args is routinely empty, and bash before 4.4 -- /bin/bash on a
# macOS runner -- treats "${empty[@]}" as unbound under `set -u`. ~keep
bats ${bats_args[@]+"${bats_args[@]}"} "$test_path"
