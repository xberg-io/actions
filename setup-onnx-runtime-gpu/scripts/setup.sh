#!/usr/bin/env bash
set -euo pipefail

version="${INPUT_VERSION:?INPUT_VERSION is required}"
platform="${INPUT_PLATFORM:-linux-x64-gpu}"

ort_dir="${RUNNER_TEMP:-/tmp}/onnxruntime"
ort_name="onnxruntime-${platform}-${version}"
archive="${ort_name}.tgz"

if [[ ! -d "$ort_dir/$ort_name" ]]; then
	echo "Downloading ONNX Runtime ${version} (${platform})"
	curl -fsSL --retry 3 --retry-delay 5 \
		-o "${RUNNER_TEMP:-/tmp}/$archive" \
		"https://github.com/microsoft/onnxruntime/releases/download/v${version}/$archive"
	mkdir -p "$ort_dir"
	tar -xzf "${RUNNER_TEMP:-/tmp}/$archive" -C "$ort_dir"
	rm -f "${RUNNER_TEMP:-/tmp}/$archive"
else
	echo "Reusing cached ONNX Runtime at $ort_dir/$ort_name"
fi

ort_lib="$ort_dir/$ort_name/lib"
echo "ORT_DYLIB_PATH=${ort_lib}/libonnxruntime.so" >>"$GITHUB_ENV"
echo "LD_LIBRARY_PATH=${ort_lib}:${LD_LIBRARY_PATH:-}" >>"$GITHUB_ENV"
echo "lib-dir=${ort_lib}" >>"$GITHUB_OUTPUT"

echo "ONNX Runtime GPU libraries staged at ${ort_lib}"
ls -la "${ort_lib}"/libonnxruntime*.so*
