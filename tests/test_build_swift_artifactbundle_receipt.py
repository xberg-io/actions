"""The preparation receipt binds a Swift bundle to its source, version and exact bytes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_ACTION = _ROOT / "build-swift-artifactbundle" / "action.yml"
_SCRIPT = _ROOT / "build-swift-artifactbundle" / "scripts" / "receipt.py"
_SOURCE = "a" * 40
_INFO = {
    "schemaVersion": "1.0",
    "artifacts": {
        "RustBridgeBinary": {
            "type": "staticLibrary",
            "version": "1.0.0",
            "variants": [
                {"path": "Example-rs-macos-arm64/libexample.a", "supportedTriples": ["arm64-apple-macosx"]},
                {
                    "path": "Example-rs-ios-sim/libexample.a",
                    "supportedTriples": ["x86_64-apple-ios-simulator", "arm64-apple-ios-simulator"],
                },
            ],
        }
    },
}


def _bundle(tmp_path: Path, info: dict | None = None) -> Path:
    path = tmp_path / "Example-rs.artifactbundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Example-rs.artifactbundle/info.json", json.dumps(info or _INFO))
        archive.writestr("Example-rs.artifactbundle/Example-rs-macos-arm64/libexample.a", b"!<arch>\n")
    return path


def _run(bundle: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--zip",
            str(bundle),
            "--version",
            "1.2.3",
            "--repository",
            "xberg-io/example",
            "--source",
            _SOURCE,
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_receipt_records_the_exact_bytes_and_identity_alef_validates(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    result = _run(bundle)

    assert result.returncode == 0, result.stderr
    receipt_path = tmp_path / "Example-rs.artifactbundle.release.json"
    assert result.stdout.strip() == str(receipt_path)
    assert json.loads(receipt_path.read_text()) == {
        "schema": 1,
        "repository": "xberg-io/example",
        "source": _SOURCE,
        "version": "1.2.3",
        "archive": "Example-rs.artifactbundle.zip",
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "triples": ["arm64-apple-ios-simulator", "arm64-apple-macosx", "x86_64-apple-ios-simulator"],
        "artifact_version": "1.0.0",
    }


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--source", "HEAD"), "source"),
        (("--version", ""), "version"),
        (("--repository", "example"), "repository"),
    ],
    ids=["symbolic-source", "empty-version", "bare-repository"],
)
def test_receipt_rejects_an_ambiguous_identity(tmp_path: Path, arguments: tuple[str, str], message: str) -> None:
    result = _run(_bundle(tmp_path), *arguments)

    assert result.returncode != 0
    assert message in result.stderr
    assert not (tmp_path / "Example-rs.artifactbundle.release.json").exists()


def test_receipt_rejects_a_bundle_with_several_artifacts(tmp_path: Path) -> None:
    info = json.loads(json.dumps(_INFO))
    info["artifacts"]["Second"] = info["artifacts"]["RustBridgeBinary"]

    result = _run(_bundle(tmp_path, info))

    assert result.returncode != 0
    assert "exactly one artifact" in result.stderr


def test_action_writes_the_receipt_only_for_an_assembled_bundle() -> None:
    action = yaml.safe_load(_ACTION.read_text())
    assert action["inputs"]["receipt-version"]["default"] == ""
    steps = action["runs"]["steps"]
    receipt = next(step for step in steps if step.get("id") == "receipt")
    assert steps.index(receipt) > next(i for i, step in enumerate(steps) if step.get("id") == "build")
    condition = " ".join(receipt["if"].split())
    assert "inputs.receipt-version != ''" in condition
    assert "inputs.dry-run != 'true'" in condition
    assert "inputs.targets == ''" in condition
    assert receipt["env"]["BUNDLE_ZIP"] == "${{ steps.build.outputs.bundle-zip }}"
    assert action["outputs"]["receipt"]["value"] == "${{ steps.receipt.outputs.receipt }}"
