#!/usr/bin/env bash
set -euo pipefail

version="${1:-latest}"
install_dir="${2:-}"

task_bin_dir="${install_dir:-${RUNNER_TEMP:-${HOME}/.local}/task-bin}"
mkdir -p "$task_bin_dir"

resolve_latest_version() {
  # The upstream taskfile.dev/install.sh resolves "latest" via godownloader's
  # GitHub-tag lookup which intermittently returns an empty tag
  # ("unable to find ''" -> "Failed to install Task after 3 attempts").
  # Pre-resolve via the GitHub API ourselves so we can pass an explicit tag.
  local api_url="https://api.github.com/repos/go-task/task/releases/latest"
  local auth_args=()
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    auth_args=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi
  curl --proto '=https' \
    --tlsv1.2 \
    --fail \
    --silent \
    --show-error \
    --location \
    --connect-timeout 10 \
    --max-time 30 \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -H "Accept: application/vnd.github+json" \
    "${auth_args[@]}" \
    "$api_url" |
    grep -oE '"tag_name":[[:space:]]*"[^"]+"' |
    head -1 |
    sed -E 's/.*"tag_name":[[:space:]]*"([^"]+)".*/\1/'
}

install_task() {
  local max_attempts=3
  local attempt=1
  local wait_time=2

  local resolved_version="$version"
  if [[ "$resolved_version" == "latest" || -z "$resolved_version" ]]; then
    local latest
    if latest=$(resolve_latest_version) && [[ -n "$latest" ]]; then
      echo "Resolved 'latest' to ${latest}"
      resolved_version="$latest"
    else
      echo "Warning: failed to pre-resolve 'latest' via GitHub API; falling back to installer default" >&2
    fi
  fi

  while [[ $attempt -le $max_attempts ]]; do
    echo "Installing Task ${resolved_version} (attempt ${attempt}/${max_attempts})..."

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
      if [[ -n "$resolved_version" && "$resolved_version" != "latest" ]]; then
        install_args+=("$resolved_version")
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
