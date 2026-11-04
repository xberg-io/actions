"""Publish a prepared Swift artifact bundle against an immutable release tag.

The release tag must already carry the final root manifest checksum. This script verifies the
tagged manifest, the exact bundle bytes and any existing release asset or legacy branch before it
mutates anything, then uploads the bundle only when the release lacks it and creates the legacy
branch only when it is absent. It never creates, moves or deletes a tag.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

CHECKSUM_FIELD = re.compile(r'checksum:\s*"([^"]*)"')
SHA256 = re.compile(r"[0-9a-f]{64}")
PLACEHOLDER = re.compile(r"__ALEF_[A-Z0-9_]+__")
RECEIPT_SCHEMA = 1


class PublishError(Exception):
    """A verification failure; raised before any mutation it guards."""


@dataclass(frozen=True)
class TagState:
    tag_object: str
    commit: str


@dataclass(frozen=True)
class Inputs:
    tag: str
    repository: str
    bundle_zip: Path | None
    manifest_path: str
    legacy_branch: str
    receipt: Path | None
    remote: str
    dry_run: bool


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise PublishError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result


def gh(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["gh", *arguments], capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise PublishError(f"gh {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote_refs(remote: str, *refs: str) -> dict[str, str]:
    listing = git("ls-remote", remote, *refs).stdout
    found: dict[str, str] = {}
    for line in listing.splitlines():
        object_id, _, name = line.partition("\t")
        found[name] = object_id
    return found


def read_tag_state(remote: str, tag: str) -> TagState:
    ref = f"refs/tags/{tag}"
    found = remote_refs(remote, ref, f"{ref}^{{}}")
    if ref not in found:
        raise PublishError(f"Release tag {tag} does not exist on {remote}; tag the finalized manifest first")
    return TagState(tag_object=found[ref], commit=found.get(f"{ref}^{{}}", found[ref]))


def fetch_tag_commit(remote: str, tag: str, state: TagState) -> None:
    git("fetch", "--quiet", "--no-tags", remote, f"refs/tags/{tag}")
    fetched = git("rev-parse", "FETCH_HEAD^{commit}").stdout.strip()
    if fetched != state.commit:
        raise PublishError(f"Release tag {tag} changed while it was being fetched")


def verify_manifest(manifest: str, inputs: Inputs, asset: str) -> str:
    placeholders = sorted(set(PLACEHOLDER.findall(manifest)))
    if placeholders:
        raise PublishError(
            f"{inputs.manifest_path} at {inputs.tag} still holds the placeholder {', '.join(placeholders)}: "
            "the tag was cut before the Swift checksum was finalized"
        )
    checksums = CHECKSUM_FIELD.findall(manifest)
    if len(checksums) != 1 or SHA256.fullmatch(checksums[0]) is None:
        raise PublishError(
            f"{inputs.manifest_path} at {inputs.tag} must hold exactly one SHA-256 checksum field, found {checksums}"
        )
    url = f"https://github.com/{inputs.repository}/releases/download/{inputs.tag}/{asset}"
    if manifest.count(f'"{url}"') != 1:
        raise PublishError(f"{inputs.manifest_path} at {inputs.tag} has no binaryTarget URL {url}")
    return checksums[0]


def verify_receipt(path: Path, inputs: Inputs, asset: str, checksum: str, commit: str) -> None:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise PublishError(f"Unsupported Swift receipt schema {receipt.get('schema')!r}")
    expectations = {"repository": inputs.repository, "archive": asset, "sha256": checksum}
    for field, expected in expectations.items():
        if receipt.get(field) != expected:
            raise PublishError(f"Swift receipt {field} {receipt.get(field)!r} differs from {expected!r}")
    source = str(receipt.get("source", ""))
    if re.fullmatch(r"[0-9a-f]{40}", source) is None:
        raise PublishError(f"Swift receipt source {source!r} is not a commit id")
    if git("merge-base", "--is-ancestor", source, commit, check=False).returncode != 0:
        raise PublishError(f"Swift receipt source {source} is not an ancestor of the tagged commit {commit}")


def release_asset_digest(inputs: Inputs, asset: str, workdir: Path) -> str | None:
    view = gh("release", "view", inputs.tag, "--repo", inputs.repository, "--json", "assets")
    names = [entry.get("name") for entry in json.loads(view.stdout).get("assets", [])]
    if asset not in names:
        return None
    gh("release", "download", inputs.tag, "--repo", inputs.repository, "--pattern", asset, "--dir", str(workdir))
    return sha256_file(workdir / asset)


def create_branch(remote: str, branch: str, commit: str) -> None:
    ref = f"refs/heads/{branch}"
    # ~keep An empty lease value means "the ref must not exist": a plain push would fast-forward an
    # ~keep existing ancestor branch, which is a move, not a create.
    git("push", "--quiet", f"--force-with-lease={ref}:", remote, f"{commit}:{ref}")


def read_inputs() -> Inputs:
    tag = os.environ.get("INPUT_TAG", "").strip()
    repository = os.environ.get("INPUT_REPOSITORY", "").strip() or os.environ.get("GITHUB_REPOSITORY", "")
    if not tag or not repository:
        raise PublishError("INPUT_TAG and INPUT_REPOSITORY (or GITHUB_REPOSITORY) are required")
    version = tag.removeprefix("v")
    bundle = os.environ.get("INPUT_BUNDLE_ZIP", "").strip()
    receipt = os.environ.get("INPUT_RECEIPT", "").strip()
    return Inputs(
        tag=tag,
        repository=repository,
        bundle_zip=Path(bundle) if bundle else None,
        manifest_path=os.environ.get("INPUT_MANIFEST_PATH", "").strip() or "Package.swift",
        legacy_branch=os.environ.get("INPUT_LEGACY_BRANCH", "").strip().replace("{version}", version),
        receipt=Path(receipt) if receipt else None,
        remote=os.environ.get("INPUT_REMOTE", "").strip() or "origin",
        dry_run=os.environ.get("INPUT_DRY_RUN", "false").strip().lower() == "true",
    )


def asset_name(inputs: Inputs, manifest: str) -> str:
    if inputs.bundle_zip is not None:
        return inputs.bundle_zip.name
    prefix = f"https://github.com/{inputs.repository}/releases/download/{inputs.tag}/"
    names = re.findall(rf'"{re.escape(prefix)}([^"/]+)"', manifest)
    if len(names) != 1:
        raise PublishError(f"{inputs.manifest_path} at {inputs.tag} has no binaryTarget URL under {prefix}")
    return names[0]


def publish(inputs: Inputs, workdir: Path) -> dict[str, str]:
    state = read_tag_state(inputs.remote, inputs.tag)
    fetch_tag_commit(inputs.remote, inputs.tag, state)
    manifest = git("show", f"{state.commit}:{inputs.manifest_path}").stdout
    asset = asset_name(inputs, manifest)
    checksum = verify_manifest(manifest, inputs, asset)

    if inputs.bundle_zip is not None:
        local = sha256_file(inputs.bundle_zip)
        if local != checksum:
            raise PublishError(
                f"{inputs.bundle_zip} has SHA-256 {local}, which does not match the checksum pinned in "
                f"{inputs.manifest_path} at {inputs.tag} ({checksum})"
            )
    if inputs.receipt is not None:
        verify_receipt(inputs.receipt, inputs, asset, checksum, state.commit)

    branch_exists = False
    if inputs.legacy_branch:
        existing = remote_refs(inputs.remote, f"refs/heads/{inputs.legacy_branch}").get(
            f"refs/heads/{inputs.legacy_branch}"
        )
        if existing is not None and existing != state.commit:
            raise PublishError(
                f"{inputs.legacy_branch} points at {existing}, not the tagged commit {state.commit}; "
                "reconcile it by hand, this action never moves it"
            )
        branch_exists = existing is not None

    released = release_asset_digest(inputs, asset, workdir)
    if released is not None and released != checksum:
        raise PublishError(
            f"Release {inputs.tag} already holds different bytes for {asset} ({released}); expected {checksum}"
        )
    if released is None and inputs.bundle_zip is None:
        raise PublishError(f"Release {inputs.tag} has no {asset} and no prepared Swift bundle was supplied")

    upload = released is None
    create = bool(inputs.legacy_branch) and not branch_exists
    if inputs.dry_run:
        print(f"[dry-run] verified {asset} ({checksum}) at {inputs.tag} -> {state.commit}")
        print(f"[dry-run] upload asset: {upload}; create {inputs.legacy_branch or 'no branch'}: {create}")
        upload = create = False
    else:
        if upload and inputs.bundle_zip is not None:
            gh("release", "upload", inputs.tag, str(inputs.bundle_zip), "--repo", inputs.repository)
        if create:
            create_branch(inputs.remote, inputs.legacy_branch, state.commit)

    if read_tag_state(inputs.remote, inputs.tag) != state:
        raise PublishError(f"Release tag {inputs.tag} moved during Swift publication")
    return {
        "checksum": checksum,
        "commit": state.commit,
        "tag-object": state.tag_object,
        "asset-uploaded": str(upload).lower(),
        "branch-created": str(create).lower(),
    }


def main() -> int:
    try:
        inputs = read_inputs()
        with tempfile.TemporaryDirectory() as workdir:
            outputs = publish(inputs, Path(workdir))
    except PublishError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in outputs.items())
    print(f"Published Swift bundle {outputs['checksum']} for {inputs.tag} at {outputs['commit']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
