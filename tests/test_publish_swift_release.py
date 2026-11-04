"""Local Git regressions for publish-swift-release: the core tag is verified, never rewritten."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "publish-swift-release" / "scripts" / "publish_swift_release.py"
_REPOSITORY = "xberg-io/example"
_TAG = "v1.2.3"
_ASSET = "Example-rs.artifactbundle.zip"
_BUNDLE = b"PK\x03\x04prepared swift bundle bytes"
_MANIFEST = """// swift-tools-version: 5.9
import PackageDescription

let package = Package(
  name: "Example",
  targets: [
    .binaryTarget(
      name: "RustBridgeBinary",
      url: "https://github.com/{repository}/releases/download/{tag}/{asset}",
      checksum: "{checksum}"
    ),
  ]
)
"""

_FAKE_GH = r"""#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path

root = Path(os.environ["FAKE_GH_RELEASES"])
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
args = sys.argv[1:]
options, positional, index = {}, [], 0
while index < len(args):
    if args[index].startswith("--"):
        options[args[index]] = args[index + 1]
        index += 2
    else:
        positional.append(args[index])
        index += 1
assert positional[0] == "release", args
assert options.get("--repo") == os.environ["EXPECTED_REPOSITORY"], args
command, tag = positional[1], positional[2]
release = root / tag
if not release.is_dir():
    sys.exit("release not found")
if command == "view":
    hook = os.environ.get("FAKE_GH_ON_VIEW")
    if hook:
        import subprocess
        subprocess.run(hook, shell=True, check=True, capture_output=True)
    print(json.dumps({"assets": [{"name": path.name} for path in sorted(release.iterdir())]}))
elif command == "download":
    shutil.copy(release / options["--pattern"], Path(options["--dir"]) / options["--pattern"])
elif command == "upload":
    source = Path(positional[3])
    if (release / source.name).exists():
        sys.exit("asset already exists")
    shutil.copy(source, release / source.name)
else:
    sys.exit(f"unexpected gh command {args}")
