#!/usr/bin/env python3
"""Publish npm packages from a directory or a .tgz file.

Usage (GitHub Actions via env vars):
    INPUT_PACKAGE_DIR=dist/ python3 publish.py
    INPUT_PACKAGES_DIR=dist/packages/ python3 publish.py
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ALREADY_PUBLISHED_PATTERN = re.compile(
    r"previously published|cannot publish over|already exists",
    re.IGNORECASE,
)

# npm publish --provenance produces a Sigstore transparency-log entry by
# calling https://rekor.sigstore.dev which is occasionally unavailable. The
# error surface from npm is `TLOG_CREATE_ENTRY_ERROR` / `error creating tlog
# entry`. We also retry on plain network noise to absorb other transient
# failures from the registry endpoint.
TRANSIENT_PUBLISH_PATTERN = re.compile(
    r"TLOG_CREATE_ENTRY_ERROR|error creating tlog entry|ETIMEDOUT|ECONNRESET|"
    r"ECONNREFUSED|EAI_AGAIN|socket hang up|aborted|fetch failed|5\d\d ",
    re.IGNORECASE,
)
MAX_PUBLISH_RETRIES = 4
PUBLISH_RETRY_BACKOFF_SECONDS = 5

# `actions/setup-node@v6` exports NODE_AUTH_TOKEN as this 23-char placeholder
# (hardcoded in setup-node's authutil.ts) when no real token is provided.
SETUP_NODE_PLACEHOLDER = "XXXXX-XXXXX-XXXXX-XXXXX"


def validate_inputs(packages_dir: str, package_dir: str) -> str:
    """Validate mutually exclusive inputs; return mode 'tgz' or 'dir'.

    Raises SystemExit on invalid combinations.
    """
    if packages_dir and package_dir:
        print("Error: packages-dir and package-dir are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if not packages_dir and not package_dir:
        print("Error: either packages-dir or package-dir must be provided", file=sys.stderr)
        sys.exit(1)
    return "tgz" if packages_dir else "dir"


def build_publish_flags(access: str, npm_tag: str, provenance: bool, dry_run: bool) -> list[str]:
    """Build the list of flags to pass to `npm publish`.

    Note: --force bypasses npm's pre-publish validation for new scoped packages.
    This is required for platform-specific subpackages (e.g. @kreuzberg/node-linux-arm64-musl)
    on their first publish, as npm CLI cannot validate the package exists before creation.
    """
    flags: list[str] = ["--access", access, "--tag", npm_tag, "--ignore-scripts", "--force"]
    if provenance:
        flags.append("--provenance")
    if dry_run:
        flags.append("--dry-run")
    return flags


def is_already_published(output: str) -> bool:
    """Return True if the npm output indicates the package was already published."""
    return bool(ALREADY_PUBLISHED_PATTERN.search(output))


def find_tgz_files(directory: Path) -> list[Path]:
    """Return all *.tgz files in directory (non-recursive) and subdirectories."""
    return sorted(directory.glob("**/*.tgz"))


def has_native_binding(tgz_path: Path) -> bool:
    """Check if a .tgz tarball contains a .node native binding file.

    Returns False for stub packages (placeholders without prebuilt binaries),
    which should be skipped during publishing to avoid npm Sigstore validation
    failures on empty payloads.
    """
    import tarfile

    try:
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".node"):
                    return True
    except Exception:
        pass
    return False


def is_platform_package(tgz_path: Path) -> bool:
    """Check whether a .tgz is a per-platform binding package.

    napi-rs platform sub-packages (e.g. `@scope/pkg-linux-x64-gnu`) pin `os`
    and/or `cpu` in their package.json; the pure-JS umbrella package (the one
    consumers install, whose binaries resolve via `optionalDependencies`) sets
    neither. Only platform packages may be skipped as empty stubs — the umbrella
    package has no `.node` of its own and must still publish.
    """
    import tarfile

    try:
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("package.json") and member.name.count("/") == 1:
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    pkg = json.loads(extracted.read().decode("utf-8"))
                    return bool(pkg.get("os") or pkg.get("cpu"))
    except Exception:
        pass
    return False


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
    return result.returncode, result.stdout + result.stderr


def _run_publish_with_retry(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Run an `npm publish` command, retrying on Sigstore Rekor / transient network errors.

    Returns the final `(exit_code, output)` of the last attempt.
    Non-transient failures (auth, schema, already-published, etc.) return immediately.
    """
    last_output = ""
    for attempt in range(1, MAX_PUBLISH_RETRIES + 1):
        exit_code, output = _run(cmd, cwd=cwd)
        last_output = output
        if exit_code == 0:
            return exit_code, output
        if is_already_published(output):
            return exit_code, output
        if not TRANSIENT_PUBLISH_PATTERN.search(output):
            return exit_code, output
        if attempt == MAX_PUBLISH_RETRIES:
            break
        delay = PUBLISH_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
        print(
            f"  Transient npm publish error (attempt {attempt}/{MAX_PUBLISH_RETRIES}); retrying in {delay}s",
            file=sys.stderr,
        )
        time.sleep(delay)
    return 1, last_output


