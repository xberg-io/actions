#!/usr/bin/env python3
"""Verify a built package artifact ships the expected files.

Per-language allowlists are encoded below. Each entry is an fnmatch-style
glob applied to the archive's file listing. A pattern matches if at least
one file in the artifact matches it; missing patterns are reported.

Usage (GitHub Actions composite, env vars set by action.yml):
    Single file: INPUT_LANGUAGE=python INPUT_ARTIFACT_PATH=dist/liter_llm-1.4.0rc27-...whl python3 verify.py
    Directory:   INPUT_LANGUAGE=python INPUT_ARTIFACT_PATH=dist python3 verify.py

When artifact-path is a directory, the script finds all archive files
matching supported extensions (.whl, .jar, .nupkg, .zip, .tar.gz, .tgz, .crate, .gem, .tar)
and verifies each one using recursive glob.
"""

from __future__ import annotations

import fnmatch
import os
import sys
import tarfile
import zipfile
from pathlib import Path

# Per-language allowlists. Each list contains fnmatch patterns; for a binding
# to pass, every pattern must match at least one file in the artifact.
# Patterns intentionally use broad wildcards so they survive minor layout shifts
# (e.g. different native-extension filenames per platform).
ALLOWLISTS: dict[str, list[str]] = {
    "python": [
        "*.dist-info/METADATA",
        "*.dist-info/WHEEL",
        "*.dist-info/RECORD",
        "*/py.typed",
        "*/_internal_bindings.pyi",
        "*/__init__.py",
        # native lib — exact name varies by platform/arch
        "*.so",
        "*.dist-info/licenses/LICENSE*",
    ],
    "python-sdist": [
        "*/PKG-INFO",
        "*/pyproject.toml",
        "*/README*",
        "*/LICENSE*",
    ],
    "node": [
        "package/package.json",
        "package/index.js",
        "package/index.d.ts",
        "package/LICENSE*",
    ],
    "node-platform": [
        # platform-specific NAPI prebuild package (one .node binary)
        "package/package.json",
        "package/*.node",
    ],
    "wasm": [
        "package/package.json",
        "package/*.wasm",
        "package/*.d.ts",
        "package/*.js",
        "package/LICENSE*",
    ],
    "ruby": [
        "data.tar.gz",
        "metadata.gz",
        "checksums.yaml.gz",
    ],
    # When iterating inside data.tar.gz of a gem, these must be present.
    "ruby-data": [
        "lib/liter_llm.rb",
        "lib/liter_llm/version.rb",
        "sig/*.rbs",
        "LICENSE*",
        "README*",
    ],
    "java": [
        "META-INF/MANIFEST.MF",
        "META-INF/maven/*/*/pom.properties",
        "META-INF/maven/*/*/pom.xml",
        # at least one .class
        "*.class",
    ],
    "java-natives": [
        # JNI native lib jar — one platform per artifact
        "natives/*",
    ],
    "csharp": [
        "*.nuspec",
        "lib/*/*.dll",
        "LICENSE*",
        "README*",
    ],
    "csharp-runtime": [
        # NuGet package shipping per-RID native binaries
        "runtimes/*/native/*",
    ],
    "php": [
        "composer.json",
        "src/*.php",
        "LICENSE*",
    ],
    "elixir": [
        "metadata.config",
        "contents.tar.gz",
    ],
    "elixir-contents": [
        # inside contents.tar.gz of a hex package
        "lib/liter_llm*.ex",
        "mix.exs",
        "checksum-*.exs",
    ],
    "go": [
        # Go modules are source-only; we publish the package by tagging the
        # repo. A go.mod + at least one .go file in the package path is the
        # bare minimum.
        "*/go.mod",
        "*/*.go",
    ],
    "rust": [
        # crates.io .crate is a tar.gz of source
        "*/Cargo.toml",
        "*/Cargo.toml.orig",
        "*/src/*.rs",
        "*/LICENSE*",
    ],
    "c": [
        # FFI release artifact (tarball of headers + libs)
        "*/include/*.h",
        "*/lib/lib*",
    ],
    "homebrew": [
        # bottle tarball: <formula>/<version>/bin/<binary>
        "*/bin/*",
    ],
}


