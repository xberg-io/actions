#!/usr/bin/env bash
set -euo pipefail

working_directory="${1:-.}"
config_ref="${2:-}"

if [[ -z "$config_ref" || -f "$working_directory/mise.toml" ]]; then
  exit 0
fi

if [[ "$config_ref" == -* ]]; then
  echo "::error::config-ref \"$config_ref\" is not a valid git ref" >&2
  exit 1
fi

# An older checkout may predate the directory as well as its config.
mkdir -p "$working_directory"
repo_root="$(git -C "$working_directory" rev-parse --show-toplevel)"
prefix="$(git -C "$working_directory" rev-parse --show-prefix)"

echo "No mise.toml in $working_directory; restoring the mise config from $config_ref"
# `fetch --depth 1` of a commit a full clone already has makes that clone shallow, cutting the history a release
# job may need. Use a present commit as is, and only fetch shallowly into a checkout that is already shallow. ~keep
if [[ "$config_ref" =~ ^[0-9a-f]{40}$ ]] && git -C "$repo_root" cat-file -e "${config_ref}^{commit}" 2>/dev/null; then
  source_ref="$config_ref"
else
  depth_args=()
  if [[ "$(git -C "$repo_root" rev-parse --is-shallow-repository)" == true ]]; then
    depth_args=(--depth 1)
  fi
  if ! git -C "$repo_root" fetch --quiet --no-tags ${depth_args[@]+"${depth_args[@]}"} origin "$config_ref"; then
    echo "::error::could not fetch $config_ref from origin to restore the mise config. The checkout needs" \
      "credentials for origin (keep actions/checkout's persist-credentials enabled, the default) and the ref" \
      "must exist there." >&2
    exit 1
  fi
  source_ref="$(git -C "$repo_root" rev-parse FETCH_HEAD)"
fi

files=()
has_config=false
while IFS= read -r -d '' path; do
  name="$(basename "$path")"
  # Local overrides are per-developer and never belong in a CI install. ~keep
  if [[ "$name" =~ ^mise(\.[^/]+)?\.(toml|lock)$ && ! "$name" =~ (^|\.)local\. ]]; then
    files+=("$path")
    [[ "$path" == "${prefix}mise.toml" ]] && has_config=true
  fi
done < <(git -C "$repo_root" ls-tree -z --name-only "$source_ref" -- "${prefix:-.}")

if [[ "$has_config" != true ]]; then
  echo "::error::$config_ref has no ${prefix}mise.toml either; nothing to install from" >&2
  exit 1
fi

# mise.toml's file tasks live in mise-tasks/; without them every `mise run` in the older checkout fails. ~keep
tasks_dir="${prefix}mise-tasks"
if [[ ! -e "$repo_root/$tasks_dir" && "$(git -C "$repo_root" cat-file -t "$source_ref:$tasks_dir" 2>/dev/null)" == tree ]]; then
  files+=("$tasks_dir")
fi

# Worktree only, and excluded: later steps that gate on a clean `git status` or `git diff` must not see the
# restored files as changes. ~keep
git -C "$repo_root" restore --source="$source_ref" --worktree -- "${files[@]}"
exclude_file="$(git -C "$repo_root" rev-parse --git-path info/exclude)"
[[ "$exclude_file" == /* ]] || exclude_file="$repo_root/$exclude_file"
mkdir -p "$(dirname "$exclude_file")"
for path in "${files[@]}"; do
  if ! grep -qxF "/$path" "$exclude_file" 2>/dev/null; then
    printf '/%s\n' "$path" >>"$exclude_file"
  fi
done
printf 'Restored from %s: %s\n' "$config_ref" "${files[*]}"
