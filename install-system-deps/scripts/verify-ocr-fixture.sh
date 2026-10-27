#!/usr/bin/env bash
set -euo pipefail

binary="${1:?selected Tesseract executable required}"
tessdata="${2:?existing tessdata directory required}"
work_dir="$(mktemp -d)"
[ -n "$work_dir" ] && [ -d "$work_dir" ] || exit 1
trap 'rm -rf "$work_dir"' EXIT
base=https://raw.githubusercontent.com/tesseract-ocr/test/232ff181c66516116ec0e84c4963f70de15050fd
# ~keep Apache-2.0 upstream integration fixture and oracle; a 60-token smoke check, not a quality benchmark.
for filename in phototest.tif phototest.gold.txt; do
  curl --retry 3 --max-time 120 -fsSL -o "$work_dir/$filename" "$base/testing/$filename"
done
checksum_command=(sha256sum)
if ! command -v sha256sum >/dev/null 2>&1; then checksum_command=(shasum -a 256); fi
printf '%s  %s\n' \
  d2241a1eb6d6cd2eb6544b8e228c2862c852b7467d16ed636caa32179b780692 "$work_dir/phototest.tif" \
  76ef157baeb6ab275b7d90f310477a8060d5822aea2b2e05d480f459b016a6ed "$work_dir/phototest.gold.txt" | "${checksum_command[@]}" -c -
curl --retry 3 --max-time 120 -fsSL -o "$work_dir/LICENSE" "$base/LICENSE"
printf '%s  %s\n' c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4 "$work_dir/LICENSE" | "${checksum_command[@]}" -c -
"$binary" "$work_dir/phototest.tif" stdout --tessdata-dir "$tessdata" -l eng --psm 3 >"$work_dir/actual.txt"
python3 - "$work_dir" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
expected = (root / 'phototest.gold.txt').read_text().split()
actual = (root / 'actual.txt').read_text().split()
if len(expected) != 60 or actual != expected:
    raise RuntimeError(f'English OCR smoke: expected 60 exact tokens, received {len(actual)}')
print(json.dumps({'expected_inputs': 1, 'actual_ocr_inputs': 1, 'expected_tokens': 60, 'actual_tokens': len(actual)}))
PY
printf 'not an image' >"$work_dir/invalid.tif"
if "$binary" "$work_dir/invalid.tif" stdout --tessdata-dir "$tessdata" -l eng >"$work_dir/invalid-output" 2>&1; then
  echo 'Malformed image negative control was accepted' >&2
  exit 1
fi
echo 'Malformed OCR input rejected'
