#!/usr/bin/env bash
set -euo pipefail

label="${1:?label required}"
cache_dir_prefix="${2:?cache-dir-prefix required}"

mkdir -p "${cache_dir_prefix}/${label}"
mkdir -p ".xdg-cache/${label}"
