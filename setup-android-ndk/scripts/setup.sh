#!/usr/bin/env bash
#   INPUT_NDK_VERSION         Explicit NDK directory name under $ANDROID_HOME/ndk/
#   INPUT_CARGO_NDK_VERSION   Specific cargo-ndk version (empty = latest)
set -euo pipefail

NDK_VERSION="${INPUT_NDK_VERSION:-}"
TARGETS="${INPUT_TARGETS:-aarch64-linux-android,x86_64-linux-android}"
INSTALL_CARGO_NDK="${INPUT_INSTALL_CARGO_NDK:-true}"
CARGO_NDK_VERSION="${INPUT_CARGO_NDK_VERSION:-}"

resolve_ndk_home() {
	if [[ -n "${NDK_VERSION}" && -n "${ANDROID_HOME:-}" ]]; then
		if [[ -d "${ANDROID_HOME}/ndk/${NDK_VERSION}" ]]; then
			echo "${ANDROID_HOME}/ndk/${NDK_VERSION}"
			return 0
		fi
		echo "Error: ANDROID_HOME/ndk/${NDK_VERSION} not found" >&2
		exit 1
	fi

	if [[ -n "${ANDROID_HOME:-}" && -d "${ANDROID_HOME}/ndk" ]]; then
		local picked
		picked="$(find "${ANDROID_HOME}/ndk" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -V | tail -n1 || true)"
		if [[ -n "${picked}" && -d "${ANDROID_HOME}/ndk/${picked}" ]]; then
			echo "${ANDROID_HOME}/ndk/${picked}"
			return 0
		fi
	fi

	for var in ANDROID_NDK_HOME ANDROID_NDK_ROOT NDK_HOME; do
		local val="${!var:-}"
		if [[ -n "${val}" && -d "${val}" ]]; then
			echo "${val}"
			return 0
		fi
	done

	if [[ "$(uname -s)" == "Darwin" ]]; then
		if [[ -d /opt/homebrew/share/android-ndk ]]; then
			local resolved
			resolved="$(readlink -f /opt/homebrew/share/android-ndk 2>/dev/null || true)"
			if [[ -n "${resolved}" && -d "${resolved}" ]]; then
				echo "${resolved}"
				return 0
			fi
			echo "/opt/homebrew/share/android-ndk"
			return 0
		fi
		if [[ -d /opt/homebrew/Caskroom/android-ndk ]]; then
			local candidate
			candidate="$(find /opt/homebrew/Caskroom/android-ndk -maxdepth 4 -type d -name NDK 2>/dev/null | head -n1 || true)"
			if [[ -n "${candidate}" && -d "${candidate}" ]]; then
				echo "${candidate}"
				return 0
			fi
		fi
	fi

	echo "Error: no Android NDK found. Set ANDROID_HOME or install one." >&2
	exit 1
}

ndk_home="$(resolve_ndk_home)"
echo "Resolved ANDROID_NDK_HOME=${ndk_home}"

resolve_host_toolchain() {
	local base="${ndk_home}/toolchains/llvm/prebuilt"
	if [[ ! -d "${base}" ]]; then
		echo "Error: NDK toolchain dir not found at ${base}" >&2
		exit 1
	fi
	local kernel
	kernel="$(uname -s)"
	local arch
	arch="$(uname -m)"
	local -a candidates=()
	if [[ "${kernel}" == "Darwin" ]]; then
		if [[ "${arch}" == "arm64" || "${arch}" == "aarch64" ]]; then
			candidates=("darwin-aarch64" "darwin-arm64" "darwin-x86_64")
		else
			candidates=("darwin-x86_64")
		fi
	else
		if [[ "${arch}" == "aarch64" ]]; then
			candidates=("linux-aarch64" "linux-x86_64")
		else
			candidates=("linux-x86_64")
		fi
	fi
	for c in "${candidates[@]}"; do
		if [[ -d "${base}/${c}/bin" ]]; then
			echo "${base}/${c}/bin"
			return 0
		fi
	done
	echo "Error: no prebuilt host toolchain under ${base} (tried: ${candidates[*]})" >&2
	exit 1
}

host_bin="$(resolve_host_toolchain)"
echo "NDK host toolchain bin: ${host_bin}"

if [[ -n "${GITHUB_ENV:-}" ]]; then
	{
		echo "ANDROID_NDK_HOME=${ndk_home}"
		echo "ANDROID_NDK_ROOT=${ndk_home}"
		echo "NDK_HOME=${ndk_home}"
	} >>"${GITHUB_ENV}"
fi

if [[ -n "${GITHUB_PATH:-}" ]]; then
	echo "${host_bin}" >>"${GITHUB_PATH}"
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	echo "ndk-home=${ndk_home}" >>"${GITHUB_OUTPUT}"
fi

IFS=',' read -r -a target_list <<<"${TARGETS}"
for t in "${target_list[@]}"; do
	t="$(echo "${t}" | tr -d ' ')"
	if [[ -z "${t}" ]]; then
		continue
	fi
	echo "Adding rustup target ${t}"
	rustup target add "${t}"
done

if [[ "${INSTALL_CARGO_NDK}" == "true" ]]; then
	if command -v cargo-ndk >/dev/null 2>&1; then
		echo "cargo-ndk already installed"
	else
		if [[ -n "${CARGO_NDK_VERSION}" ]]; then
			cargo install cargo-ndk --locked --version "${CARGO_NDK_VERSION}"
		else
			cargo install cargo-ndk --locked
		fi
	fi
fi

echo "setup-android-ndk done"
