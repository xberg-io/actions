#!/usr/bin/env bash
# Install Zig on Linux/macOS by resolving the requested version against
set -euo pipefail

version="${1:-latest}"

case "$(uname -s)" in
Linux) os="linux" ;;
Darwin) os="macos" ;;
*)
  echo "Unsupported OS: $(uname -s)" >&2
  exit 1
  ;;
esac

case "$(uname -m)" in
x86_64 | amd64) arch="x86_64" ;;
aarch64 | arm64) arch="aarch64" ;;
*)
  echo "Unsupported arch: $(uname -m)" >&2
  exit 1
  ;;
esac

platform="${arch}-${os}"
install_dir="${RUNNER_TEMP:-${HOME}/.local}/zig"
mkdir -p "$install_dir"

resolve_url() {
  local v="$1"
  python3 - "$v" "$platform" <<'PY'
import json
import re
import sys
import urllib.request

requested, platform = sys.argv[1], sys.argv[2]
with urllib.request.urlopen("https://ziglang.org/download/index.json", timeout=30) as fh:
    data = json.load(fh)

if requested == "latest":
    # Pick the lexicographically-greatest stable tag (everything except "master").
    candidates = [k for k in data.keys() if k != "master"]
    candidates.sort(key=lambda s: [int(x) for x in s.split(".")])
    key = candidates[-1]
elif requested == "master":
    key = "master"
elif requested in data:
    key = requested
else:
    sys.exit(f"Zig version {requested!r} not in ziglang.org index")

entry = data[key]
asset = entry.get(platform)
if not asset or "tarball" not in asset:
    sys.exit(f"No {platform} asset for Zig {key}")

checksum = asset.get("shasum", "")
size = str(asset.get("size", ""))
if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum) or not size.isdecimal() or int(size) <= 0:
    sys.exit(f"Missing or malformed checksum/size for Zig {key} {platform}")
print(asset["tarball"])
print(entry.get("version", key))
print(checksum.lower())
print(size)
PY
}

# ~keep Read into the array by hand rather than with `mapfile`. `mapfile`/`readarray` is a
# bash 4 builtin and macOS ships bash 3.2 as /bin/bash, which is what `#!/usr/bin/env bash`
# resolves to on a macos runner -- the script died there with `mapfile: command not found`
# and then took the resolved URL and version from an empty array.
info=()
while IFS= read -r line; do
  info+=("$line")
done < <(resolve_url "$version")
if [[ ${#info[@]} -ne 4 ]]; then
  echo "Could not resolve complete Zig download metadata" >&2
  exit 1
fi
url="${info[0]}"
resolved_version="${info[1]}"
expected_sha256="${info[2]}"
expected_size="${info[3]}"

echo "Resolved Zig $version -> $resolved_version"
echo "Downloading $url"

archive="$install_dir/zig.tar.xz"
attempt=1
max_attempts=3
while ((attempt <= max_attempts)); do
  if curl --proto '=https' --tlsv1.2 --fail --location \
    --connect-timeout 10 --max-time 600 \
    --retry 2 --retry-delay 1 \
    --output "$archive" "$url"; then
    break
  fi
  echo "Download attempt $attempt failed" >&2
  attempt=$((attempt + 1))
  sleep 2
done
if ((attempt > max_attempts)); then
  echo "Failed to download Zig from $url" >&2
  exit 1
fi

python3 - "$archive" "$expected_sha256" "$expected_size" <<'PYVERIFY'
import hashlib
import pathlib
import sys

archive = pathlib.Path(sys.argv[1])
if archive.stat().st_size != int(sys.argv[3]):
    sys.exit("Zig archive size mismatch")
checksum = hashlib.sha256()
with archive.open("rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        checksum.update(block)
if checksum.hexdigest() != sys.argv[2]:
    sys.exit("Zig archive SHA-256 mismatch")
PYVERIFY

extraction_dir="$(mktemp -d "$install_dir/toolchain.XXXXXX")"
tar -xJf "$archive" -C "$extraction_dir"
extracted_dir="$extraction_dir/$(basename "$url" .tar.xz)"
if [[ ! -d "$extracted_dir" || ! -x "$extracted_dir/zig" ]]; then
  echo "Could not locate extracted zig directory under $install_dir" >&2
  exit 1
fi

actual_version="$("$extracted_dir/zig" version)"
if [[ "$actual_version" != "$resolved_version" ]]; then
  echo "Expected Zig $resolved_version, found $actual_version" >&2
  exit 1
fi
echo "$extracted_dir" >>"$GITHUB_PATH"
printf '%s\n' "$actual_version"
