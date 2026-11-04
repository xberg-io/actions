"""Local Git regressions for prepare-swift-release: pin the checksum, then create the tag exactly once."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "prepare-swift-release" / "scripts" / "prepare_swift_release.py"
_ACTION = _ROOT / "prepare-swift-release" / "action.yml"
_WORKFLOW = _ROOT / ".github" / "workflows" / "reusable-swift-release-prepare.yml"
_REPOSITORY = "xberg-io/example"
_VERSION = "1.2.3"
_TAG = f"v{_VERSION}"
_ARTIFACT = "Example-rs"
_ARCHIVE = f"{_ARTIFACT}.artifactbundle.zip"
_URL = f"https://github.com/{_REPOSITORY}/releases/download/{_TAG}/{_ARCHIVE}"
_TRIPLES = ["aarch64-unknown-linux-gnu", "arm64-apple-macosx"]
_SOURCE_MANIFEST = f"""// swift-tools-version: 6.2
import PackageDescription

let package = Package(
  name: "Example",
  platforms: [
    .macOS(.v26),
    .iOS(.v16),
  ],
  targets: [
    .binaryTarget(
      name: "RustBridgeBinary",
      url: "{_URL}",
      checksum: "__ALEF_SWIFT_CHECKSUM__"
    ),
  ]
)
"""
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Release Bot",
    "GIT_AUTHOR_EMAIL": "bot@example.invalid",
    "GIT_COMMITTER_NAME": "Release Bot",
    "GIT_COMMITTER_EMAIL": "bot@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
_FAKE_ALEF = r"""#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path

assert sys.argv[1:] == ["sync-versions", "--regen"], sys.argv
receipt = json.loads(next(Path("dist/swift-artifactbundle").glob("*.release.json")).read_text())
manifest = Path("Package.swift")
manifest.write_bytes(manifest.read_bytes().replace(b"__ALEF_SWIFT_CHECKSUM__", receipt["sha256"].encode()))
if os.environ.get("FAKE_ALEF_RERENDER"):
    Path("poly.toml").write_text("rerendered = true\n")
    Path("test_apps").mkdir(exist_ok=True)
    Path("test_apps/new.txt").write_text("new\n")
