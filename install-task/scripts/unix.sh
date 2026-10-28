#!/usr/bin/env bash
set -euo pipefail

version="${1:-latest}"
install_dir="${2:-}"

task_bin_dir="${install_dir:-${RUNNER_TEMP:-${HOME}/.local}/task-bin}"
mkdir -p "$task_bin_dir"

if [[ -z "${MISE_GITHUB_TOKEN:-}" && -n "${GITHUB_TOKEN:-}" ]]; then
  export MISE_GITHUB_TOKEN="$GITHUB_TOKEN"
fi

# Run outside the checkout: a repository mise.toml must neither decide this version nor have its mise.lock
# rewritten by this install. ~keep
cd "${RUNNER_TEMP:-$(mktemp -d)}"

if [[ -z "$version" || "$version" == "latest" ]]; then
  version="$(mise latest task)"
  if [[ -z "$version" ]]; then
    echo "Error: mise could not resolve the latest Task release" >&2
    exit 1
  fi
  echo "Resolved 'latest' to v${version}"
else
  version="${version#v}"
fi

echo "Installing Task v${version}"
mise install "task@${version}"
task_path="$(mise which task --tool "task@${version}")"
cp "$task_path" "$task_bin_dir/task"
chmod +x "$task_bin_dir/task"

echo "Task is ready at $task_bin_dir/task"
"$task_bin_dir/task" --version
echo "$task_bin_dir" >>"$GITHUB_PATH"
