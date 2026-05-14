#!/usr/bin/env python3
"""Stage build-java-natives artifacts into a Maven resources tree.

build-java-natives produces `{output-dir}/native/{classifier}/{libfile}`. The
publish workflow uploads `{output-dir}` as the artifact `java-natives-{label}`
and the downstream Java package job downloads them all into a single tree. With
`merge-multiple: true` on actions/download-artifact, all per-classifier libs end
up under `{artifacts-dir}/native/{classifier}/{libfile}` regardless of which
upload they came from.

This script walks the artifacts tree, copies each lib into
`{resources-dir}/{classifier}/`, then verifies every classifier in
`required-classifiers` has exactly one matching library file.

Inputs (env vars):
    INPUT_ARTIFACTS_DIR: source tree containing native/{classifier}/{libfile}
    INPUT_RESOURCES_DIR: destination Maven resources dir
    INPUT_REQUIRED_CLASSIFIERS: whitespace-separated classifier list
    INPUT_LIB_NAME: library base name (used to confirm each classifier has it)
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

LIB_EXTENSIONS = (".so", ".dylib", ".dll")


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"::error::stage-java-natives: '{name}' is empty", file=sys.stderr)
        sys.exit(1)
    return value


def discover_libs(artifacts_dir: Path) -> list[Path]:
    libs: list[Path] = []
    for ext in LIB_EXTENSIONS:
        libs.extend(artifacts_dir.rglob(f"*{ext}"))
    return sorted(libs)


def stage_libs(libs: list[Path], resources_dir: Path) -> dict[str, list[Path]]:
    """Copy each lib into {resources_dir}/{classifier}/ and return a map of
    classifier -> staged file paths.
    """
    staged: dict[str, list[Path]] = {}
    resources_dir.mkdir(parents=True, exist_ok=True)
    for lib in libs:
        classifier = lib.parent.name
        target_dir = resources_dir / classifier
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / lib.name
        shutil.copy2(lib, target)
        staged.setdefault(classifier, []).append(target)
    return staged


def verify_required(
    staged: dict[str, list[Path]],
    resources_dir: Path,
    required: list[str],
    lib_name: str,
) -> None:
    missing: list[str] = []
    for classifier in required:
        candidates = [staged_lib for staged_lib in staged.get(classifier, []) if lib_name in staged_lib.name]
        if not candidates:
            missing.append(classifier)
    if missing:
        for classifier in missing:
            print(
                f"::error::stage-java-natives: missing lib for classifier "
                f"'{classifier}' (expected file containing '{lib_name}' under "
                f"{resources_dir}/{classifier}/)",
                file=sys.stderr,
            )
        sys.exit(1)


def main() -> None:
    artifacts_dir = Path(require_env("INPUT_ARTIFACTS_DIR"))
    resources_dir = Path(require_env("INPUT_RESOURCES_DIR"))
    required = require_env("INPUT_REQUIRED_CLASSIFIERS").split()
    lib_name = require_env("INPUT_LIB_NAME")

    if not artifacts_dir.is_dir():
        print(
            f"::error::stage-java-natives: artifacts-dir '{artifacts_dir}' does not exist",
            file=sys.stderr,
        )
        sys.exit(1)

    libs = discover_libs(artifacts_dir)
    if not libs:
        print(
            f"::error::stage-java-natives: no *.so/*.dylib/*.dll files found under '{artifacts_dir}'",
            file=sys.stderr,
        )
        sys.exit(1)

    staged = stage_libs(libs, resources_dir)

    print("=== Staged native resources ===")
    for path in sorted(p for files in staged.values() for p in files):
        print(path)

    verify_required(staged, resources_dir, required, lib_name)
    print(f"stage-java-natives: all {len(required)} required classifier(s) present.")


if __name__ == "__main__":
    main()
