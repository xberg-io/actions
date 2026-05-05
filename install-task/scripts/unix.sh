#!/usr/bin/env bash
set -euo pipefail

version="${1:-latest}"
install_dir="${2:-}"

task_bin_dir="${install_dir:-${RUNNER_TEMP:-${HOME}/.local}/task-bin}"
mkdir -p "$task_bin_dir"

install_task() {
  local max_attempts=3
  local attempt=1
  local wait_time=2

  while [[ $attempt -le $max_attempts ]]; do
    echo "Installing Task ${version} (attempt ${attempt}/${max_attempts})..."

    local installer
    installer="${RUNNER_TEMP:-$(mktemp -d)}/task-install.sh"
    if curl --proto '=https' \
      --tlsv1.2 \
      --fail \
      --silent \
      --show-error \
      --location \
      --connect-timeout 10 \
      --max-time 30 \
      --retry 2 \
      --retry-delay 1 \
      https://taskfile.dev/install.sh \
      --output "$installer"; then

      local install_args=(-b "$task_bin_dir")
      if [[ -n "$version" && "$version" != "latest" ]]; then
        install_args+=("$version")
      fi

      if sh "$installer" "${install_args[@]}"; then

        if [[ -x "$task_bin_dir/task" ]]; then
          echo "Task installation successful"
          return 0
        else
          echo "Error: Task binary not found at $task_bin_dir/task"
          rm -f "$task_bin_dir/task"
        fi
      fi
    else
      echo "Download/installation failed"
    fi

    attempt=$((attempt + 1))
    if [[ $attempt -le $max_attempts ]]; then
      echo "Retrying in ${wait_time}s..."
      sleep "$wait_time"
      wait_time=$((wait_time * 2))
    fi
  done

  echo "Error: Failed to install Task after ${max_attempts} attempts" >&2
  return 1
}

install_task

if [[ ! -x "$task_bin_dir/task" ]]; then
  echo "Error: Task binary not found or not executable at $task_bin_dir/task" >&2
  exit 1
fi

echo "Task is ready at $task_bin_dir/task"
"$task_bin_dir/task" --version
echo "$task_bin_dir" >>"$GITHUB_PATH"
