#!/usr/bin/env bats

# Every tool a composite installs through INSTALL_TOOLS_FALLBACK_ROOT must resolve, in this repository's own
# mise.toml, to one version that mise.lock locks on every lockfile_platforms entry; lock drift fails here instead
# of in a caller's job.

setup() {
	bats_load_library xberg-bats
	ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
	export ROOT
}

# The tool each fallback install step requests: the last argument of its install-tools.sh run, without a version.
fallback_tools() {
	local action
	for action in "$ROOT"/*/action.yml; do
		awk '
			/^    - / { if (fallback && tool != "") print tool; fallback = 0; tool = "" }
			/INSTALL_TOOLS_FALLBACK_ROOT:/ { fallback = 1 }
			/install-tools\.sh" / { tool = $NF; gsub(/"/, "", tool); sub(/=.*/, "", tool) }
			END { if (fallback && tool != "") print tool }
		' "$action"
	done
}

lock_platforms() {
	sed -n 's/^lockfile_platforms = \[\(.*\)\]$/\1/p' "$ROOT/mise.toml" | tr -d '" ' | tr ',' '\n'
}

@test "fallback_pins should_lock_every_composite_fallback_tool_on_every_platform" {
	[[ -n "$(command -v mise)" ]] || skip "mise is not on PATH"
	run fallback_tools
	xberg_assert_status 0
	requests=("${lines[@]}")
	((${#requests[@]} == 4)) || false
	tools=()
	while IFS= read -r tool; do
		tools+=("$tool")
	done < <(printf '%s\n' "${requests[@]}" | sort -u)
	[[ "${tools[*]}" == "github:taiki-e/cargo-llvm-cov helm uv" ]] || false
	platforms=()
	while IFS= read -r platform; do
		platforms+=("$platform")
	done < <(lock_platforms)
	((${#platforms[@]} >= 4)) || false

	current="$(cd "$ROOT" && env -u MISE_ENV MISE_OFFLINE=1 MISE_TRUSTED_CONFIG_PATHS="$ROOT" \
		MISE_CEILING_PATHS="$(dirname "$ROOT")" \
		MISE_DATA_DIR="$BATS_TEST_TMPDIR/data" MISE_CACHE_DIR="$BATS_TEST_TMPDIR/cache" \
		MISE_STATE_DIR="$BATS_TEST_TMPDIR/state" MISE_GLOBAL_CONFIG_FILE="$BATS_TEST_TMPDIR/global.toml" \
		mise current 2>/dev/null)"
	lock="$(tr -d '\r' <"$ROOT/mise.lock")"
	for tool in "${tools[@]}"; do
		read -r id version extra < <(awk -v tool="$tool" '$1 == tool' <<<"$current")
		[[ "$id" == "$tool" && -n "$version" && -z "${extra:-}" ]] || {
			echo "$tool resolves to '${version:-} ${extra:-}' in $ROOT/mise.toml, not one version" >&2
			return 1
		}
		header="[[tools.$tool]]"
		[[ "$tool" == *[:/]* ]] && header="[[tools.\"$tool\"]]"
		grep -A1 -Fx "$header" <<<"$lock" | grep -Fxq "version = \"$version\"" || {
			echo "mise.lock does not lock $tool@$version" >&2
			return 1
		}
		for platform in "${platforms[@]}"; do
			entry="[tools.$tool.\"platforms.$platform\"]"
			[[ "$tool" == *[:/]* ]] && entry="[tools.\"$tool\".\"platforms.$platform\"]"
			grep -Fxq "$entry" <<<"$lock" || {
				echo "mise.lock has no $platform entry for $tool" >&2
				return 1
			}
		done
	done
}