def _strip_empty_npm_auth_token() -> None:
    """Strip empty NODE_AUTH_TOKEN env + _authToken lines in .npmrc.

    When a caller writes `NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}` and the
    secret is undefined, the env var is set to "" and `setup-node` writes a
    `//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}` line into .npmrc.
    npm CLI then sees an empty token and skips OIDC trusted publishing, even
    though npm@11+ would otherwise exchange the GHA OIDC token for a
    short-lived credential automatically. Strip both so OIDC can take over.

    Note: `setup-node` writes the literal placeholder string
    `_authToken=${NODE_AUTH_TOKEN}` to .npmrc and relies on npm CLI to expand
    the env var at read time. When NODE_AUTH_TOKEN is empty/unset, that
    expansion produces an empty token but the line itself is non-empty —
    so we must strip lines matching the placeholder form too, not just the
    post-expansion `_authToken=` form.
    """
    token = os.environ.get("NODE_AUTH_TOKEN", "")
    # `actions/setup-node@v6` exports NODE_AUTH_TOKEN='XXXXX-XXXXX-XXXXX-XXXXX'
    # (the 23-char placeholder string, hardcoded in setup-node's authutil.ts)
    # when the caller hasn't provided a real token, so that npm CLI doesn't
    # complain about a missing token at .npmrc read time. But the placeholder
    # gets sent to the registry as the actual auth credential — yielding
    # `404 Not Found` and shadowing OIDC trusted publishing. Treat the
    # placeholder the same as empty so OIDC can take over.
    if token.strip() and token.strip() != SETUP_NODE_PLACEHOLDER:
        print(f"NODE_AUTH_TOKEN is set ({len(token)} chars); skipping OIDC fallback strip")
        return

    if token.strip() == SETUP_NODE_PLACEHOLDER:
        print("NODE_AUTH_TOKEN is set to setup-node@v6's placeholder; treating as unset for OIDC")
    os.environ.pop("NODE_AUTH_TOKEN", None)

    # Walk candidate .npmrc paths: NPM_CONFIG_USERCONFIG (set by setup-node),
    # $HOME/.npmrc, and the project-local .npmrc (cwd or near package.json).
    candidates: list[Path] = []
    if cfg := os.environ.get("NPM_CONFIG_USERCONFIG"):
        candidates.append(Path(cfg))
    candidates.extend([Path.home() / ".npmrc", Path.cwd() / ".npmrc"])

    # Strip every line declaring an _authToken when NODE_AUTH_TOKEN is empty.
    # Either the value is literally empty (`=` then EOL), references the now-
    # unset NODE_AUTH_TOKEN placeholder (`=${NODE_AUTH_TOKEN}`), or any other
    # value — we're committing to OIDC trusted publishing in this script when
    # the env var is unset, so any leftover _authToken line would shadow OIDC.
    strip_pattern = re.compile(r"^\s*//[^:]+:_authToken\s*=")

    seen: set[Path] = set()
    for raw in candidates:
        try:
            npmrc_path = raw.resolve()
        except OSError:
            continue
        if npmrc_path in seen:
            continue
        seen.add(npmrc_path)
        if not npmrc_path.is_file():
            continue

        original = npmrc_path.read_text()
        cleaned = "".join(line for line in original.splitlines(keepends=True) if not strip_pattern.match(line))
        if cleaned != original:
            npmrc_path.write_text(cleaned)
            print(f"Stripped _authToken lines from {npmrc_path}; npm will use OIDC trusted publishing")
        else:
            # Helps diagnose silent failures — log what we saw so future logs show
            # whether the .npmrc layout drifted vs whether the file was already clean.
            print(f"No _authToken line found in {npmrc_path} (file present, no strip needed)")


