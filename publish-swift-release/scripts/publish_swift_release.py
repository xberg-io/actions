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
REMOTE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


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


def sha256_file(path: Path, label: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError as error:
        raise PublishError(f"Cannot read {label} {path}: {error.strerror or error}") from error
    return digest.hexdigest()


def require_ref_name(kind: str, ref: str) -> None:
    if ref.startswith("-") or git("check-ref-format", ref, check=False).returncode != 0:
        raise PublishError(f"invalid {kind} {ref!r}")


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


def read_receipt(path: Path) -> dict:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PublishError(f"Cannot read Swift receipt {path}: {error.strerror or error}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PublishError(f"Swift receipt {path} is not valid JSON: {error}") from error
    if not isinstance(receipt, dict):
        raise PublishError(f"Swift receipt {path} must be a JSON object")
    return receipt


def verify_receipt(path: Path, inputs: Inputs, asset: str, checksum: str, commit: str) -> None:
    receipt = read_receipt(path)
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise PublishError(f"Unsupported Swift receipt schema {receipt.get('schema')!r} in {path}")
    expectations = {
        "repository": inputs.repository,
        "archive": asset,
        "sha256": checksum,
        "version": inputs.tag.removeprefix("v"),
    }
    for field, expected in expectations.items():
        if receipt.get(field) != expected:
            raise PublishError(f"Swift receipt {field} {receipt.get(field)!r} differs from {expected!r}")
    artifact_version = receipt.get("artifact_version")
    if not isinstance(artifact_version, str) or not artifact_version:
        raise PublishError(f"Swift receipt artifact_version {artifact_version!r} must be a non-empty string")
    triples = receipt.get("triples")
    if (
        not isinstance(triples, list)
        or not triples
        or not all(isinstance(triple, str) and triple for triple in triples)
        or len(set(triples)) != len(triples)
    ):
        raise PublishError(f"Swift receipt triples {triples!r} must be a non-empty list of distinct triples")
    source = str(receipt.get("source", ""))
    if re.fullmatch(r"[0-9a-f]{40}", source) is None:
        raise PublishError(f"Swift receipt source {source!r} is not a commit id")
    if git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        raise PublishError(
            "Checking the Swift receipt source needs full history (fetch-depth: 0); this checkout is shallow"
        )
    if git("merge-base", "--is-ancestor", source, commit, check=False).returncode != 0:
        raise PublishError(f"Swift receipt source {source} is not an ancestor of the tagged commit {commit}")


def release_asset_digest(inputs: Inputs, asset: str, workdir: Path) -> str | None:
    # ~keep gh resolves the tag to a published release and falls back to a draft (verified with gh 2.103).
    view = gh("release", "view", inputs.tag, "--repo", inputs.repository, "--json", "assets", check=False)
    if view.returncode != 0:
        raise PublishError(
            f"Release {inputs.tag} was not found in {inputs.repository} (published or draft); "
            f"create it before publishing the Swift bundle: {view.stderr.strip()}"
        )
    try:
        names = [entry.get("name") for entry in json.loads(view.stdout).get("assets", [])]
    except (json.JSONDecodeError, AttributeError) as error:
        raise PublishError(f"gh release view {inputs.tag} returned an unexpected payload: {error}") from error
    if asset not in names:
        return None
    gh("release", "download", inputs.tag, "--repo", inputs.repository, "--pattern", asset, "--dir", str(workdir))
    return sha256_file(workdir / asset, "downloaded release asset")


def create_branch(remote: str, branch: str, commit: str) -> None:
    ref = f"refs/heads/{branch}"
    # ~keep An empty lease value means "the ref must not exist": a plain push would fast-forward an
    # ~keep existing ancestor branch, which is a move, not a create.
    pushed = git("push", "--quiet", f"--force-with-lease={ref}:", remote, f"{commit}:{ref}", check=False)
    if pushed.returncode != 0:
        raise PublishError(
            f"{branch} was created concurrently or could not be pushed; nothing was uploaded, rerun to verify it: "
            f"{pushed.stderr.strip()}"
        )


def read_inputs() -> Inputs:
    tag = os.environ.get("INPUT_TAG", "").strip()
    repository = os.environ.get("INPUT_REPOSITORY", "").strip() or os.environ.get("GITHUB_REPOSITORY", "")
    if not tag or not repository:
        raise PublishError("INPUT_TAG and INPUT_REPOSITORY (or GITHUB_REPOSITORY) are required")
    version = tag.removeprefix("v")
    legacy_branch = os.environ.get("INPUT_LEGACY_BRANCH", "").strip().replace("{version}", version)
    remote = os.environ.get("INPUT_REMOTE", "").strip() or "origin"
    require_ref_name("tag", f"refs/tags/{tag}")
    if legacy_branch:
        require_ref_name("legacy branch", f"refs/heads/{legacy_branch}")
    if REMOTE_NAME.fullmatch(remote) is None:
        raise PublishError(f"invalid remote {remote!r}; pass a configured remote name")
    bundle = os.environ.get("INPUT_BUNDLE_ZIP", "").strip()
    receipt = os.environ.get("INPUT_RECEIPT", "").strip()
    return Inputs(
        tag=tag,
        repository=repository,
        bundle_zip=Path(bundle) if bundle else None,
        manifest_path=os.environ.get("INPUT_MANIFEST_PATH", "").strip() or "Package.swift",
        legacy_branch=legacy_branch,
        receipt=Path(receipt) if receipt else None,
        remote=remote,
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
        local = sha256_file(inputs.bundle_zip, "prepared Swift bundle")
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
        if read_tag_state(inputs.remote, inputs.tag) != state:
            raise PublishError(f"Release tag {inputs.tag} moved after verification; nothing was published")
        # ~keep The branch goes first: it is a pure create at the verified commit, so a failed upload
        # ~keep leaves state a rerun accepts (branch at the tag commit, asset absent) and completes.
        if create:
            create_branch(inputs.remote, inputs.legacy_branch, state.commit)
        if upload and inputs.bundle_zip is not None:
            uploaded = gh(
                "release", "upload", inputs.tag, str(inputs.bundle_zip), "--repo", inputs.repository, check=False
            )
            if uploaded.returncode != 0:
                done = f"{inputs.legacy_branch} created, " if create else ""
                raise PublishError(f"{done}asset upload failed; rerun to retry it: {uploaded.stderr.strip()}")

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
    verb = "Verified (dry run)" if inputs.dry_run else "Published"
    print(f"{verb} Swift bundle {outputs['checksum']} for {inputs.tag} at {outputs['commit']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