"""


def _load_script():
    spec = importlib.util.spec_from_file_location("prepare_swift_release", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["prepare_swift_release"] = module
    spec.loader.exec_module(module)
    return module


psr = _load_script()


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True, env={**os.environ, **_GIT_ENV}
    ).stdout.strip()


def _bundle_bytes(triples: list[str]) -> bytes:
    info = {
        "schemaVersion": "1.0",
        "artifacts": {
            "RustBridgeBinary": {
                "type": "staticLibrary",
                "version": "1.0.0",
                "variants": [{"path": f"{triple}/libexample.a", "supportedTriples": [triple]} for triple in triples],
            }
        },
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{_ARTIFACT}.artifactbundle/info.json", json.dumps(info))
        for triple in triples:
            archive.writestr(f"{_ARTIFACT}.artifactbundle/{triple}/libexample.a", b"!<arch>\n" + b"x" * 64)
    return buffer.getvalue()


class Release:
    """A source repository with a bare origin, a prepared bundle and its receipt in dist/."""

    def __init__(self, base: Path, manifest: bytes = _SOURCE_MANIFEST.encode()) -> None:
        self.base = base
        self.origin = base / "origin.git"
        self.repo = base / "work"
        _git(base, "init", "--quiet", "--bare", "--initial-branch=main", str(self.origin))
        _git(base, "init", "--quiet", "--initial-branch=main", str(self.repo))
        _git(self.repo, "remote", "add", "origin", str(self.origin))
        (self.repo / ".gitignore").write_text("dist/\n")
        (self.repo / "poly.toml").write_text("rerendered = false\n")
        (self.repo / "Cargo.toml").write_text(f'[workspace.package]\nversion = "{_VERSION}"\n')
        (self.repo / "Package.swift").write_bytes(manifest)
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "--quiet", "-m", f"chore: release {_VERSION}")
        _git(self.repo, "push", "--quiet", "origin", "HEAD:refs/heads/main")
        self.source = _git(self.repo, "rev-parse", "HEAD")
        self.bundle_dir = self.repo / "dist" / "swift-artifactbundle"
        self.bundle_dir.mkdir(parents=True)
        self.zip = self.bundle_dir / _ARCHIVE
        self.zip.write_bytes(_bundle_bytes(_TRIPLES))
        self.checksum = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.receipt = self.bundle_dir / f"{_ARTIFACT}.artifactbundle.release.json"
        self.receipt_data = {
            "schema": 1,
            "repository": _REPOSITORY,
            "source": self.source,
            "version": _VERSION,
            "archive": _ARCHIVE,
            "sha256": self.checksum,
            "triples": sorted(_TRIPLES),
            "artifact_version": "1.0.0",
        }
        self.write_receipt()
        self.alef = base / "alef"
        self.alef.write_text(_FAKE_ALEF.replace("/usr/bin/env python3", sys.executable, 1))
        self.alef.chmod(0o755)

    def write_receipt(self, **overrides: object) -> None:
        self.receipt.write_text(json.dumps({**self.receipt_data, **overrides}))

    def pin_manifest(self) -> None:
        manifest = self.repo / "Package.swift"
        manifest.write_bytes(manifest.read_bytes().replace(b"__ALEF_SWIFT_CHECKSUM__", self.checksum.encode()))

    def remote(self, ref: str) -> str:
        return _git(self.origin, "rev-parse", ref)

    def remote_has(self, ref: str) -> bool:
        return bool(_git(self.origin, "for-each-ref", ref))

    def verify(self, expected_triples: list[str] | None = None) -> str:
        return psr.verify(
            self.repo,
            zip_path=self.zip,
            receipt_path=self.receipt,
            tag=_TAG,
            repository=_REPOSITORY,
            manifest="Package.swift",
            expected_triples=expected_triples,
        )

    def finalize(self, *, dry_run: bool = False) -> dict[str, str]:
        previous = os.environ.copy()
        os.environ.update(_GIT_ENV)
        try:
            return psr.finalize(
                self.repo, tag=_TAG, remote="origin", branch="main", manifest="Package.swift", dry_run=dry_run
            )
        finally:
            os.environ.clear()
            os.environ.update(previous)

    def fresh_checkout(self) -> None:
        """Rerun from a new clone that fetched only the source commit, with the downloaded pin and bundle.

        The clone lacks the objects of any earlier pin commit or tag, so the content checks must fetch them.
        """
        pinned = (self.repo / "Package.swift").read_bytes()
        bundle = {path.name: path.read_bytes() for path in self.bundle_dir.iterdir()}
        self.reruns = getattr(self, "reruns", 0) + 1
        self.repo = self.base / f"rerun-{self.reruns}"
        _git(self.base, "init", "--quiet", str(self.repo))
        _git(self.repo, "remote", "add", "origin", str(self.origin))
        _git(self.repo, "fetch", "--quiet", "--no-tags", "origin", self.source)
        _git(self.repo, "checkout", "--quiet", "--detach", self.source)
        assert not _git(self.repo, "tag", "--list"), "the rerun clone must not hold the release tag"
        self.bundle_dir = self.repo / "dist" / "swift-artifactbundle"
        self.bundle_dir.mkdir(parents=True)
        for name, data in bundle.items():
            (self.bundle_dir / name).write_bytes(data)
        self.zip = self.bundle_dir / _ARCHIVE
        self.receipt = self.bundle_dir / f"{_ARTIFACT}.artifactbundle.release.json"
        (self.repo / "Package.swift").write_bytes(pinned)

    def push_from_other_clone(self, path: str, content: str) -> str:
        other = self.base / "other"
        if not other.exists():
            _git(self.base, "clone", "--quiet", str(self.origin), str(other))
        _git(other, "pull", "--quiet", "--ff-only", "origin", "main")
        (other / path).write_text(content)
        _git(other, "add", path)
        _git(other, "commit", "--quiet", "-m", f"touch {path}")
        _git(other, "push", "--quiet", "origin", "HEAD:refs/heads/main")
        return self.remote("refs/heads/main")


@pytest.fixture
def release(tmp_path: Path) -> Release:
    return Release(tmp_path)


def _raises(call, match: str) -> None:
    with pytest.raises(psr.ReleaseError, match=match):
        call()


# ~keep Deployment targets


@pytest.mark.parametrize(
    ("macos", "ios", "expected"),
    [
        ("", "", {"macos": "26.0", "ios": "16.0"}),
        ("26.0", "", {"macos": "26.0", "ios": "16.0"}),
        ("26", "13.0", {"macos": "26.0", "ios": "13.0"}),
    ],
)
def test_deployment_targets_derive_from_the_manifest(macos: str, ios: str, expected: dict[str, str]) -> None:
    assert psr.deployment_targets(_SOURCE_MANIFEST, macos=macos, ios=ios) == expected


def test_deployment_targets_read_minor_versions_and_string_forms() -> None:
    manifest = _SOURCE_MANIFEST.replace(".macOS(.v26)", ".macOS(.v13_5)").replace(".iOS(.v16)", '.iOS("17.2")')
    assert psr.deployment_targets(manifest, macos="", ios="") == {"macos": "13.5", "ios": "17.2"}


def test_deployment_targets_ignore_commented_platforms() -> None:
    decoy = "  // .macOS(.v13),\n  /* .iOS(.v12)\n  */\n"
    manifest = _SOURCE_MANIFEST.replace("  platforms: [\n", "  platforms: [\n" + decoy)
    assert psr.deployment_targets(manifest, macos="", ios="") == {"macos": "26.0", "ios": "16.0"}


def test_deployment_targets_keep_comment_markers_inside_strings() -> None:
    manifest = _SOURCE_MANIFEST.replace(".macOS(.v26)", '.macOS("26.0") // https://example.invalid/*')
    assert psr.deployment_targets(manifest, macos="", ios="")["macos"] == "26.0"


def test_deployment_targets_reject_a_non_literal_minimum_behind_a_commented_literal() -> None:
    manifest = _SOURCE_MANIFEST.replace(".macOS(.v26),", "// .macOS(.v26),\n    .macOS(minimumMacOS),")
    _raises(lambda: psr.deployment_targets(manifest, macos="", ios=""), "literal")


def test_deployment_targets_reject_a_macos_input_that_disagrees_with_the_manifest() -> None:
    _raises(lambda: psr.deployment_targets(_SOURCE_MANIFEST, macos="13.0", ios=""), "macOS")


def test_deployment_targets_reject_an_ios_input_above_the_manifest_minimum() -> None:
    _raises(lambda: psr.deployment_targets(_SOURCE_MANIFEST, macos="", ios="17.0"), "iOS")


def test_deployment_targets_require_a_macos_minimum() -> None:
    manifest = _SOURCE_MANIFEST.replace("    .macOS(.v26),\n", "")
    _raises(lambda: psr.deployment_targets(manifest, macos="", ios=""), "macOS")


# ~keep Resolve


def test_resolve_derives_the_tag_from_cargo(release: Release) -> None:
    assert psr.resolve(release.repo, tag="", cargo_toml="Cargo.toml", remote="origin", branch="main") == {
        "tag": _TAG,
        "version": _VERSION,
        "source": release.source,
    }


def test_resolve_rejects_a_tag_that_does_not_match_cargo(release: Release) -> None:
    _raises(
        lambda: psr.resolve(release.repo, tag="v1.2.4", cargo_toml="Cargo.toml", remote="origin", branch="main"),
        "Cargo",
    )


def test_resolve_rejects_an_existing_tag(release: Release) -> None:
    _git(release.repo, "tag", _TAG)
    _git(release.repo, "push", "--quiet", "origin", f"refs/tags/{_TAG}")
    _raises(
        lambda: psr.resolve(release.repo, tag="", cargo_toml="Cargo.toml", remote="origin", branch="main"),
        "already exists",
    )


def test_resolve_rejects_a_source_that_is_not_the_branch_tip(release: Release) -> None:
    release.push_from_other_clone("README.md", "moved\n")
    _raises(lambda: psr.resolve(release.repo, tag="", cargo_toml="Cargo.toml", remote="origin", branch="main"), "main")


# ~keep Pin


def test_pin_keeps_only_the_manifest_and_warns_about_rerendered_files(
    release: Release, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ALEF_RERENDER", "1")
    restored = psr.pin(
        release.repo, manifest="Package.swift", bundle_dir="dist/swift-artifactbundle", alef=str(release.alef)
    )
    assert restored == ["poly.toml", "test_apps/new.txt"]
    assert "::warning::" in capsys.readouterr().out
    assert _git(release.repo, "status", "--porcelain") == "M Package.swift"
    assert release.checksum in (release.repo / "Package.swift").read_text()
    assert release.verify() == release.checksum


def test_pin_refuses_a_dirty_tree(release: Release) -> None:
    (release.repo / "poly.toml").write_text("local edit\n")
    _raises(
        lambda: psr.pin(
            release.repo, manifest="Package.swift", bundle_dir="dist/swift-artifactbundle", alef=str(release.alef)
        ),
        r"poly\.toml.*gitignore",
    )


def test_pin_fails_when_alef_leaves_the_manifest_unchanged(release: Release, tmp_path: Path) -> None:
    noop = tmp_path / "noop-alef"
    noop.write_text("#!/bin/sh\nexit 0\n")
    noop.chmod(0o755)
    _raises(
        lambda: psr.pin(release.repo, manifest="Package.swift", bundle_dir="dist/swift-artifactbundle", alef=str(noop)),
        "did not change",
    )


# ~keep Verify


def test_verify_accepts_exactly_the_checksum_pin(release: Release) -> None:
    release.pin_manifest()
    assert release.verify(expected_triples=list(reversed(_TRIPLES))) == release.checksum


def test_verify_accepts_a_pin_that_replaces_an_earlier_literal_checksum(tmp_path: Path) -> None:
    release = Release(tmp_path, _SOURCE_MANIFEST.replace("__ALEF_SWIFT_CHECKSUM__", "ab" * 32).encode())
    manifest = release.repo / "Package.swift"
    manifest.write_bytes(manifest.read_bytes().replace(b"ab" * 32, release.checksum.encode()))
    assert release.verify() == release.checksum


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("sha256", "cd" * 32, "sha256"),
        ("source", "0" * 40, "source"),
        ("version", "1.2.2", "version"),
        ("archive", "Other-rs.artifactbundle.zip", "archive"),
        ("repository", "xberg-io/other", "repository"),
        ("schema", 2, "schema"),
        ("triples", ["arm64-apple-macosx"], "triples"),
        ("artifact_version", "2.0.0", "artifact_version"),
    ],
)
def test_verify_rejects_a_receipt_that_does_not_describe_this_bundle(
    release: Release, field: str, value: object, match: str
) -> None:
    release.pin_manifest()
    release.write_receipt(**{field: value})
    _raises(release.verify, match)


@pytest.mark.parametrize("info", [[], {"artifacts": []}, {"artifacts": {"RustBridgeBinary": []}}])
def test_verify_rejects_a_malformed_info_json(release: Release, info: object) -> None:
    with zipfile.ZipFile(release.zip, "w") as archive:
        archive.writestr(f"{_ARTIFACT}.artifactbundle/info.json", json.dumps(info))
    release.checksum = hashlib.sha256(release.zip.read_bytes()).hexdigest()
    release.write_receipt(sha256=release.checksum)
    release.pin_manifest()
    _raises(release.verify, "exactly one artifact|list of variants")


def test_verify_rejects_a_platform_census_mismatch(release: Release) -> None:
    release.pin_manifest()
    _raises(lambda: release.verify(expected_triples=[*_TRIPLES, "x86_64-apple-macosx"]), "triples")


def test_verify_rejects_a_bundle_with_an_unsafe_entry(release: Release) -> None:
    with zipfile.ZipFile(release.zip, "a") as archive:
        archive.writestr("../escape", b"x")
    release.checksum = hashlib.sha256(release.zip.read_bytes()).hexdigest()
    release.write_receipt(sha256=release.checksum)
    release.pin_manifest()
    _raises(release.verify, "unsafe")


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda text, checksum: text, "placeholder"),
        (lambda text, checksum: text.replace("__ALEF_SWIFT_CHECKSUM__", "cd" * 32), "checksum"),
        (lambda text, checksum: text.replace("__ALEF_SWIFT_CHECKSUM__", checksum) + "// extra\n", "more than"),
        (lambda text, checksum: text.replace("__ALEF_SWIFT_CHECKSUM__", checksum).replace("\n", "\r\n"), "more than"),
        (lambda text, checksum: text.replace("__ALEF_SWIFT_CHECKSUM__", checksum).replace(_TAG, "v1.2.2"), "URL"),
        (
            lambda text, checksum: text.replace("__ALEF_SWIFT_CHECKSUM__", checksum) + f'// checksum: "{checksum}"\n',
            "exactly one",
        ),
    ],
)
def test_verify_rejects_a_manifest_that_is_not_exactly_the_pin(release: Release, mutate, match: str) -> None:
    manifest = release.repo / "Package.swift"
    manifest.write_bytes(mutate(_SOURCE_MANIFEST, release.checksum).encode())
    _raises(release.verify, match)


def test_verify_rejects_a_checksum_field_shape_publish_swift_release_would_not_read(release: Release) -> None:
    manifest = release.repo / "Package.swift"
    manifest.write_text(
        _SOURCE_MANIFEST.replace('checksum: "__ALEF_SWIFT_CHECKSUM__"', f'checksum : "{release.checksum}"')
    )
    _raises(release.verify, "exactly one")


def test_verify_rejects_a_file_mode_change(release: Release) -> None:
    release.pin_manifest()
    manifest = release.repo / "Package.swift"
    manifest.chmod(manifest.stat().st_mode | stat.S_IXUSR)
    _raises(release.verify, "mode")


def test_verify_rejects_other_changed_or_untracked_files(release: Release) -> None:
    release.pin_manifest()
    (release.repo / "poly.toml").write_text("drift\n")
    _raises(release.verify, "only Package.swift")
    _git(release.repo, "checkout", "--", "poly.toml")
    (release.repo / "stray.txt").write_text("stray\n")
    _raises(release.verify, "only Package.swift")


# ~keep Finalize


def test_first_run_pushes_the_pin_and_an_annotated_tag(release: Release) -> None:
    release.pin_manifest()
    result = release.finalize()
    commit = result["commit"]
    assert result == {"commit": commit, "tag-created": "true", "branch-updated": "true"}
    assert release.remote("refs/heads/main") == commit
    assert release.remote(f"{_TAG}^{{commit}}") == commit
    assert _git(release.origin, "cat-file", "-t", f"refs/tags/{_TAG}") == "tag"
    assert release.remote(f"{commit}^") == release.source
    assert _git(release.origin, "diff", "--name-only", release.source, commit) == "Package.swift"
    tagged = _git(release.origin, "show", f"{_TAG}:Package.swift")
    assert re.findall(r'checksum: "([0-9a-f]{64})"', tagged) == [release.checksum]


def test_retry_after_success_changes_no_ref(release: Release) -> None:
    release.pin_manifest()
    release.finalize()
    tag_object = release.remote(f"refs/tags/{_TAG}")
    main = release.remote("refs/heads/main")
    release.fresh_checkout()
    assert release.finalize() == {"commit": main, "tag-created": "false", "branch-updated": "false"}
    assert release.remote(f"refs/tags/{_TAG}") == tag_object
    assert release.remote("refs/heads/main") == main


def test_retry_after_success_accepts_main_that_moved_past_the_tag(release: Release) -> None:
    release.pin_manifest()
    commit = release.finalize()["commit"]
    release.push_from_other_clone("README.md", "later\n")
    release.fresh_checkout()
    assert release.finalize() == {"commit": commit, "tag-created": "false", "branch-updated": "false"}


def test_resume_after_a_pin_only_push_tags_that_commit(release: Release) -> None:
    release.pin_manifest()
    _git(release.repo, "commit", "--quiet", "-m", "pin", "--", "Package.swift")
    _git(release.repo, "push", "--quiet", "origin", "HEAD:refs/heads/main")
    pushed = release.remote("refs/heads/main")
    release.fresh_checkout()
    assert release.finalize() == {"commit": pushed, "tag-created": "true", "branch-updated": "false"}
    assert release.remote(f"{_TAG}^{{commit}}") == pushed
    assert release.remote("refs/heads/main") == pushed


def test_resume_after_a_tag_only_push_fast_forwards_main(release: Release) -> None:
    release.pin_manifest()
    _git(release.repo, "commit", "--quiet", "-m", "pin", "--", "Package.swift")
    _git(release.repo, "tag", "-a", _TAG, "-m", _TAG)
    _git(release.repo, "push", "--quiet", "origin", f"refs/tags/{_TAG}")
    tagged = release.remote(f"{_TAG}^{{commit}}")
    release.fresh_checkout()
    assert release.finalize() == {"commit": tagged, "tag-created": "false", "branch-updated": "true"}
    assert release.remote("refs/heads/main") == tagged


def test_main_that_moved_elsewhere_fails_before_any_tag(release: Release) -> None:
    release.pin_manifest()
    moved = release.push_from_other_clone("README.md", "unrelated\n")
    _raises(release.finalize, "moved")
    assert release.remote("refs/heads/main") == moved
    assert not release.remote_has(f"refs/tags/{_TAG}")


def test_a_pin_commit_with_different_bytes_on_main_is_not_resumed(release: Release) -> None:
    other = release.repo / "Package.swift"
    other.write_text(_SOURCE_MANIFEST.replace("__ALEF_SWIFT_CHECKSUM__", "ef" * 32))
    _git(release.repo, "commit", "--quiet", "-m", "pin other bytes", "--", "Package.swift")
    _git(release.repo, "push", "--quiet", "origin", "HEAD:refs/heads/main")
    moved = release.remote("refs/heads/main")
    release.fresh_checkout()
    (release.repo / "Package.swift").write_text(_SOURCE_MANIFEST)
    release.pin_manifest()
    _raises(release.finalize, "moved")
    assert release.remote("refs/heads/main") == moved
    assert not release.remote_has(f"refs/tags/{_TAG}")


def test_existing_divergent_tag_fails_and_is_left_alone(release: Release) -> None:
    _git(release.repo, "tag", "-a", _TAG, "-m", _TAG, release.source)
    _git(release.repo, "push", "--quiet", "origin", f"refs/tags/{_TAG}")
    _git(release.repo, "tag", "-d", _TAG)
    tag_object = release.remote(f"refs/tags/{_TAG}")
    release.pin_manifest()
    _raises(release.finalize, "not the checksum pin")
    assert release.remote(f"refs/tags/{_TAG}") == tag_object
    assert release.remote("refs/heads/main") == release.source


def test_existing_pin_tag_with_a_branch_that_moved_without_it_fails(release: Release) -> None:
    release.pin_manifest()
    _git(release.repo, "commit", "--quiet", "-m", "pin", "--", "Package.swift")
    _git(release.repo, "tag", "-a", _TAG, "-m", _TAG)
    _git(release.repo, "push", "--quiet", "origin", f"refs/tags/{_TAG}")
    release.fresh_checkout()
    moved = release.push_from_other_clone("README.md", "unrelated\n")
    _raises(release.finalize, "moved")
    assert release.remote("refs/heads/main") == moved


def test_a_missing_branch_fails_before_any_tag(release: Release) -> None:
    _git(release.origin, "update-ref", "-d", "refs/heads/main")
    release.pin_manifest()
    _raises(release.finalize, "moved")
    assert not release.remote_has(f"refs/tags/{_TAG}")


def test_dry_run_in_a_resume_state_pushes_nothing(release: Release) -> None:
    release.pin_manifest()
    _git(release.repo, "commit", "--quiet", "-m", "pin", "--", "Package.swift")
    _git(release.repo, "tag", "-a", _TAG, "-m", _TAG)
    _git(release.repo, "push", "--quiet", "origin", f"refs/tags/{_TAG}")
    release.fresh_checkout()
    result = release.finalize(dry_run=True)
    assert result["branch-updated"] == "false"
    assert release.remote("refs/heads/main") == release.source


def test_dry_run_with_the_pin_already_on_the_branch_creates_no_tag(release: Release) -> None:
    release.pin_manifest()
    _git(release.repo, "commit", "--quiet", "-m", "pin", "--", "Package.swift")
    _git(release.repo, "push", "--quiet", "origin", "HEAD:refs/heads/main")
    release.fresh_checkout()
    assert release.finalize(dry_run=True)["tag-created"] == "false"
    assert not release.remote_has(f"refs/tags/{_TAG}")


def _race(monkeypatch: pytest.MonkeyPatch, racer) -> None:
    real_push = psr.push

    def racing_push(repo: Path, remote: str, *refspecs: str) -> None:
        racer()
        real_push(repo, remote, *refspecs)

    monkeypatch.setattr(psr, "push", racing_push)


def test_a_main_push_that_races_the_atomic_push_lands_nothing(release: Release, monkeypatch) -> None:
    moved: list[str] = []
    _race(monkeypatch, lambda: moved.append(release.push_from_other_clone("README.md", "racer\n")))
    release.pin_manifest()
    _raises(release.finalize, "push")
    assert release.remote("refs/heads/main") == moved[0]
    assert not release.remote_has(f"refs/tags/{_TAG}")


def test_a_tag_that_races_the_atomic_push_lands_nothing(release: Release, monkeypatch) -> None:
    competitor: list[str] = []

    def push_competing_tag() -> None:
        other = release.base / "competitor"
        _git(release.base, "clone", "--quiet", str(release.origin), str(other))
        _git(other, "tag", "-a", _TAG, "-m", "competitor")
        _git(other, "push", "--quiet", "origin", f"refs/tags/{_TAG}")
        competitor.append(release.remote(f"refs/tags/{_TAG}"))

    _race(monkeypatch, push_competing_tag)
    release.pin_manifest()
    _raises(release.finalize, "push")
    assert release.remote("refs/heads/main") == release.source
    assert release.remote(f"refs/tags/{_TAG}") == competitor[0]


def test_dry_run_pushes_nothing(release: Release) -> None:
    release.pin_manifest()
    result = release.finalize(dry_run=True)
    assert result["tag-created"] == "false"
    assert result["branch-updated"] == "false"
    assert release.remote("refs/heads/main") == release.source
    assert not release.remote_has(f"refs/tags/{_TAG}")


def test_cli_reports_errors_as_annotations(release: Release, capsys: pytest.CaptureFixture[str]) -> None:
    previous = Path.cwd()
    os.chdir(release.repo)
    try:
        code = psr.main(["finalize", "--tag", "1.2.3"])
    finally:
        os.chdir(previous)
    assert code == 1
    assert "::error::" in capsys.readouterr().err


def test_cli_targets_exports_the_deployment_targets(release: Release, tmp_path: Path, monkeypatch) -> None:
    output, env = tmp_path / "output", tmp_path / "env"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_ENV", str(env))
    monkeypatch.chdir(release.repo)
    assert psr.main(["targets", "--manifest", "Package.swift", "--ios", "13.0"]) == 0
    assert env.read_text() == "MACOSX_DEPLOYMENT_TARGET=26.0\nIPHONEOS_DEPLOYMENT_TARGET=13.0\n"
    assert output.read_text() == "macos=26.0\nios=13.0\n"


def test_cli_verify_passes_every_flag_the_action_sends(release: Release, tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.chdir(release.repo)
    release.pin_manifest()
    arguments = ["verify", "--zip", str(release.zip), "--receipt", str(release.receipt), "--tag", _TAG]
    arguments += ["--repository", _REPOSITORY, "--manifest", "Package.swift"]
    assert psr.main([*arguments, "--expected-triples", ", ".join(_TRIPLES)]) == 0
    assert output.read_text() == f"checksum={release.checksum}\n"
    assert psr.main([*arguments, "--expected-triples", _TRIPLES[0]]) == 1


def test_cli_finalize_reports_a_git_failure_as_an_annotation(release: Release, capsys, monkeypatch) -> None:
    monkeypatch.chdir(release.repo)
    release.pin_manifest()
    assert psr.main(["finalize", "--tag", _TAG, "--remote", "missing"]) == 1
    assert "::error::Swift release preparation: git ls-remote" in capsys.readouterr().err


# ~keep Workflow and action shape


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text())


def _triggers(workflow: dict) -> dict:
    return workflow["on"] if "on" in workflow else workflow[True]


def _uses(job: dict, prefix: str) -> list[dict]:
    return [step for step in job["steps"] if str(step.get("uses", "")).startswith(prefix)]


def _prepare_commands(job: dict) -> list[str]:
    return [step["with"]["command"] for step in _uses(job, "xberg-io/actions/prepare-swift-release@")]


def test_workflow_is_only_callable_and_reads_by_default() -> None:
    workflow = _workflow()
    assert list(_triggers(workflow)) == ["workflow_call"]
    assert workflow["permissions"] == {"contents": "read"}
    assert "concurrency" not in workflow
    assert all("concurrency" not in job for job in workflow["jobs"].values())


def test_every_input_expression_names_a_declared_input() -> None:
    declared = set(_triggers(_workflow())["workflow_call"]["inputs"])
    referenced = set(re.findall(r"inputs\.([A-Za-z0-9_-]+)", _WORKFLOW.read_text()))
    assert referenced
    assert referenced - declared == set()


def test_every_secret_expression_names_a_declared_secret() -> None:
    declared = set(_triggers(_workflow())["workflow_call"]["secrets"])
    referenced = set(re.findall(r"secrets\.([A-Za-z0-9_-]+)", _WORKFLOW.read_text()))
    assert declared == {"app-id", "app-private-key"}
    assert referenced == declared


def test_jobs_build_once_then_finalize_then_release() -> None:
    jobs = _workflow()["jobs"]
    assert list(jobs) == ["build", "finalize", "release"]
    assert jobs["build"]["runs-on"] == "${{ inputs.runner }}"
    assert _triggers(_workflow())["workflow_call"]["inputs"]["runner"]["default"] == "macos-26"
    assert jobs["finalize"]["needs"] == "build"
    assert jobs["release"]["needs"] == ["build", "finalize"]
    assert jobs["finalize"]["if"] == "${{ !inputs.dry-run }}"
    assert _prepare_commands(jobs["build"]) == ["resolve", "targets", "pin", "verify", "finalize"]
    assert _prepare_commands(jobs["finalize"]) == ["verify", "finalize"]
    assert _prepare_commands(jobs["release"]) == []
    (bundle,) = _uses(jobs["build"], "xberg-io/actions/build-swift-artifactbundle@")
    assert bundle["with"]["receipt-version"] == "${{ steps.resolve.outputs.version }}"
    assert "package-manifest-path" not in bundle["with"]
    for name in ("finalize", "release"):
        assert not _uses(jobs[name], "xberg-io/actions/build-swift-artifactbundle@")
        assert not _uses(jobs[name], "xberg-io/actions/install-alef@")


def test_dry_run_finalize_in_the_build_job_never_pushes() -> None:
    build = _workflow()["jobs"]["build"]
    (step,) = [s for s in _uses(build, "xberg-io/actions/prepare-swift-release@") if s["with"]["command"] == "finalize"]
    assert step["if"] == "${{ inputs.dry-run }}"
    assert step["with"]["dry-run"] == "true"


def test_later_jobs_reuse_the_uploaded_bytes() -> None:
    jobs = _workflow()["jobs"]
    (upload,) = _uses(jobs["build"], "actions/upload-artifact@")
    assert upload["with"]["if-no-files-found"] == "error"
    for name in ("finalize", "release"):
        (download,) = _uses(jobs[name], "actions/download-artifact@")
        assert download["with"]["name"] == upload["with"]["name"]
    assert upload["with"]["name"] == "swift-release-prepared-${{ inputs.artifact-name }}"


def test_release_job_publishes_through_the_shared_action_and_a_verified_draft() -> None:
    release = _workflow()["jobs"]["release"]
    (publish,) = _uses(release, "xberg-io/actions/publish-swift-release@")
    assert publish["uses"] == "xberg-io/actions/publish-swift-release@v1"
    assert publish["with"]["bundle-zip"] == "${{ needs.build.outputs.bundle-zip }}"
    assert publish["with"]["receipt"] == "${{ needs.build.outputs.receipt }}"
    runs = "\n".join(str(step.get("run", "")) for step in release["steps"])
    assert "--draft" in runs
    assert "--verify-tag" in runs
    (checkout,) = _uses(release, "actions/checkout@")
    assert checkout["with"]["fetch-depth"] == 0


_MOVES_A_REF = re.compile(r"git\s+tag\s+(-\S*\s+)*-f\b|--force\b|\s\+refs/|git\s+push\s+-f\b|--delete\b")


def test_no_step_moves_or_deletes_a_ref() -> None:
    texts = [str(step.get("run", "")) for job in _workflow()["jobs"].values() for step in job["steps"]]
    texts.append(_SCRIPT.read_text())
    assert len(texts) > 10
    assert not any(_MOVES_A_REF.search(text) for text in texts)
    assert _MOVES_A_REF.search('git tag -f -a "$TAG"')
    assert _MOVES_A_REF.search("git push origin --force main")


def test_xberg_actions_are_pinned_to_v1() -> None:
    for job in _workflow()["jobs"].values():
        for step in job["steps"]:
            uses = str(step.get("uses", ""))
            if uses.startswith("xberg-io/actions/"):
                assert uses.endswith("@v1"), uses


def test_action_dispatches_exactly_the_script_commands() -> None:
    action = yaml.safe_load(_ACTION.read_text())
    assert action["runs"]["using"] == "composite"
    (step,) = action["runs"]["steps"]
    arms = re.findall(r"^\s+([a-z]+)\)$", step["run"], flags=re.MULTILINE)
    assert arms == list(psr.COMMANDS)
    for command in psr.COMMANDS:
        assert f'"$script" {command} ' in step["run"] or f"args=({command} " in step["run"]
        psr.parser().parse_args(
            [
                command,
                *(
                    ["--zip", "z", "--receipt", "r", "--tag", "t", "--repository", "o/r"]
                    if command == "verify"
                    else ["--tag", "t"]
                    if command == "finalize"
                    else []
                ),
            ]
        )


def _order(job: dict, markers: list[str]) -> list[int]:
    texts = [json.dumps(step) for step in job["steps"]]
    return [next(index for index, text in enumerate(texts) if marker in text) for marker in markers]


def test_steps_run_in_dependency_order() -> None:
    jobs = _workflow()["jobs"]
    build = _order(
        jobs["build"],
        [
            '"command": "resolve"',
            '"command": "targets"',
            "build-swift-artifactbundle@",
            "install-alef@",
            '"command": "pin"',
            '"command": "verify"',
            "upload-artifact@",
            '"command": "finalize"',
        ],
    )
    assert build == sorted(build)
    finalize = _order(jobs["finalize"], ["download-artifact@", '"command": "verify"', '"command": "finalize"'])
    assert finalize == sorted(finalize)
    release = _order(
        jobs["release"], ["download-artifact@", "--verify-tag", "publish-swift-release@", "Attach the receipt"]
    )
    assert release == sorted(release)
    for name in ("build", "finalize"):
        (verify,) = [
            s for s in _uses(jobs[name], "xberg-io/actions/prepare-swift-release@") if s["with"]["command"] == "verify"
        ]
        prefix = "steps.paths" if name == "build" else "needs.build"
        assert verify["with"]["bundle-zip"] == f"${{{{ {prefix}.outputs.bundle-zip }}}}"
        assert verify["with"]["receipt"] == f"${{{{ {prefix}.outputs.receipt }}}}"