"""


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Release:
    """A bare origin, a tagged clone and a fake GitHub release store."""

    def __init__(
        self, tmp_path: Path, checksum: str, *, tag_in_url: str = _TAG, lightweight: bool = False, extra: str = ""
    ) -> None:
        self.tmp = tmp_path
        self.origin = tmp_path / "origin.git"
        self.clone = tmp_path / "clone"
        self.releases = tmp_path / "releases"
        self.log = tmp_path / "gh.log"
        _git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(self.origin))
        _git(tmp_path, "clone", "--quiet", str(self.origin), str(self.clone))
        _git(self.clone, "config", "user.name", "Release Bot")
        _git(self.clone, "config", "user.email", "bot@example.invalid")
        (self.clone / "src.rs").write_text("pub fn core() {}\n")
        _git(self.clone, "add", "src.rs")
        _git(self.clone, "commit", "--quiet", "-m", "source")
        self.source = _git(self.clone, "rev-parse", "HEAD")
        manifest = _MANIFEST.format(repository=_REPOSITORY, tag=tag_in_url, asset=_ASSET, checksum=checksum) + extra
        (self.clone / "Package.swift").write_text(manifest)
        _git(self.clone, "add", "Package.swift")
        _git(self.clone, "commit", "--quiet", "-m", "chore(release): finalize Swift checksum")
        self.commit = _git(self.clone, "rev-parse", "HEAD")
        if lightweight:
            _git(self.clone, "-c", "tag.gpgSign=false", "tag", _TAG)
        else:
            _git(self.clone, "tag", "-a", _TAG, "-m", _TAG)
        _git(self.clone, "push", "--quiet", "origin", "main", f"refs/tags/{_TAG}")
        self.tag_object = self.remote_ref(f"refs/tags/{_TAG}")
        (self.releases / _TAG).mkdir(parents=True)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(_FAKE_GH.replace("/usr/bin/env python3", sys.executable, 1))
        gh.chmod(0o755)
        self.output = tmp_path / "github_output"
        self.output.touch()

    def remote_ref(self, ref: str) -> str:
        return _git(self.origin, "for-each-ref", "--format=%(objectname)", ref)

    def write_bundle(self, data: bytes = _BUNDLE) -> Path:
        path = self.tmp / "dist" / _ASSET
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        return path

    def seed_asset(self, data: bytes = _BUNDLE) -> None:
        (self.releases / _TAG / _ASSET).write_bytes(data)

    def gh_calls(self, command: str) -> list[list[str]]:
        if not self.log.exists():
            return []
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [call for call in calls if call[1] == command]

    def run(
        self, bundle: Path | None, *, cwd: Path | None = None, on_view: str = "", **inputs: str
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "FAKE_GH_ON_VIEW": on_view,
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_RELEASES": str(self.releases),
            "FAKE_GH_LOG": str(self.log),
            "EXPECTED_REPOSITORY": _REPOSITORY,
            "GITHUB_OUTPUT": str(self.output),
            "INPUT_TAG": _TAG,
            "INPUT_REPOSITORY": _REPOSITORY,
            "INPUT_BUNDLE_ZIP": str(bundle) if bundle else "",
            "INPUT_MANIFEST_PATH": "Package.swift",
            "INPUT_LEGACY_BRANCH": "release/swift/{version}",
            "INPUT_RECEIPT": "",
            "INPUT_REMOTE": "origin",
            "INPUT_DRY_RUN": "false",
            **{f"INPUT_{key.upper()}": value for key, value in inputs.items()},
        }
        return subprocess.run(
            [sys.executable, str(_SCRIPT)], cwd=cwd or self.clone, env=env, capture_output=True, text=True, check=False
        )

    def assert_tag_unchanged(self) -> None:
        assert self.remote_ref(f"refs/tags/{_TAG}") == self.tag_object
        assert _git(self.origin, "rev-parse", f"refs/tags/{_TAG}^{{commit}}") == self.commit

    def outputs(self) -> dict[str, str]:
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())


@pytest.fixture
def release(tmp_path: Path) -> Release:
    return Release(tmp_path, _sha256(_BUNDLE))


def test_first_publish_uploads_the_prepared_bytes_and_creates_the_branch_at_the_tag_commit(release: Release) -> None:
    result = release.run(release.write_bundle())

    assert result.returncode == 0, result.stderr
    assert (release.releases / _TAG / _ASSET).read_bytes() == _BUNDLE
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == release.commit
    release.assert_tag_unchanged()
    assert release.outputs() == {
        "checksum": _sha256(_BUNDLE),
        "commit": release.commit,
        "tag-object": release.tag_object,
        "asset-uploaded": "true",
        "branch-created": "true",
    }


def test_retry_after_success_mutates_nothing(release: Release) -> None:
    assert release.run(release.write_bundle()).returncode == 0
    release.output.write_text("")

    result = release.run(release.write_bundle())

    assert result.returncode == 0, result.stderr
    assert len(release.gh_calls("upload")) == 1
    release.assert_tag_unchanged()
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == release.commit
    assert release.outputs()["asset-uploaded"] == "false"
    assert release.outputs()["branch-created"] == "false"


def test_existing_release_asset_is_reused_when_no_local_bundle_is_supplied(release: Release) -> None:
    release.seed_asset()

    result = release.run(None)

    assert result.returncode == 0, result.stderr
    assert release.gh_calls("upload") == []
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == release.commit
    release.assert_tag_unchanged()


def test_missing_bundle_and_missing_asset_fails_before_any_mutation(release: Release) -> None:
    result = release.run(None)

    assert result.returncode != 0
    assert "no prepared Swift bundle" in result.stderr
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == ""


def test_local_bundle_that_differs_from_the_tagged_checksum_fails_before_publication(release: Release) -> None:
    result = release.run(release.write_bundle(b"rebuilt, non-identical bytes"))

    assert result.returncode != 0
    assert "does not match the checksum pinned" in result.stderr
    assert release.gh_calls("upload") == []
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == ""
    release.assert_tag_unchanged()


def test_existing_release_asset_with_different_bytes_fails_before_publication(release: Release) -> None:
    release.seed_asset(b"stale asset from an earlier attempt")

    result = release.run(release.write_bundle())

    assert result.returncode != 0
    assert "already holds different bytes" in result.stderr
    assert release.gh_calls("upload") == []
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == ""
    release.assert_tag_unchanged()


def test_divergent_legacy_branch_fails_before_publication(release: Release) -> None:
    _git(release.clone, "push", "--quiet", "origin", f"{release.source}:refs/heads/release/swift/1.2.3")

    result = release.run(release.write_bundle())

    assert result.returncode != 0
    assert "points at" in result.stderr
    assert release.gh_calls("upload") == []
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == release.source
    release.assert_tag_unchanged()


def test_tag_cut_before_checksum_finalization_is_rejected(tmp_path: Path) -> None:
    release = Release(tmp_path, "__ALEF_SWIFT_CHECKSUM__")

    result = release.run(release.write_bundle())

    assert result.returncode != 0
    assert "placeholder" in result.stderr
    assert release.gh_calls("upload") == []
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == ""
    release.assert_tag_unchanged()


def test_manifest_pointing_at_another_release_is_rejected(tmp_path: Path) -> None:
    release = Release(tmp_path, _sha256(_BUNDLE), tag_in_url="v1.2.2")

    result = release.run(release.write_bundle())

    assert result.returncode != 0
    assert "binaryTarget URL" in result.stderr
    assert release.gh_calls("upload") == []


def test_missing_tag_is_rejected(release: Release) -> None:
    result = release.run(release.write_bundle(), tag="v9.9.9")

    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert release.gh_calls("upload") == []


def test_dry_run_verifies_without_publishing(release: Release) -> None:
    result = release.run(release.write_bundle(), dry_run="true")

    assert result.returncode == 0, result.stderr
    assert release.gh_calls("upload") == []
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == ""
    release.assert_tag_unchanged()


def test_empty_legacy_branch_skips_branch_creation(release: Release) -> None:
    result = release.run(release.write_bundle(), legacy_branch="")

    assert result.returncode == 0, result.stderr
    assert _git(release.origin, "for-each-ref", "refs/heads/release") == ""
    assert release.outputs()["branch-created"] == "false"


def _receipt(release: Release, **overrides: str) -> Path:
    receipt = {
        "schema": 1,
        "repository": _REPOSITORY,
        "source": release.source,
        "version": "1.2.3",
        "archive": _ASSET,
        "sha256": _sha256(_BUNDLE),
        "triples": ["arm64-apple-macosx"],
        "artifact_version": "1.0.0",
        **overrides,
    }
    path = release.tmp / "receipt.json"
    path.write_text(json.dumps(receipt))
    return path


def test_receipt_bound_to_an_ancestor_source_is_accepted(release: Release) -> None:
    result = release.run(release.write_bundle(), receipt=str(_receipt(release)))

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"sha256": "0" * 64}, "receipt sha256"),
        ({"archive": "Other-rs.artifactbundle.zip"}, "receipt archive"),
        ({"repository": "xberg-io/other"}, "receipt repository"),
        ({"source": "f" * 40}, "not an ancestor"),
    ],
    ids=["digest", "archive", "repository", "unrelated-source"],
)
def test_receipt_mismatch_fails_before_publication(release: Release, overrides: dict[str, str], message: str) -> None:
    result = release.run(release.write_bundle(), receipt=str(_receipt(release, **overrides)))

    assert result.returncode != 0
    assert message in result.stderr
    assert release.gh_calls("upload") == []
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == ""


def test_lightweight_tag_is_verified_and_left_unchanged(tmp_path: Path) -> None:
    release = Release(tmp_path, _sha256(_BUNDLE), lightweight=True)
    assert release.tag_object == release.commit

    result = release.run(release.write_bundle())

    assert result.returncode == 0, result.stderr
    assert release.outputs()["tag-object"] == release.commit
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == release.commit
    release.assert_tag_unchanged()


def test_manifest_with_two_checksums_is_rejected(tmp_path: Path) -> None:
    release = Release(tmp_path, _sha256(_BUNDLE), extra=f'// checksum: "{"b" * 64}"\n')

    result = release.run(release.write_bundle())

    assert result.returncode != 0
    assert "exactly one SHA-256 checksum" in result.stderr
    assert release.gh_calls("upload") == []


def test_missing_release_fails_with_an_explicit_message(release: Release) -> None:
    (release.releases / _TAG).rmdir()

    result = release.run(release.write_bundle())

    assert result.returncode != 0
    assert f"Release {_TAG} was not found" in result.stderr
    assert "Traceback" not in result.stderr
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == ""


def test_missing_bundle_file_fails_without_a_traceback(release: Release) -> None:
    result = release.run(release.tmp / "dist" / _ASSET)

    assert result.returncode != 0
    assert "Swift bundle" in result.stderr
    assert str(release.tmp / "dist" / _ASSET) in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("content", ["{not json", "[]", ""], ids=["invalid-json", "not-an-object", "empty"])
def test_malformed_receipt_fails_without_a_traceback(release: Release, content: str) -> None:
    receipt = release.tmp / "receipt.json"
    receipt.write_text(content)

    result = release.run(release.write_bundle(), receipt=str(receipt))

    assert result.returncode != 0
    assert str(receipt) in result.stderr
    assert "Traceback" not in result.stderr
    assert release.gh_calls("upload") == []


def test_missing_receipt_fails_without_a_traceback(release: Release) -> None:
    receipt = release.tmp / "absent.json"

    result = release.run(release.write_bundle(), receipt=str(receipt))

    assert result.returncode != 0
    assert str(receipt) in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"version": "1.2.2"}, "receipt version"),
        ({"artifact_version": ""}, "artifact_version"),
        ({"triples": []}, "triples"),
        ({"triples": ["arm64-apple-macosx", "arm64-apple-macosx"]}, "triples"),
    ],
    ids=["version", "artifact-version", "no-triples", "duplicate-triples"],
)
def test_receipt_identity_mismatch_fails_before_publication(
    release: Release, overrides: dict[str, object], message: str
) -> None:
    result = release.run(release.write_bundle(), receipt=str(_receipt(release, **overrides)))

    assert result.returncode != 0
    assert message in result.stderr
    assert release.gh_calls("upload") == []


def test_receipt_check_in_a_shallow_clone_asks_for_full_history(release: Release) -> None:
    shallow = release.tmp / "shallow"
    _git(release.tmp, "clone", "--quiet", "--depth", "1", f"file://{release.origin}", str(shallow))

    result = release.run(release.write_bundle(), cwd=shallow, receipt=str(_receipt(release)))

    assert result.returncode != 0
    assert "needs full history (fetch-depth: 0)" in result.stderr
    assert release.gh_calls("upload") == []


def test_tag_moved_after_verification_stops_before_any_mutation(release: Release) -> None:
    move = f"git -C {release.origin} tag -f {_TAG} {release.source}"

    result = release.run(release.write_bundle(), on_view=move)

    assert result.returncode != 0
    assert "moved" in result.stderr
    assert release.gh_calls("upload") == []
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == ""


def test_branch_created_concurrently_is_not_overwritten(release: Release) -> None:
    race = f"git -C {release.origin} update-ref refs/heads/release/swift/1.2.3 {release.source}"

    result = release.run(release.write_bundle(), on_view=race)

    assert result.returncode != 0
    assert "created concurrently" in result.stderr
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == release.source
    assert release.gh_calls("upload") == []
    release.assert_tag_unchanged()


def test_branch_is_created_before_the_upload_so_a_failed_upload_reruns_cleanly(release: Release) -> None:
    fail_upload = release.bin / "gh-real"
    (release.bin / "gh").rename(fail_upload)
    (release.bin / "gh").write_text(
        f'#!/bin/sh\n[ "$2" = upload ] && {{ echo upload failed >&2; exit 1; }}\nexec "{fail_upload}" "$@"\n'
    )
    (release.bin / "gh").chmod(0o755)

    first = release.run(release.write_bundle())

    assert first.returncode != 0
    assert "rerun" in first.stderr
    assert release.remote_ref("refs/heads/release/swift/1.2.3") == release.commit
    (release.bin / "gh").unlink()
    fail_upload.rename(release.bin / "gh")
    release.output.write_text("")

    second = release.run(release.write_bundle())

    assert second.returncode == 0, second.stderr
    assert release.outputs()["asset-uploaded"] == "true"
    assert release.outputs()["branch-created"] == "false"
    release.assert_tag_unchanged()


@pytest.mark.parametrize(
    "inputs",
    [{"tag": "--upload-pack=touch pwned"}, {"remote": "-oProxyCommand=x"}, {"legacy_branch": "bad..branch"}],
    ids=["tag", "remote", "branch"],
)
def test_option_shaped_or_invalid_ref_names_are_rejected(release: Release, inputs: dict[str, str]) -> None:
    result = release.run(release.write_bundle(), **inputs)

    assert result.returncode != 0
    assert "invalid" in result.stderr
    assert release.gh_calls("view") == []


def test_dry_run_does_not_claim_to_have_published(release: Release) -> None:
    result = release.run(release.write_bundle(), dry_run="true")

    assert result.returncode == 0, result.stderr
    assert "Published" not in result.stdout
