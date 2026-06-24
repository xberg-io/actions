#!/usr/bin/env bash
set -euo pipefail

# Merge bottle JSON manifests from all platform builds into the formula files
# inside the homebrew-tap checkout. Parses the JSONs directly with jq and
# rewrites each formula's `bottle do` block, avoiding a brew dependency on the
# merge runner.
#
# Required env:
#   TAG, VERSION, TAP_DIR, JSON_DIR, FORMULAS (newline-separated), GITHUB_REPO

tag="${TAG:?TAG is required}"
version="${VERSION:?VERSION is required}"
tap_dir="${TAP_DIR:?TAP_DIR is required}"
json_dir="${JSON_DIR:?JSON_DIR is required}"
formulas_raw="${FORMULAS:?FORMULAS is required (newline-separated list)}"
github_repo="${GITHUB_REPO:?GITHUB_REPO is required}"

[[ -d "$tap_dir" ]] || {
  echo "Tap directory not found: $tap_dir" >&2
  exit 1
}
[[ -d "$json_dir" ]] || {
  echo "JSON dir not found: $json_dir" >&2
  exit 1
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

root_url="https://github.com/${github_repo}/releases/download/${tag}"

# render_bottle_block <formula-name> writes the `bottle do ... end` lines to stdout.
render_bottle_block() {
  local formula_name="$1"
  local jsons=("$json_dir"/"$formula_name"--"$version".*.bottle.json)

  if [[ ! -e "${jsons[0]}" ]]; then
    echo "ERROR: no JSON manifests for ${formula_name} in $json_dir" >&2
    return 1
  fi

  printf '  bottle do\n'
  printf '    root_url "%s"\n' "$root_url"

  for jf in "${jsons[@]}"; do
    local tag_key sha cellar formatted_cellar
    # brew bottle --json keys the top-level object by the fully-qualified
    # tap formula name (e.g. "xberg-io/tap/ts-pack"), not the bare
    # formula name. There's exactly one key per file, so dereference via keys[0].
    tag_key=$(jq -r '.[keys[0]].bottle.tags | keys[0]' "$jf")
    sha=$(jq -r --arg tag "$tag_key" '.[keys[0]].bottle.tags[$tag].sha256' "$jf")
    cellar=$(jq -r --arg tag "$tag_key" '.[keys[0]].bottle.tags[$tag].cellar // .[keys[0]].bottle.cellar' "$jf")

    # brew bottle JSON stores symbol cellar values as plain strings ("any",
    # "any_skip_relocation"); literal Cellar paths start with "/". Emit the
    # former as Ruby symbols (:any) and the latter as quoted strings.
    case "$cellar" in
    any | any_skip_relocation) formatted_cellar=":$cellar" ;;
    :*) formatted_cellar="$cellar" ;;
    *) formatted_cellar="\"$cellar\"" ;;
    esac

    printf '    sha256 cellar: %s, %s: "%s"\n' "$formatted_cellar" "$tag_key" "$sha"
  done

  printf '  end\n'
}

# replace_or_insert_bottle_block <formula-file> <bottle-block-content>
# Replaces an existing `bottle do ... end` block, or inserts after the
# `license` line if no bottle block exists.
replace_or_insert_bottle_block() {
  local file="$1"
  local block_content="$2"

  python3 - "$file" "$block_content" <<'PYEOF'
import re
import sys

path, block = sys.argv[1], sys.argv[2]

with open(path) as fh:
    content = fh.read()

# Strip EVERY existing `bottle do ... end` block from the file. Older
# formulas (especially ones bootstrapped by GoReleaser) sometimes accreted
# multiple bottle blocks at file-level scope — *outside* the `class … end`
# — which causes `brew bottle` to fail with
# `undefined method 'bottle' for module Formulary::FormulaNamespace…`.
# Removing all matches and re-inserting one fresh block inside the class
# fixes both the duplicate-block and the wrong-scope cases.
bottle_re = re.compile(r"^[ \t]*bottle do\b.*?^[ \t]*end(?:\n|\Z)", re.MULTILINE | re.DOTALL)
stripped = bottle_re.sub("", content)

# Insert the fresh block immediately after the `license` line so it lands
# inside the `class < Formula` body (license is a Formula DSL call, so it
# must be inside the class).
license_re = re.compile(r"^([ \t]*license [^\n]*\n)", re.MULTILINE)
m = license_re.search(stripped)
if not m:
    sys.stderr.write(f"ERROR: cannot find license line in {path}\n")
    sys.exit(1)
insert_at = m.end()
new_content = stripped[:insert_at] + "\n" + block + "\n" + stripped[insert_at:]

# Collapse any triple+ blank lines created by stripping outside-class blocks.
new_content = re.sub(r"\n{3,}", "\n\n", new_content)

with open(path, "w") as fh:
    fh.write(new_content)
PYEOF
}

while IFS= read -r formula; do
  formula="${formula// /}"
  [[ -z "$formula" ]] && continue
  block="$(render_bottle_block "$formula")"
  replace_or_insert_bottle_block "${tap_dir}/Formula/${formula}.rb" "$block"
done <<<"$formulas_raw"

cd "$tap_dir"
echo "Merged formulas:"
git diff --stat Formula/
