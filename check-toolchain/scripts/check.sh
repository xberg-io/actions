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

if [[ "$baseline_ref" == -* ]]; then
  echo "::error file=$manifest::baseline \"$baseline_ref\" is not a valid tag name" >&2
  exit 2
fi

# A branch would let the baseline move under the repository without a reviewed bump of toolchains.toml. ~keep
status=0
git ls-remote --exit-code --tags "$toolchains_url" "refs/tags/$baseline_ref" >/dev/null || status=$?
if [[ $status -eq 2 ]]; then
  echo "::error file=$manifest::baseline \"$baseline_ref\" is not a tag of $toolchains_url; pin a release tag such as v1.0.0" >&2
  exit 2
elif [[ $status -ne 0 ]]; then
  echo "::error::could not list the tags of $toolchains_url (git exit $status); check network access and credentials" >&2
  exit "$status"
fi

checkout="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/toolchains.XXXXXX")"
trap 'rm -rf "$checkout"' EXIT

echo "Checking $working_directory against xberg-io/toolchains $baseline_ref"
# Fetch the tag by its full refname: `clone --branch` prefers a branch of the same name. ~keep
git -C "$checkout" init --quiet
git -C "$checkout" fetch --quiet --no-tags --depth 1 "$toolchains_url" "refs/tags/$baseline_ref:refs/tags/$baseline_ref"
git -C "$checkout" -c advice.detachedHead=false checkout --quiet "refs/tags/$baseline_ref"

python3 "$checkout/scripts/toolchains.py" check --baseline "$checkout/baseline.toml" --repo "$working_directory"
