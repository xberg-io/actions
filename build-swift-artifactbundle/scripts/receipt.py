"""Write the preparation receipt that binds a Swift bundle to its source, version and exact bytes.

The receipt matches the schema alef's version sync validates before it pins the bundle's
checksum into the root Package.swift, so the manifest can be finalized before the release tag.
"""

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

SCHEMA = 1


def build_receipt(bundle: Path, version: str, repository: str, source: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{40}", source) is None:
        raise ValueError(f"source must be a full commit id, got {source!r}")
    if not version:
        raise ValueError("version must be the release version the source declares")
    if re.fullmatch(r"[^/\s]+/[^/\s]+", repository) is None:
        raise ValueError(f"repository must be owner/name, got {repository!r}")
    root = bundle.name.removesuffix(".zip")
    with zipfile.ZipFile(bundle) as archive:
        info = json.loads(archive.read(f"{root}/info.json"))
    artifacts = info.get("artifacts", {})
    if len(artifacts) != 1:
        raise ValueError(f"bundle must declare exactly one artifact, found {sorted(artifacts)}")
    artifact = next(iter(artifacts.values()))
    triples = [triple for variant in artifact.get("variants", []) for triple in variant.get("supportedTriples", [])]
    return {
        "schema": SCHEMA,
        "repository": repository,
        "source": source,
        "version": version,
        "archive": bundle.name,
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "triples": sorted(triples),
        "artifact_version": artifact.get("version", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source", required=True)
    arguments = parser.parse_args()
    try:
        receipt = build_receipt(arguments.zip, arguments.version, arguments.repository, arguments.source)
    except (ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f"::error::Swift preparation receipt: {error}", file=sys.stderr)
        return 1
    path = arguments.zip.with_name(arguments.zip.name.removesuffix(".zip") + ".release.json")
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
