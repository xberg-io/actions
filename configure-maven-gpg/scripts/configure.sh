#!/usr/bin/env bash
set -euo pipefail

prefer_gpg2="${INPUT_PREFER_GPG2:-true}"
patch_pom="${INPUT_PATCH_POM:-true}"
pom_file="${INPUT_POM_FILE:-packages/java/pom.xml}"

if [[ "$prefer_gpg2" == "true" ]]; then
	if command -v gpg2 >/dev/null 2>&1; then
		mkdir -p "${HOME}/.local/bin"
		printf '#!/usr/bin/env bash\nexec gpg2 "$@"\n' >"${HOME}/.local/bin/gpg"
		chmod +x "${HOME}/.local/bin/gpg"
		echo "${HOME}/.local/bin" >>"$GITHUB_PATH"
		echo "PATH=${HOME}/.local/bin:${PATH}" >>"$GITHUB_ENV"
		echo "gpg2 binary preference configured"
	else
		echo "gpg2 not found; using default gpg"
	fi
fi

if [[ "$patch_pom" == "true" ]]; then
	if [[ ! -f "$pom_file" ]]; then
		echo "::warning::pom.xml not found: $pom_file (skipping patch)" >&2
	elif grep -q '<arg>--pinentry-mode</arg>' "$pom_file"; then
		sed -i 's/<arg>--pinentry-mode<\/arg>\s*<arg>loopback<\/arg>/<arg>--pinentry-mode=loopback<\/arg>/g' "$pom_file"
		echo "Patched legacy GPG pinentry argument format in $pom_file"
	else
		echo "No legacy GPG arguments found in $pom_file"
	fi
fi
