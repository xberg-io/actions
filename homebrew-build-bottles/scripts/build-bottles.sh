#!/usr/bin/env bash
set -euo pipefail

# Build Homebrew bottles for one or more formulas on the current platform.
# Runs `brew install --build-bottle` (which uses the URL blocks in the
# already-published formula) followed by `brew bottle --json`. Renames bottle
# artifacts to single-dash convention and uploads them to the GitHub release.
# Saves bottle JSON manifests to OUT_DIR for the merge step to aggregate.
#
# Required env:
#   TAG, VERSION, TAP, FORMULAS (newline-separated), OUT_DIR, GITHUB_REPO, GH_TOKEN

tag="${TAG:?TAG is required}"
version="${VERSION:?VERSION is required}"
tap="${TAP:?TAP is required (e.g. kreuzberg-dev/tap)}"
formulas_raw="${FORMULAS:?FORMULAS is required (newline-separated list)}"
out_dir="${OUT_DIR:?OUT_DIR is required}"
github_repo="${GITHUB_REPO:?GITHUB_REPO is required (e.g. kreuzberg-dev/foo)}"

mkdir -p "$out_dir"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cd "$work_dir"

echo "::group::brew env"
brew --version
brew config | head -20 || true
echo "::endgroup::"

echo "::group::Tap ${tap}"
brew tap "$tap"
brew update --quiet || true
echo "::endgroup::"

build_one_bottle() {
  local formula="$1"
  echo "::group::Building bottle for ${formula}"

  brew uninstall --force "${tap}/${formula}" 2>/dev/null || true

  brew install --build-bottle --verbose "${tap}/${formula}"

  brew bottle --json --no-rebuild "${tap}/${formula}"

  local original_tarball
  shopt -s nullglob
  local tarballs=("${formula}--${version}".*.bottle.tar.gz)
  shopt -u nullglob
  if [[ ${#tarballs[@]} -eq 0 ]]; then
    echo "ERROR: no bottle tarball produced for ${formula}" >&2
    ls -la
    return 1
  fi
  original_tarball="${tarballs[0]}"

  local renamed_tarball="${original_tarball/--/-}"
  if [[ "$renamed_tarball" != "$original_tarball" ]]; then
    cp "$original_tarball" "$renamed_tarball"
  fi

  shopt -s nullglob
  local json_files=("${formula}--${version}".*.bottle.json)
  shopt -u nullglob
  for jf in "${json_files[@]}"; do
    cp "$jf" "$out_dir/"
  done

  echo "Uploading ${renamed_tarball} to release ${tag}"
  gh release upload "$tag" "$renamed_tarball" --clobber --repo "$github_repo" </dev/null

  echo "::endgroup::"
}

# Iterate the newline-separated formula list. Read from FD 3 so that commands
# inside the loop body (notably `gh`) cannot consume the loop's stdin and end
# iteration early — observed on macOS bash 3.2 where `gh release upload`
# absorbed the remaining lines.
while IFS= read -r formula <&3; do
  formula="${formula// /}"
  [[ -z "$formula" ]] && continue
  build_one_bottle "$formula"
done 3<<<"$formulas_raw"

echo "Bottles built; JSON manifests saved to ${out_dir}:"
ls -la "$out_dir"
