#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY="bats-core/bats-core"
readonly API_BASE_URL="https://api.github.com/repos/${REPOSITORY}/releases"
# Resolved rather than assumed: the action invokes this by absolute path from github.action_path,
# so the working directory is the consumer's workspace, not this directory. ~keep
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR

error() {
  echo "::error::$*" >&2
  exit 1
}

normalize_version() {
  local requested_version="$1"

  if [[ "$requested_version" == "latest" ]]; then
    printf '%s\n' "latest"
    return
  fi

  if [[ ! "$requested_version" =~ ^v?[0-9]+(\.[0-9]+){1,2}([-.][0-9A-Za-z][0-9A-Za-z.-]*)?$ ]]; then
    error "Invalid Bats version '${requested_version}'. Use 'latest' or a version such as '1.11.1' or 'v1.11.1'."
  fi

  printf 'v%s\n' "${requested_version#v}"
}

fetch_release_metadata() {
  local release_url="$1"
  local metadata_file="$2"
  local auth_args=()

  if [[ -n "${CURL_AUTH_HEADER:-}" ]]; then
    auth_args=(--header "$CURL_AUTH_HEADER")
  fi

  if ! curl \
    --proto '=https' \
    --tlsv1.2 \
    --fail \
    --silent \
    --show-error \
    --connect-timeout 10 \
    --max-time 30 \
    --header "Accept: application/vnd.github+json" \
    --header "X-GitHub-Api-Version: 2022-11-28" \
    ${auth_args[@]+"${auth_args[@]}"} \
    --output "$metadata_file" \
    "$release_url"; then
    error "Could not retrieve Bats release metadata from GitHub."
  fi
}

read_release_tag() {
  local metadata_file="$1"

  python3 - "$metadata_file" 2>/dev/null <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as metadata_file:
    metadata = json.load(metadata_file)

tag = metadata.get("tag_name")
if not isinstance(tag, str):
    raise ValueError("release metadata has no tag_name")

print(tag)
PY
}

# Sanity-checks the release metadata. Note this asserts the API's tarball_url, which is NOT the
# URL the archive is fetched from -- download_source_archive uses
# github.com/<repo>/archive/refs/tags/<tag>.tar.gz, whose bytes differ from the API tarball
# entirely. Download integrity comes from verify_archive_checksum, not from this. ~keep
release_has_source_archive() {
  local metadata_file="$1"
  local release_tag="$2"

  python3 - "$metadata_file" "$release_tag" 2>/dev/null <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as metadata_file:
    metadata = json.load(metadata_file)

assets = metadata.get("assets")
if not isinstance(assets, list):
    raise ValueError("release metadata has no assets list")

if metadata.get("tag_name") != sys.argv[2]:
    raise ValueError("release tag does not match")

tarball_url = metadata.get("tarball_url")
expected_url = f"https://api.github.com/repos/bats-core/bats-core/tarball/{sys.argv[2]}"
if tarball_url != expected_url:
    raise ValueError("release metadata has an unexpected source archive URL")
PY
}

validate_tag() {
  local tag="$1"

  [[ "$tag" =~ ^v[0-9]+(\.[0-9]+){1,2}([-.][0-9A-Za-z][0-9A-Za-z.-]*)?$ ]]
}

sha256_of_tar() {
  local archive="$1"

  # The digest covers the decompressed tar, not the archive as served. GitHub generates these
  # on demand and does not promise the compressed bytes are stable: its January 2023 gzip change
  # altered the checksum of every source archive on the platform with no repository content
  # changing. That moved the gzip framing only -- the tar payload comes from git objects and is
  # fixed by the tag -- so hashing after decompression survives a recompression while still
  # catching a tampered download or a moved tag. ~keep
  if command -v sha256sum >/dev/null 2>&1; then
    gzip -dc "$archive" | sha256sum | awk '{ print $1 }'
  elif command -v shasum >/dev/null 2>&1; then
    gzip -dc "$archive" | shasum -a 256 | awk '{ print $1 }'
  else
    error "Neither sha256sum nor shasum is available to verify the download."
  fi
}

pinned_checksum() {
  local version="$1"
  local table="${SCRIPT_DIR}/../checksums.tsv"

  awk -F '\t' -v want="$version" '
		/^[[:space:]]*#/ { next }
		NF < 2 { next }
		$1 == want { print $2; found = 1; exit }
		END { exit !found }
	' "$table"
}

