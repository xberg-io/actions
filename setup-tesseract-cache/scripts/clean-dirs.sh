#!/usr/bin/env bash
set -euo pipefail

label="${1:?label required}"
cache_dir_prefix="${2:?cache-dir-prefix required}"

rm -rf "${cache_dir_prefix:?cache-dir-prefix missing}/${label:?label missing}"
rm -rf ".xdg-cache/${label:?label missing}"