def list_archive(path: Path) -> list[str]:
    """Return a list of file names contained in path. Supports zip, tar, tgz, gz."""
    name = path.name.lower()
    if name.endswith((".whl", ".jar", ".nupkg", ".zip")):
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    if name.endswith((".tar.gz", ".tgz", ".crate")):
        with tarfile.open(path, "r:gz") as tf:
            return list(tf.getnames())
    if name.endswith((".gem", ".tar")):
        # gem files are uncompressed tar archives containing data.tar.gz + metadata.gz
        with tarfile.open(path, "r:") as tf:
            return list(tf.getnames())
    msg = f"Unsupported artifact extension: {path.name}"
    raise SystemExit(msg)


def find_archives_in_directory(directory: Path) -> list[Path]:
    """Find all archive files matching supported extensions in directory (recursive)."""
    supported_extensions = (
        ".whl", ".jar", ".nupkg", ".zip",
        ".tar.gz", ".tgz", ".crate",
        ".gem", ".tar"
    )
    archives = []
    for archive in directory.rglob("*"):
        if archive.is_file() and archive.name.lower().endswith(supported_extensions):
            archives.append(archive)
    return sorted(archives)


def match_patterns(files: list[str], patterns: list[str]) -> tuple[list[str], list[str]]:
    """Return (matched_patterns, missing_patterns)."""
    matched: list[str] = []
    missing: list[str] = []
    for pat in patterns:
        if any(fnmatch.fnmatch(f, pat) for f in files):
            matched.append(pat)
        else:
            missing.append(pat)
    return matched, missing


def main() -> int:
    language = os.environ.get("INPUT_LANGUAGE", "").strip()
    artifact = Path(os.environ.get("INPUT_ARTIFACT_PATH", "").strip())
    extras = [
        line.strip()
        for line in os.environ.get("INPUT_REQUIRED_EXTRAS", "").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    strict = os.environ.get("INPUT_STRICT", "true").lower() == "true"

    if language not in ALLOWLISTS:
        print(f"::error::Unknown language: {language!r}. Known: {', '.join(sorted(ALLOWLISTS))}")
        return 2
    if not artifact.exists():
        print(f"::error::Artifact not found: {artifact}")
        return 2

    # Determine if artifact is a file or directory
    if artifact.is_file():
        # Single file mode: verify the single archive
        archives = [artifact]
    elif artifact.is_dir():
        # Directory mode: find all supported archive files inside (recursive)
        archives = find_archives_in_directory(artifact)
        if not archives:
            print(f"::error::No archive files found in {artifact}")
            return 2
    else:
        print(f"::error::Artifact is neither a file nor a directory: {artifact}")
        return 2

    # Verify each archive
    patterns = [*ALLOWLISTS[language], *extras]
    total_files = 0
    total_matched = 0
    all_missing: set[str] = set()
    had_error = False

    for archive in archives:
        try:
            files = list_archive(archive)
            matched, missing = match_patterns(files, patterns)
            total_files += len(files)
            total_matched += len(matched)
            all_missing.update(missing)

            print(f"::group::Archive: {archive.relative_to(artifact.parent) if artifact.is_dir() else archive.name}")
            print(f"Files: {len(files)}, Matched: {len(matched)}, Missing: {len(missing)}")
            if missing:
                for m in missing:
                    print(f"  - {m}")
            print("::endgroup::")

            if missing and strict:
                had_error = True
        except Exception as e:
            print(f"::error::Failed to verify {archive}: {e}")
            had_error = True

    # Aggregate output
    print(f"::group::Verification summary — {language}")
    print(f"Archives verified: {len(archives)}")
    print(f"Total files: {total_files}")
    print(f"Patterns checked: {len(patterns)}")
    print(f"Unique missing patterns: {len(all_missing)}")
    if all_missing:
        for m in sorted(all_missing):
            print(f"  - {m}")
    print("::endgroup::")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with Path(out).open("a", encoding="utf-8") as fh:
            fh.write(f"matched={total_matched}\n")
            fh.write(f"file-count={total_files}\n")
            fh.write("missing<<EOF\n")
            for m in sorted(all_missing):
                fh.write(f"{m}\n")
            fh.write("EOF\n")

    if had_error and strict:
        print(f"::error::Package verification failed; {len(all_missing)} unique missing pattern(s); see log.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
