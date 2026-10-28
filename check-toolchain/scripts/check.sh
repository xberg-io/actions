#!/usr/bin/env bash
set -euo pipefail

working_directory="${1:-.}"
toolchains_url="${TOOLCHAINS_REPOSITORY_URL:-https://github.com/xberg-io/toolchains}"
manifest="$working_directory/toolchains.toml"

if [[ ! -f "$manifest" ]]; then
  echo "::error file=$manifest::$manifest not found; it must record the baseline tag, e.g. baseline = \"v1.0.0\"" >&2
  exit 2
fi

baseline_ref="$(
  python3 - "$manifest" <<'PYTHON'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    ref = tomllib.load(handle).get("baseline")
if not isinstance(ref, str) or not ref.strip():
    raise SystemExit(f"{sys.argv[1]}: missing a string `baseline` key, e.g. baseline = \"v1.0.0\"")
print(ref.strip())
PYTHON
)"

checkout="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/toolchains.XXXXXX")"
trap 'rm -rf "$checkout"' EXIT

echo "Checking $working_directory against xberg-io/toolchains $baseline_ref"
git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$baseline_ref" "$toolchains_url" "$checkout"

python3 "$checkout/scripts/toolchains.py" check --baseline "$checkout/baseline.toml" --repo "$working_directory"
