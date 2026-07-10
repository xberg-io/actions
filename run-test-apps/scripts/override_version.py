#!/usr/bin/env python3
"""Override test-app version pin in alef.toml."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        import tomlkit
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages", "tomlkit"],
            check=True,
        )
        import tomlkit

    language = os.environ.get("INPUT_LANGUAGE", "").strip()
    version = os.environ.get("INPUT_VERSION", "").strip()
    working_directory = os.environ.get("INPUT_WORKING_DIRECTORY", ".").strip()

    if not language:
        print("::error::INPUT_LANGUAGE is required", file=sys.stderr)
        sys.exit(1)
    if not version:
        print("::error::INPUT_VERSION is required", file=sys.stderr)
        sys.exit(1)

    alef_toml_path = Path(working_directory) / "alef.toml"
    if not alef_toml_path.exists():
        print(
            f"::error::alef.toml not found at {alef_toml_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    content = alef_toml_path.read_text()
    doc = tomlkit.parse(content)

    found = False
    if "crates" in doc and isinstance(doc["crates"], dict):
        for crate_name, crate_config in doc["crates"].items():
            if not isinstance(crate_config, dict):
                continue
            if "e2e" not in crate_config:
                continue
            e2e = crate_config["e2e"]
            if not isinstance(e2e, dict):
                continue
            if "registry" not in e2e:
                continue
            registry = e2e["registry"]
            if not isinstance(registry, dict):
                continue
            if "packages" not in registry:
                continue
            packages = registry["packages"]
            if not isinstance(packages, dict):
                continue
            if language in packages:
                pkg = packages[language]
                if isinstance(pkg, dict):
                    pkg["version"] = version
                    found = True
                    print(f"Updated {crate_name}.e2e.registry.packages.{language}.version to {version}")

    if not found:
        print(
            f"::error::No matching package entry for language '{language}' found in alef.toml",
            file=sys.stderr,
        )
        sys.exit(1)

    alef_toml_path.write_text(tomlkit.dumps(doc))
    print("Successfully updated alef.toml")


if __name__ == "__main__":
    main()