verify_archive_checksum() {
  local archive="$1"
  local version="$2"
  local expected actual
  local table="${SCRIPT_DIR}/../checksums.tsv"

  # Checked here rather than inside pinned_checksum: `error` exits, but from within a command
  # substitution it only exits the subshell, so the caller would sail on into the unpinned
  # warning path and report success with no table at all. ~keep
  [[ -f "$table" ]] || error "Checksum table is missing: ${table}."

  if ! expected="$(pinned_checksum "$version")" || [[ -z "$expected" ]]; then
    # `latest` and any release newer than this table resolve here. The download still passes
    # the structural checks below, but it is not verified against a pinned digest, and a
    # silent skip would read exactly like a successful verification. ~keep
    echo "::warning::Bats ${version} is not in install-bats/checksums.tsv; the download was not checksum-verified. Pin a listed version for a reproducible install."
    return 0
  fi

  actual="$(sha256_of_tar "$archive")"
  if [[ "$actual" != "$expected" ]]; then
    error "Bats ${version} archive digest mismatch: expected ${expected}, got ${actual}."
  fi

  echo "Verified Bats ${version} against the pinned digest."
}

# Collapses "." and ".." components without touching the filesystem, so an archive entry can be
# resolved before anything is extracted. Fails when the path climbs above its own first
# component, which is what a traversal link does. ~keep
normalize_archive_path() {
  local remaining="$1"
  local normalized=""
  local component

  while [[ -n "$remaining" ]]; do
    component="${remaining%%/*}"
    if [[ "$remaining" == */* ]]; then
      remaining="${remaining#*/}"
    else
      remaining=""
    fi

    case "$component" in
    "" | .) ;;
    ..)
      [[ -n "$normalized" ]] || return 1
      if [[ "$normalized" == */* ]]; then
        normalized="${normalized%/*}"
      else
        normalized=""
      fi
      ;;
    *) normalized="${normalized:+${normalized}/}${component}" ;;
    esac
  done

  printf '%s\n' "$normalized"
}

# Splits the target off a `tar -tv` line by anchoring on the entry name, which the caller already
# read from `tar -t` and validated -- parsing the columns instead would have to straddle the
# different layouts GNU tar and bsdtar print. ~keep
read_link_target() {
  local verbose_entry="$1"
  local entry_name="$2"
  local entry_type="$3"
  local separator="${entry_name} -> "

  [[ "$entry_type" == "l" ]] || separator="${entry_name} link to "
  [[ "$verbose_entry" == *"$separator"* ]] || return 1

  printf '%s\n' "${verbose_entry#*"$separator"}"
}

# Symlink targets are relative to the entry's own directory; tar reports hard-link targets as
# archive-root-relative paths. ~keep
link_target_stays_in_root() {
  local entry_name="$1"
  local entry_type="$2"
  local link_target="$3"
  local expected_root="$4"
  local base=""
  local resolved

  [[ "$link_target" != /* ]] || return 1
  if [[ "$entry_type" == "l" && "$entry_name" == */* ]]; then
    base="${entry_name%/*}/"
  fi

  resolved="$(normalize_archive_path "${base}${link_target}")" || return 1
  [[ "$resolved" == "$expected_root" || "$resolved" == "$expected_root/"* ]]
}

# The threat is extraction-time path traversal, not the presence of a link: upstream bats-core
# tarballs legitimately ship ten in-tree symlinks under test/fixtures/, so rejecting links
# outright would reject every real release. Entry names come from `tar -t` and entry types and
# link targets from `tar -tv`, read in lockstep -- both list the same entries in the same
# order. ~keep
validate_archive() {
  local archive="$1"
  local expected_root="$2"
  local archive_entry verbose_entry entry_type link_target
  local found_bats=false

  while IFS= read -r archive_entry && IFS= read -r verbose_entry <&3; do
    archive_entry="${archive_entry#./}"
    [[ -n "$archive_entry" ]] || continue

    case "$archive_entry" in
    /* | ../* | */../* | */..)
      error "Downloaded Bats archive contains an unsafe path."
      ;;
    esac

    if [[ "$archive_entry" != "$expected_root" && "$archive_entry" != "$expected_root/"* ]]; then
      error "Downloaded Bats archive has an unexpected top-level path."
    fi

    entry_type="${verbose_entry:0:1}"
    case "$entry_type" in
    - | d) ;;
    l | h)
      link_target="$(read_link_target "$verbose_entry" "$archive_entry" "$entry_type")" ||
        error "Could not read the link target of '${archive_entry}' in the downloaded Bats archive."
      link_target_stays_in_root "$archive_entry" "$entry_type" "$link_target" "$expected_root" ||
        error "Downloaded Bats archive links outside itself: '${archive_entry}' -> '${link_target}'."
      ;;
    *)
      error "Downloaded Bats archive contains an unsupported special-file entry: '${archive_entry}'."
      ;;
    esac

    if [[ "$archive_entry" == "${expected_root}/bin/bats" ]]; then
      found_bats=true
    fi
  done < <(tar -tzf "$archive") 3< <(tar -tvzf "$archive")

  if [[ "$found_bats" != true ]]; then
    error "Downloaded Bats archive does not contain bin/bats."
  fi
}

