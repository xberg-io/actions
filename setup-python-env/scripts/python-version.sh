#!/usr/bin/env bash
# Report the version of the Python first on PATH, the one mise selected, as the step's `version` output.
set -euo pipefail

python="$(command -v python || command -v python3 || true)"
if [[ -z "$python" ]]; then
  echo "::error::no python on PATH after the mise install" >&2
  exit 1
fi
version="$("$python" -c 'import platform; print(platform.python_version())' | tr -d '\r')"
echo "Python $version at $python"
echo "version=$version" >>"$GITHUB_OUTPUT"
