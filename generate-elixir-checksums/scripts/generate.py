#!/usr/bin/env python3
"""Generate RustlerPrecompiled checksum files for Elixir NIF binaries.

Usage (GitHub Actions via env vars):
    INPUT_GITHUB_REPO=org/repo \
    INPUT_TAG=v1.2.3 \
    INPUT_VERSION=1.2.3 \
    INPUT_LIB_NAME=mylib \
    INPUT_NIF_VERSIONS=2.16,2.17 \
    INPUT_TARGETS=x86_64-unknown-linux-gnu,aarch64-unknown-linux-gnu \
    INPUT_OUTPUT_PATH=checksum-mylib.exs \
    GH_TOKEN=ghs_... \
    python3 generate.py
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def build_nif_artifact_name(lib_name: str, version: str, nif_version: str, target: str) -> str:
    """Return the NIF artifact filename for a given target triple.

    Use `.dll` on windows and `.so` everywhere else (including macOS).
    `rustler_precompiled 0.9.0`'s `lib_name_with_ext/2` (the latest version on
    Hex; no `.dylib` support exists) hardcodes `.so` for every non-Windows
    consumer download URL and cannot be overridden. Publishing `.dylib` for
    darwin causes Hex publish to fail on checksum vs. asset mismatch and
    404s every downstream `mix deps.get` on macOS.
    """
    ext = "dll.tar.gz" if "windows" in target else "so.tar.gz"
    return f"lib{lib_name}-v{version}-nif-{nif_version}-{target}.{ext}"


def compute_sha256_hex(data: bytes) -> str:
    """Return the SHA256 hex digest of data."""
    return hashlib.sha256(data).hexdigest()


def download_asset_via_gh(github_repo: str, tag: str, filename: str, dest_dir: Path) -> Path:
    """Download a release asset via authenticated `gh release download`.

    Using `gh release download` instead of the public
    `releases/download/<tag>/<name>` CDN URL means this works against draft
    releases (where the public CDN returns 404 because the tag is not yet
    published). The publish workflow keeps the release in draft until the
    final `release-finalize` step, so every prior consumer (this action,
    publish-hex, etc.) sees a draft release.

    Retries on transient failures with exponential-ish backoff: the gh API
    can briefly 502 during release fan-out, and a freshly uploaded asset
    can momentarily 404 even via the authenticated API.
    """
    dest = dest_dir / filename
    max_attempts = 20
    sleep_seconds = 10
    last_stderr = ""
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            [
                "gh",
                "release",
                "download",
                tag,
                "--repo",
                github_repo,
                "--pattern",
                filename,
                "--dir",
                str(dest_dir),
                "--clobber",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and dest.is_file():
            return dest
        last_stderr = result.stderr.strip() or result.stdout.strip()
        if attempt < max_attempts:
            print(
                f"gh release download attempt {attempt}/{max_attempts} failed; "
                f"asset may not be propagated yet, retrying in {sleep_seconds}s...",
                file=sys.stderr,
            )
            if last_stderr:
                print(last_stderr, file=sys.stderr)
            time.sleep(sleep_seconds)
    print(
        f"Error downloading {filename} from {github_repo}@{tag} via gh: {last_stderr}",
        file=sys.stderr,
    )
    sys.exit(1)


def format_checksum_file(checksums: dict[str, str]) -> str:
    """Format checksums as an Elixir map literal for RustlerPrecompiled.

    Each entry is formatted as:
        "filename" => "sha256:hexdigest",

    Entries are sorted by key for deterministic output.
    """
    lines = ["%{"]
    for filename in sorted(checksums):
        digest = checksums[filename]
        lines.append(f'  "{filename}" => "sha256:{digest}",')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    github_repo = os.environ.get("INPUT_GITHUB_REPO", "")
    tag = os.environ.get("INPUT_TAG", "")
    version = os.environ.get("INPUT_VERSION", "")
    lib_name = os.environ.get("INPUT_LIB_NAME", "")
    nif_versions_raw = os.environ.get("INPUT_NIF_VERSIONS", "2.16,2.17")
    targets_raw = os.environ.get("INPUT_TARGETS", "")
    output_path = Path(os.environ.get("INPUT_OUTPUT_PATH", ""))

    for name, value in [
        ("INPUT_GITHUB_REPO", github_repo),
        ("INPUT_TAG", tag),
        ("INPUT_VERSION", version),
        ("INPUT_LIB_NAME", lib_name),
        ("INPUT_TARGETS", targets_raw),
        ("INPUT_OUTPUT_PATH", str(output_path)),
    ]:
        if not value:
            print(f"Error: {name} is required", file=sys.stderr)
            sys.exit(1)

    nif_versions = [v.strip() for v in nif_versions_raw.split(",") if v.strip()]
    targets = [t.strip() for t in targets_raw.split(",") if t.strip()]

    checksums: dict[str, str] = {}

    with tempfile.TemporaryDirectory(prefix="elixir-nif-checksum-") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        for nif_version in nif_versions:
            for target in targets:
                filename = build_nif_artifact_name(lib_name, version, nif_version, target)
                print(f"Downloading {filename}...")
                asset_path = download_asset_via_gh(github_repo, tag, filename, tmpdir)
                data = asset_path.read_bytes()
                digest = compute_sha256_hex(data)
                checksums[filename] = digest
                print(f"  sha256: {digest}")

    content = format_checksum_file(checksums)
    output_path.write_text(content, encoding="utf-8")
    print(f"Wrote checksum file: {output_path}")

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a") as fh:
            fh.write(f"checksum-file={output_path}\n")


if __name__ == "__main__":
    main()