download_source_archive() {
  local release_tag="$1"
  local archive="$2"

  if ! curl \
    --proto '=https' \
    --proto-redir '=https' \
    --tlsv1.2 \
    --fail \
    --silent \
    --show-error \
    --location \
    --connect-timeout 10 \
    --max-time 120 \
    --retry 3 \
    --retry-delay 2 \
    --output "$archive" \
    "https://github.com/${REPOSITORY}/archive/refs/tags/${release_tag}.tar.gz"; then
    error "Could not download the official Bats source archive for ${release_tag}."
  fi
}

requested_version="${INPUT_VERSION:-latest}"
install_dir="${INPUT_INSTALL_DIR:-}"
release_tag="$(normalize_version "$requested_version")"

case "$(uname -s)" in
Linux | Darwin) ;;
*) error "Unsupported operating system: $(uname -s). install-bats supports Linux and macOS only." ;;
esac

if ! command -v curl >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  error "install-bats requires curl, tar, and python3 on PATH."
fi

install_root="${install_dir:-${RUNNER_TEMP:-${HOME}/.local}/bats}"
mkdir -p "$install_root"

stage_dir="${install_root}/.install-bats-${RANDOM}-${RANDOM}"
if ! (umask 077 && mkdir "$stage_dir"); then
  error "Could not create a private staging directory in ${install_root}."
fi
trap 'rm -rf "$stage_dir"' EXIT

CURL_AUTH_HEADER=""
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  if [[ "$GITHUB_TOKEN" == *$'\r'* || "$GITHUB_TOKEN" == *$'\n'* ]]; then
    error "GITHUB_TOKEN must not contain carriage returns or newlines."
  fi
  CURL_AUTH_HEADER="Authorization: Bearer ${GITHUB_TOKEN}"
fi

metadata_file="${stage_dir}/release.json"
if [[ "$release_tag" == "latest" ]]; then
  fetch_release_metadata "${API_BASE_URL}/latest" "$metadata_file"
else
  fetch_release_metadata "${API_BASE_URL}/tags/${release_tag}" "$metadata_file"
fi

if ! resolved_tag="$(read_release_tag "$metadata_file")" || ! validate_tag "$resolved_tag"; then
  error "GitHub returned an invalid Bats release tag."
fi
if [[ "$release_tag" != "latest" && "$resolved_tag" != "$release_tag" ]]; then
  error "GitHub returned ${resolved_tag}, not the requested Bats release ${release_tag}."
fi

asset_version="${resolved_tag#v}"
asset_name="bats-core-${asset_version}.tar.gz"
if ! release_has_source_archive "$metadata_file" "$resolved_tag"; then
  error "Bats release ${resolved_tag} has invalid source archive metadata."
fi

release_dir="${install_root}/bats-core-${asset_version}"
bats_bin="${release_dir}/bin/bats"
if [[ -x "$bats_bin" ]]; then
  echo "Using existing Bats ${resolved_tag} at ${bats_bin}"
else
  archive="${stage_dir}/${asset_name}"
  download_source_archive "$resolved_tag" "$archive"
  verify_archive_checksum "$archive" "$asset_version"
  validate_archive "$archive" "bats-core-${asset_version}"

  if ! tar -xzf "$archive" -C "$stage_dir"; then
    error "Could not safely extract the downloaded Bats archive."
  fi

  extracted_dir="${stage_dir}/bats-core-${asset_version}"
  if [[ ! -x "${extracted_dir}/bin/bats" ]]; then
    error "Extracted Bats archive did not provide an executable bin/bats."
  fi
  if [[ -e "$release_dir" ]]; then
    error "Installation directory already exists but does not contain an executable Bats binary: ${release_dir}."
  fi
  mv "$extracted_dir" "$release_dir"
fi

if [[ ! -x "$bats_bin" ]]; then
  error "Bats binary is missing or not executable at ${bats_bin}."
fi

"$bats_bin" --version

if [[ -z "${GITHUB_PATH:-}" ]]; then
  error "GITHUB_PATH is not set; install-bats must run in a GitHub Actions job."
fi
printf '%s\n' "${release_dir}/bin" >>"$GITHUB_PATH"
