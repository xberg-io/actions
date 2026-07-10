#!/usr/bin/env bash
set -euo pipefail

label="${1:?label required}"
enable_cache="${2:?enable-cache required (true/false)}"
cache_dir_prefix="${3:?cache-dir-prefix required}"

if [ "$enable_cache" = "true" ]; then
	case "$cache_dir_prefix" in
	/*) cache_dir="${cache_dir_prefix}/${label}" ;;
	*) cache_dir="${GITHUB_WORKSPACE}/${cache_dir_prefix}/${label}" ;;
	esac

	echo "TESSERACT_RS_CACHE_DIR=${cache_dir}" >>"$GITHUB_ENV"
	echo "XDG_CACHE_HOME=${GITHUB_WORKSPACE}/.xdg-cache/${label}" >>"$GITHUB_ENV"

	echo "cache-dir=${cache_dir}" >>"$GITHUB_OUTPUT"
	echo "cache-enabled=true" >>"$GITHUB_OUTPUT"

	docker_opts="--env TESSERACT_RS_CACHE_DIR=/io/${cache_dir_prefix}/${label}"
	docker_opts="${docker_opts} --env XDG_CACHE_HOME=/io/.xdg-cache/${label}"
	echo "docker-options=${docker_opts}" >>"$GITHUB_OUTPUT"
else
	{
		echo "TESSERACT_RS_CACHE_DIR="
	} >>"$GITHUB_ENV"
	{
		echo "cache-dir="
		echo "cache-enabled=false"
		echo "docker-options="
	} >>"$GITHUB_OUTPUT"
fi
