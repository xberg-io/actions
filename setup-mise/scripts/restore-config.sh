#!/usr/bin/env bash
set -euo pipefail

working_directory="${1:-.}"
config_ref="${2:-}"

if [[ -z "$config_ref" || -f "$working_directory/mise.toml" ]]; then
  exit 0
fi

# An older checkout may predate the directory as well as its config.
mkdir -p "$working_directory"
repo_root="$(git -C "$working_directory" rev-parse --show-toplevel)"
prefix="$(git -C "$working_directory" rev-parse --show-prefix)"

echo "No mise.toml in $working_directory; restoring the mise config from $config_ref"
git -C "$repo_root" fetch --quiet --no-tags --depth 1 origin "$config_ref"

files=()
has_config=false
while IFS= read -r path; do
  if [[ "$(basename "$path")" =~ ^mise(\.[^/]+)?\.(toml|lock)$ ]]; then
    files+=("$path")
    [[ "$path" == "${prefix}mise.toml" ]] && has_config=true
  fi
done < <(git -C "$repo_root" ls-tree --name-only FETCH_HEAD -- "${prefix:-.}")

if [[ "$has_config" != true ]]; then
  echo "::error::$config_ref has no ${prefix}mise.toml either; nothing to install from" >&2
  exit 1
fi

git -C "$repo_root" checkout FETCH_HEAD -- "${files[@]}"
printf 'Restored from %s: %s\n' "$config_ref" "${files[*]}"
