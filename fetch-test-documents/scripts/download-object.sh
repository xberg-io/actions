#!/usr/bin/env bash
# Downloads one content-addressed object into the cache store, verifying its sha256. Invoked once
# per unique object, in parallel, by fetch.sh via xargs -P.
#
# Args: $1 = sha256, $2 = bucket name, $3 = cache dir (objects live at <cache-dir>/objects/<sha256>)
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${script_dir}/lib.sh"

sha="$1"
bucket="$2"
cache_dir="$(to_posix_path "$3")"

objects_dir="${cache_dir}/objects"
mkdir -p "$objects_dir"
dest="${objects_dir}/${sha}"

if [[ -f "$dest" ]] && [[ "$(sha256_of "$dest")" == "$sha" ]]; then
  echo "cached: ${sha}"
  exit 0
fi

url="https://storage.googleapis.com/${bucket}/objects/${sha}"
tmp="$(mktemp "${objects_dir}/.download.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

echo "downloading: ${url}"
# curl's own --retry cannot cover curl dying: on windows-latest, under `xargs -P 8`, one of 190
# concurrent Git-for-Windows curl processes took a SIGSEGV, `set -e` aborted this script, and the
# whole corpus fetch failed with xargs exit 123 -- a green run and this one differed by one crashed
# child process, nothing else. So a death by signal (128+n) is retried here, at the process level.
# Ordinary nonzero exits are deliberately NOT retried again: curl already applied --retry-all-errors
# to those internally, and repeating them would only slow a genuinely missing object down. ~keep
attempt=1
attempts=3
while :; do
  rc=0
  curl --proto '=https' \
    --tlsv1.2 \
    --fail \
    --silent \
    --show-error \
    --location \
    --connect-timeout 10 \
    --max-time 300 \
    --retry 3 \
    --retry-delay 2 \
    --retry-all-errors \
    "$url" \
    --output "$tmp" || rc=$?

  if [[ "$rc" -lt 128 ]] || [[ "$attempt" -ge "$attempts" ]]; then
    break
  fi
  echo "::warning::curl died with signal $((rc - 128)) downloading ${sha}; retrying (attempt $((attempt + 1)) of ${attempts})" >&2
  attempt=$((attempt + 1))
  sleep 2
done

if [[ "$rc" -ne 0 ]]; then
  exit "$rc"
fi

actual="$(sha256_of "$tmp")"
if [[ "$actual" != "$sha" ]]; then
  echo "::error::checksum mismatch downloading ${url}: expected ${sha}, got ${actual}" >&2
  exit 1
fi

mv "$tmp" "$dest"
trap - EXIT
echo "fetched: ${sha}"
