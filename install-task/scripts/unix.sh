#!/usr/bin/env bash
set -euo pipefail

version="${1:-latest}"
install_dir="${2:-}"

task_bin_dir="${install_dir:-${RUNNER_TEMP:-${HOME}/.local}/task-bin}"
mkdir -p "$task_bin_dir"
task_bin_dir="$(cd "$task_bin_dir" && pwd)"

if [[ -z "${MISE_GITHUB_TOKEN:-}" && -n "${GITHUB_TOKEN:-}" ]]; then
  export MISE_GITHUB_TOKEN="$GITHUB_TOKEN"
fi
export MISE_HTTP_TIMEOUT="${MISE_HTTP_TIMEOUT:-5m}"
# setup-mise exports MISE_LOCKED=1 for the repository's lock; this install is outside that lock. ~keep
export MISE_LOCKED=false

max_attempts=6

# Run a mise network call, retrying with exponential backoff; release lookups and downloads fail transiently.
retry() {
  local attempt=1
  local wait_time=5
  until "$@"; do
    if [[ $attempt -ge $max_attempts ]]; then
      echo "Error: '$*' failed after ${max_attempts} attempts" >&2
      return 1
    fi
    echo "'$*' failed (attempt ${attempt}/${max_attempts}); retrying in ${wait_time}s" >&2
    sleep "$wait_time"
    attempt=$((attempt + 1))
    wait_time=$((wait_time * 2))
  done
}

# Run outside the checkout: a repository mise.toml must neither decide this version nor have its mise.lock
# rewritten by this install. ~keep
cd "${RUNNER_TEMP:-$(mktemp -d)}"

if [[ -z "$version" || "$version" == "latest" ]]; then
  version="$(retry mise latest task)"
  if [[ -z "$version" ]]; then
    echo "Error: mise could not resolve the latest Task release" >&2
    exit 1
  fi
  echo "Resolved 'latest' to v${version}"
else
  version="${version#v}"
fi

echo "Installing Task v${version}"
retry mise install "task@${version}"
task_path="$(mise which task --tool "task@${version}")"
cp "$task_path" "$task_bin_dir/task"
chmod +x "$task_bin_dir/task"

echo "Task is ready at $task_bin_dir/task"
"$task_bin_dir/task" --version
echo "$task_bin_dir" >>"$GITHUB_PATH"
