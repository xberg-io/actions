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

print(asset["tarball"])
print(entry.get("version", key))
PY
}

mapfile -t info < <(resolve_url "$version")
url="${info[0]}"
resolved_version="${info[1]}"

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

tar -xJf "$archive" -C "$install_dir"
extracted_dir="$(find "$install_dir" -maxdepth 1 -type d -name "zig-*" | head -n1)"
if [[ -z "$extracted_dir" ]]; then
	echo "Could not locate extracted zig directory under $install_dir" >&2
	exit 1
fi

echo "$extracted_dir" >>"$GITHUB_PATH"
"$extracted_dir/zig" version
