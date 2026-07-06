#!/usr/bin/env bash
set -euo pipefail

image="${INPUT_IMAGE:?INPUT_IMAGE is required}"
warn_mb="${INPUT_WARN_MB:-}"
fail_mb="${INPUT_FAIL_MB:-}"
label="${INPUT_LABEL:-$image}"

if ! docker inspect "$image" >/dev/null 2>&1; then
	echo "::error::image not found locally: $image" >&2
	exit 1
fi

size_bytes=$(docker inspect "$image" --format='{{.Size}}')
size_mb=$((size_bytes / 1024 / 1024))

echo "Image: $image"
echo "Size:  ${size_mb}MB"
echo "size-mb=${size_mb}" >>"$GITHUB_OUTPUT"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
	printf -- '- **%s**: %sMB\n' "$label" "$size_mb" >>"$GITHUB_STEP_SUMMARY"
fi

if [[ -n "$fail_mb" ]] && ((size_mb > fail_mb)); then
	echo "::error::$label exceeds fail threshold (${size_mb}MB > ${fail_mb}MB)" >&2
	exit 1
fi

if [[ -n "$warn_mb" ]] && ((size_mb > warn_mb)); then
	echo "::warning::$label is larger than ${warn_mb}MB (${size_mb}MB)"
fi