def main() -> None:
    packages_dir = os.environ.get("INPUT_PACKAGES_DIR", "")
    package_dir = os.environ.get("INPUT_PACKAGE_DIR", "")
    npm_tag = os.environ.get("INPUT_NPM_TAG", "latest")
    access = os.environ.get("INPUT_ACCESS", "public")
    provenance = os.environ.get("INPUT_PROVENANCE", "true").lower() == "true"
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"

    _strip_empty_npm_auth_token()

    mode = validate_inputs(packages_dir, package_dir)
    flags = build_publish_flags(access, npm_tag, provenance, dry_run)

    if mode == "dir":
        pkg_path = Path(package_dir)
        if not pkg_path.is_dir():
            print(f"Error: package directory not found: {package_dir}", file=sys.stderr)
            sys.exit(1)

        print(f"Publishing from directory: {package_dir}")
        exit_code, output = _run_publish_with_retry(["npm", "publish", ".", *flags], cwd=pkg_path)

        if exit_code == 0:
            print("Published successfully")
        elif is_already_published(output):
            print("Package already published, skipping")
        else:
            print("Error publishing:", file=sys.stderr)
            print(output, file=sys.stderr)
            sys.exit(1)
        return

    pkgs_path = Path(packages_dir)
    if not pkgs_path.is_dir():
        print(f"Error: packages directory not found: {packages_dir}", file=sys.stderr)
        sys.exit(1)

    tgz_files = find_tgz_files(pkgs_path)
    if not tgz_files:
        print(f"Error: no .tgz files found in {packages_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Publishing {len(tgz_files)} package(s) with tag '{npm_tag}'...")

    failed = 0
    published = 0
    skipped = 0

    for tgz in tgz_files:
        name = tgz.name

        # Skip per-platform stub packages (os/cpu pinned bindings without a
        # prebuilt .node file) — placeholders created during bootstrap for musl
        # variants and similar; publishing them triggers npm Sigstore validation
        # failures on empty payloads. The pure-JS umbrella package also has no
        # .node of its own but is NOT a stub: consumers install it and resolve
        # binaries via its optionalDependencies, so it must still publish.
        if is_platform_package(tgz) and not has_native_binding(tgz):
            print(f"  Skipping {name} (platform stub with no .node binding)")
            skipped += 1
            continue

        print(f"Publishing {name}...")
        exit_code, output = _run_publish_with_retry(["npm", "publish", str(tgz.resolve()), *flags])

        if exit_code == 0:
            print(f"  Published {name}")
            published += 1
        elif is_already_published(output):
            print(f"  {name} already published, skipping")
            published += 1
        else:
            print(f"  Error publishing {name}:", file=sys.stderr)
            print(output, file=sys.stderr)
            failed += 1

    print(f"Published: {published}, Failed: {failed}, Skipped: {skipped}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
