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
# Temporarily disable pipefail for diagnostic commands that may produce broken pipes
# on some runners (especially arm64 Linux) due to output buffering issues
set +o pipefail
brew --version
brew config | head -20 || true
set -o pipefail
echo "::endgroup::"

echo "::group::Tap ${tap}"
# Force git-tap installs so the formula is read from the just-tapped
# clone instead of the JSON API (avoids stale API metadata on first
# bottle build).
export HOMEBREW_NO_INSTALL_FROM_API=1
# Bring Homebrew itself up to date BEFORE tap/trust so older runner images
# (e.g. macos-14 arm64_sequoia ships Homebrew 5.1.14) self-upgrade to 6.x,
# which is required for the `brew trust` command. `brew update` updates the
# Homebrew Library source tree it bootstraps from; the next `brew` invocation
# uses the upgraded code.
brew update --quiet || true
# GitHub-hosted Linux runners block unprivileged user namespaces, so even
# though bubblewrap is installed it cannot create a rootless sandbox
# ("Bubblewrap is installed but cannot create a rootless sandbox"). The
# documented workaround in that error is to disable Homebrew's Linux sandbox
# entirely. Set on every shell — no-op on macOS.
export HOMEBREW_NO_SANDBOX_LINUX=1
brew tap "$tap"
# Recent Homebrew refuses to load formulae from non-core taps when
# HOMEBREW_REQUIRE_TAP_TRUST is set ("Refusing to load formula <…> from
# untrusted tap"). GitHub-hosted runners export the var in /etc/environment
# and Homebrew's EnvConfigBool treats *any* value (including empty) as
# "set", so unsetting or overriding to "" in this shell does not silence
# the check inside the brew Ruby process. Use the explicit `brew trust`
# command (available since Homebrew 6.x); the warning message itself
# instructs callers to use it. Falls back to a no-op on very old brews
# that lack both the command and the check.
brew trust "$tap" || echo "warning: brew trust unavailable; relying on env-var bypass"
echo "::endgroup::"

# Strip every `bottle do … end` block from the freshly tapped formula before
# building. A pre-existing formula can carry stale bottle blocks left OUTSIDE
# its `class … end` body (historical GoReleaser output, or older merges that
# appended at end-of-file); Homebrew then fails to even load the formula with
# `undefined method 'bottle' for module Formulary::FormulaNamespace`, which
# deadlocks `brew install --build-bottle` before a fresh bottle can be built.
# Building a bottle needs no bottle block, so drop them all here — this edits
# only the local tap clone; homebrew-merge-bottles re-adds one block inside the
# class afterwards. No-op when the formula has no bottle blocks.
normalize_tapped_formula() {
  local formula="$1"
  local repo formula_file
  repo="$(brew --repository "$tap" 2>/dev/null)" || return 0
  for formula_file in "${repo}/Formula/${formula}.rb" "${repo}/${formula}.rb"; do
    [[ -f "$formula_file" ]] || continue
    python3 - "$formula_file" <<'PYEOF'
import re
import sys

path = sys.argv[1]
with open(path) as fh:
    content = fh.read()

bottle_re = re.compile(r"^[ \t]*bottle do\b.*?^[ \t]*end(?:\n|\Z)", re.MULTILINE | re.DOTALL)
stripped = bottle_re.sub("", content)
stripped = re.sub(r"\n{3,}", "\n\n", stripped)

if stripped != content:
    with open(path, "w") as fh:
        fh.write(stripped)
    sys.stderr.write(f"normalize_tapped_formula: stripped stale bottle block(s) from {path}\n")
PYEOF
    return 0
  done
}

build_one_bottle() {
  local formula="$1"
  echo "::group::Building bottle for ${formula}"

  brew uninstall --force "${tap}/${formula}" 2>/dev/null || true

  normalize_tapped_formula "$formula"

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
