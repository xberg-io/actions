"""Pin a prepared Swift bundle's checksum into Package.swift and create the release tag exactly once.

SwiftPM resolves `from:`/`exact:` requirements to the core `vX.Y.Z` tag, so the tagged root
Package.swift must already carry the final checksum. These commands run before the tag exists:

- `resolve` derives the tag from Cargo.toml and requires it absent and the source at the branch tip.
- `targets` derives the Apple deployment targets from Package.swift's `platforms`.
- `pin` runs alef's version sync and keeps only the root manifest it rewrote (alef#884).
- `verify` proves the working tree is the source with only its checksum value replaced.
- `finalize` pushes that commit and an annotated tag without force, atomically, and recognises
  every partial state a failed run leaves by content; any other state of the branch or tag fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

COMMANDS = ("resolve", "targets", "pin", "verify", "finalize")
# ~keep The same field shape publish-swift-release accepts, so verify cannot pass a manifest it later rejects.
CHECKSUM_FIELD = re.compile(r'(checksum:\s*")([^"]*)(")')
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
PLACEHOLDER = re.compile(r"__ALEF_[A-Z0-9_]+__")
TAG = re.compile(r"v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?")
RECEIPT_SCHEMA = 1


class ReleaseError(Exception):
    """The prepared release is inconsistent; nothing may be pushed."""


def git(repo: Path, *arguments: str) -> str:
    return git_bytes(repo, *arguments).decode("utf-8").strip()


def git_bytes(repo: Path, *arguments: str) -> bytes:
    result = subprocess.run(["git", *arguments], cwd=repo, capture_output=True, check=False)
    if result.returncode != 0:
        raise ReleaseError(f"git {' '.join(arguments)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def git_ok(repo: Path, *arguments: str) -> bool:
    return subprocess.run(["git", *arguments], cwd=repo, capture_output=True, check=False).returncode == 0


def tree_mode(repo: Path, revision: str, path: str) -> str:
    entry = git(repo, "ls-tree", revision, "--", path).split()
    if not entry:
        raise ReleaseError(f"{path} does not exist at {revision}")
    return entry[0]


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


# ~keep Resolve


def cargo_version(path: Path) -> str:
    try:
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ReleaseError(f"cannot read the version from {path}: {error}") from error
    version = manifest.get("workspace", {}).get("package", {}).get("version") or manifest.get("package", {}).get(
        "version"
    )
    if not isinstance(version, str) or not version:
        raise ReleaseError(f"{path} declares no [workspace.package] or [package] version")
    return version


def remote_commit(repo: Path, remote: str, ref: str) -> str | None:
    """Resolve a remote ref to the commit it peels to, or None when it does not exist."""
    # ~keep ls-remote prints the peeled `^{}` line only for a pattern, never for the exact ref.
    lines = git(repo, "ls-remote", remote, f"{ref}*").splitlines()
    found = {name: sha for sha, name in (line.split("\t", 1) for line in lines if line)}
    return found.get(f"{ref}^{{}}") or found.get(ref)


def resolve(repo: Path, *, tag: str, cargo_toml: str, remote: str, branch: str) -> dict[str, str]:
    version = cargo_version(repo / cargo_toml)
    expected = f"v{version}"
    if tag and tag != expected:
        raise ReleaseError(f"tag {tag} does not match the {cargo_toml} version {version}; expected {expected}")
    if TAG.fullmatch(expected) is None:
        raise ReleaseError(f"{expected!r} is not a vX.Y.Z release tag")
    if remote_commit(repo, remote, f"refs/tags/{expected}") is not None:
        raise ReleaseError(
            f"{expected} already exists. A release tag is never moved: bump the version, or rerun only the "
            "failed jobs of the run that created it"
        )
    source = git(repo, "rev-parse", "HEAD")
    tip = remote_commit(repo, remote, f"refs/heads/{branch}")
    if tip != source:
        raise ReleaseError(f"{branch} is at {tip}, not the checked-out source {source}; prepare from the branch tip")
    return {"tag": expected, "version": version, "source": source}


# ~keep Deployment targets

PLATFORM = re.compile(r'\.(macOS|iOS)\(\s*(?:\.v(\d+)(?:_(\d+))?|"(\d+(?:\.\d+)*)")\s*\)')


def normalize(version: str) -> tuple[int, ...]:
    if re.fullmatch(r"\d+(\.\d+)*", version) is None:
        raise ReleaseError(f"{version!r} is not a deployment target such as 26.0")
    parts = [int(part) for part in version.split(".")]
    while len(parts) > 2 and parts[-1] == 0:
        parts.pop()
    return tuple(parts + [0] * (2 - len(parts)))


def render(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def manifest_platforms(manifest: str) -> dict[str, tuple[int, ...]]:
    found: dict[str, list[tuple[int, ...]]] = {}
    for platform, major, minor, literal in PLATFORM.findall(manifest):
        version = literal or f"{major}.{minor or 0}"
        found.setdefault(platform, []).append(normalize(version))
    duplicated = sorted(platform for platform, versions in found.items() if len(set(versions)) > 1)
    if duplicated:
        raise ReleaseError(f"Package.swift declares conflicting minimums for {', '.join(duplicated)}")
    return {platform: versions[0] for platform, versions in found.items()}


def deployment_targets(manifest: str, *, macos: str, ios: str) -> dict[str, str]:
    """The macOS target must equal the manifest's; an iOS input may lower it, never raise it."""
    platforms = manifest_platforms(manifest)
    if "macOS" not in platforms:
        raise ReleaseError("Package.swift declares no .macOS minimum to build the archive for")
    declared_macos = platforms["macOS"]
    if macos and normalize(macos) != declared_macos:
        raise ReleaseError(
            f"macOS deployment target {macos} disagrees with Package.swift's .macOS minimum {render(declared_macos)}"
        )
    targets = {"macos": render(declared_macos)}
    declared_ios = platforms.get("iOS")
    if ios:
        if declared_ios is not None and normalize(ios) > declared_ios:
            raise ReleaseError(
                f"iOS deployment target {ios} is above Package.swift's .iOS minimum {render(declared_ios)}"
            )
        targets["ios"] = render(normalize(ios))
    elif declared_ios is not None:
        targets["ios"] = render(declared_ios)
    return targets


# ~keep Pin


def changed_paths(repo: Path, bundle_dir: str) -> tuple[list[str], list[str]]:
    """Tracked paths that differ from HEAD and untracked paths outside the bundle directory."""
    tracked = [path for path in git_bytes(repo, "diff", "--name-only", "-z", "HEAD").decode().split("\0") if path]
    untracked = [
        path
        for path in git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
        if path and not PurePosixPath(path).is_relative_to(bundle_dir)
    ]
    return sorted(tracked), sorted(untracked)


def pin(repo: Path, *, manifest: str, bundle_dir: str, alef: str) -> list[str]:
    """Run alef's version sync on a clean tree and put back everything but the root manifest."""
    tracked, untracked = changed_paths(repo, bundle_dir)
    if tracked or untracked:
        raise ReleaseError(f"version sync needs a clean tree; changed before it ran: {tracked + untracked}")
    before = (repo / manifest).read_bytes()
    result = subprocess.run([alef, "sync-versions", "--regen"], cwd=repo, check=False)
    if result.returncode != 0:
        raise ReleaseError(f"alef sync-versions --regen exited {result.returncode}")
    if (repo / manifest).read_bytes() == before:
        raise ReleaseError(
            f"alef sync-versions did not change {manifest}: it pins a prepared checksum only with the ZIP and "
            f"its receipt in {bundle_dir} on a clean tree whose HEAD is the receipt's source"
        )
    tracked, untracked = changed_paths(repo, bundle_dir)
    tracked = [path for path in tracked if path != manifest]
    restored = sorted(tracked + untracked)
    if restored:
        print(f"::warning::alef sync-versions re-rendered files besides {manifest}; restoring them: {restored}")
        if tracked:
            git(repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", *tracked)
        for path in untracked:
            (repo / path).unlink()
    return restored


# ~keep Verify


def load_receipt(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReleaseError(f"cannot read the Swift receipt {path}: {error}") from error
    if not isinstance(data, dict):
        raise ReleaseError(f"Swift receipt {path.name} is not a JSON object")
    return data


def bundle_census(zip_path: Path) -> dict[str, object]:
    """Check the ZIP is one well-formed artifact bundle; return its triples and artifact version."""
    root = zip_path.name.removesuffix(".zip")
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ReleaseError(f"{zip_path.name} contains duplicate entries")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts or path.parts[0] != root:
                    raise ReleaseError(f"{zip_path.name} contains an unsafe or foreign entry {name!r}")
            if archive.testzip() is not None:
                raise ReleaseError(f"{zip_path.name} fails its CRC check")
            info = json.loads(archive.read(f"{root}/info.json"))
            artifacts = info.get("artifacts", {})
            if len(artifacts) != 1:
                raise ReleaseError(f"{zip_path.name} must declare exactly one artifact, found {sorted(artifacts)}")
            artifact = next(iter(artifacts.values()))
            triples: list[str] = []
            for variant in artifact.get("variants", []):
                member = f"{root}/{variant.get('path', '')}"
                if member not in names or archive.getinfo(member).file_size <= 8:
                    raise ReleaseError(f"{zip_path.name} lacks the native library {member}")
                triples.extend(variant.get("supportedTriples", []))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise ReleaseError(f"{zip_path.name} is not a valid artifact bundle: {error}") from error
    if not triples or len(triples) != len(set(triples)):
        raise ReleaseError(f"{zip_path.name} declares no or duplicate triples: {triples}")
    return {"triples": sorted(triples), "artifact_version": artifact.get("version", "")}


def verify_receipt(receipt: dict[str, object], expected: dict[str, object]) -> None:
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ReleaseError(f"Swift receipt {key} is {receipt.get(key)!r}, expected {value!r}")


def verify_manifest(source: bytes, pinned: bytes, checksum: str, url: str) -> None:
    """Accept `pinned` only if it is `source` byte for byte with its one checksum value replaced."""
    text = pinned.decode("utf-8")
    placeholders = sorted(set(PLACEHOLDER.findall(text)))
    if placeholders:
        raise ReleaseError(f"pinned Package.swift still holds the placeholder {', '.join(placeholders)}")
    fields = CHECKSUM_FIELD.findall(text)
    if len(fields) != 1:
        raise ReleaseError(f"pinned Package.swift must hold exactly one checksum field, found {len(fields)}")
    if fields[0][1] != checksum:
        raise ReleaseError(f"pinned checksum {fields[0][1]!r} is not the bundle's SHA-256 {checksum}")
    if text.count(f'"{url}"') != 1:
        raise ReleaseError(f"pinned Package.swift does not name the release asset URL {url} exactly once")
    original = source.decode("utf-8")
    tokens = CHECKSUM_FIELD.findall(original)
    if len(tokens) != 1 or not (PLACEHOLDER.fullmatch(tokens[0][1]) or SHA256.fullmatch(tokens[0][1])):
        raise ReleaseError("source Package.swift must hold exactly one placeholder or literal checksum field")
    expected = CHECKSUM_FIELD.sub(lambda match: f"{match[1]}{checksum}{match[3]}", original, count=1)
    if text != expected:
        raise ReleaseError("pinned Package.swift changes more than the checksum value (bytes or line endings)")


def verify(
    repo: Path,
    *,
    zip_path: Path,
    receipt_path: Path,
    tag: str,
    repository: str,
    manifest: str,
    expected_triples: list[str] | None,
) -> str:
    """Check the working tree holds exactly the checksum pin for this bundle; return the checksum."""
    checksum = digest(zip_path)
    census = bundle_census(zip_path)
    head = git(repo, "rev-parse", "HEAD")
    verify_receipt(
        load_receipt(receipt_path),
        {
            "schema": RECEIPT_SCHEMA,
            "repository": repository,
            "source": head,
            "version": tag.removeprefix("v"),
            "archive": zip_path.name,
            "sha256": checksum,
            **census,
        },
    )
    if expected_triples and sorted(set(expected_triples)) != census["triples"]:
        raise ReleaseError(f"bundle triples {census['triples']} differ from the expected {sorted(expected_triples)}")
    url = f"https://github.com/{repository}/releases/download/{tag}/{zip_path.name}"
    verify_manifest(git_bytes(repo, "show", f"HEAD:{manifest}"), (repo / manifest).read_bytes(), checksum, url)
    bundle_dir = zip_path.resolve().parent.relative_to(repo.resolve()).as_posix()
    tracked, untracked = changed_paths(repo, bundle_dir)
    if tracked != [manifest] or untracked:
        raise ReleaseError(f"the pin may change only {manifest}; changed: {tracked}, untracked: {untracked}")
    source_mode = tree_mode(repo, "HEAD", manifest)
    executable = os.access(repo / manifest, os.X_OK)
    if source_mode != ("100755" if executable else "100644"):
        raise ReleaseError(f"the pin changed the file mode of {manifest} (was {source_mode})")
    return checksum


# ~keep Finalize


def is_pin_of(repo: Path, remote: str, ref: str, *, commit: str, source: str, manifest: str, pinned: bytes) -> bool:
    """True when `commit` is the single child of `source` that changes only `manifest` to `pinned`."""
    git(repo, "fetch", "--quiet", "--no-tags", remote, ref)
    parents = git(repo, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    if parents != [source]:
        return False
    changed = git(repo, "diff", "--no-renames", "--name-only", source, commit).splitlines()
    if changed != [manifest]:
        return False
    same_mode = tree_mode(repo, source, manifest) == tree_mode(repo, commit, manifest)
    return same_mode and git_bytes(repo, "show", f"{commit}:{manifest}") == pinned


def contains(repo: Path, remote: str, branch: str, tip: str, commit: str) -> bool:
    git(repo, "fetch", "--quiet", "--no-tags", remote, f"refs/heads/{branch}")
    return git_ok(repo, "merge-base", "--is-ancestor", commit, tip)


def push(repo: Path, remote: str, *refspecs: str) -> None:
    # ~keep Never forced: the server rejects a non-fast-forward branch update and an existing tag,
    # ~keep and --atomic applies all refspecs or none.
    git(repo, "push", "--quiet", "--atomic", remote, *refspecs)


def finalize(repo: Path, *, tag: str, remote: str, branch: str, manifest: str, dry_run: bool) -> dict[str, str]:
    """Commit the verified pin onto `branch` and create `tag` at it, neither ever moved."""
    if TAG.fullmatch(tag) is None:
        raise ReleaseError(f"{tag!r} is not a vX.Y.Z release tag")
    source = git(repo, "rev-parse", "HEAD")
    pinned = (repo / manifest).read_bytes()
    tag_ref, branch_ref = f"refs/tags/{tag}", f"refs/heads/{branch}"
    tagged = remote_commit(repo, remote, tag_ref)
    tip = remote_commit(repo, remote, branch_ref)
    pin_of = {"source": source, "manifest": manifest, "pinned": pinned}

    if tagged is not None:
        if not is_pin_of(repo, remote, tag_ref, commit=tagged, **pin_of):
            raise ReleaseError(f"{tag} already exists at {tagged}, which is not the checksum pin of {source}")
        if tip is not None and (tip == tagged or contains(repo, remote, branch, tip, tagged)):
            return {"commit": tagged, "tag-created": "false", "branch-updated": "false"}
        if tip != source:
            raise ReleaseError(f"{tag} is the pin of {source}, but {branch} moved to {tip} without it")
        if not dry_run:
            push(repo, remote, f"{tagged}:{branch_ref}")
        return {"commit": tagged, "tag-created": "false", "branch-updated": str(not dry_run).lower()}

    if tip == source:
        git(repo, "add", "--", manifest)
        git(repo, "commit", "--quiet", "-m", f"chore(release): pin the Swift artifact bundle checksum for {tag}")
        commit, refspecs = git(repo, "rev-parse", "HEAD"), [f"HEAD:{branch_ref}"]
    elif tip is not None and is_pin_of(repo, remote, branch_ref, commit=tip, **pin_of):
        commit, refspecs = tip, []
    else:
        raise ReleaseError(
            f"{branch} moved from the prepared source {source} to {tip}; prepare the release again from the new tip"
        )
    if dry_run:
        print(
            f"[dry-run] would push {commit} to {branch_ref} and create {tag_ref}"
            if refspecs
            else f"[dry-run] would create {tag_ref} at {commit}"
        )
        return {"commit": commit, "tag-created": "false", "branch-updated": "false"}
    git(repo, "tag", "-a", tag, "-m", tag, commit)
    push(repo, remote, *refspecs, tag_ref)
    if remote_commit(repo, remote, tag_ref) != commit:
        raise ReleaseError(f"{tag} does not peel to {commit} after the push")
    return {"commit": commit, "tag-created": "true", "branch-updated": str(bool(refspecs)).lower()}


# ~keep CLI


def write_outputs(values: dict[str, str], env_values: dict[str, str] | None = None) -> None:
    for key, value in {**values, **(env_values or {})}.items():
        if "\n" in value or "\r" in value:
            raise ReleaseError(f"refusing to write a multi-line value for {key}")
    for key, value in values.items():
        print(f"{key}={value}")
    for variable, path in (("GITHUB_OUTPUT", values), ("GITHUB_ENV", env_values or {})):
        target = os.environ.get(variable)
        if target and path:
            with Path(target).open("a", encoding="utf-8") as handle:
                handle.writelines(f"{key}={value}\n" for key, value in path.items())


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    parsers = {command: sub.add_parser(command) for command in COMMANDS}
    resolve_parser = parsers["resolve"]
    resolve_parser.add_argument("--tag", default="")
    resolve_parser.add_argument("--cargo-toml", default="Cargo.toml")
    resolve_parser.add_argument("--remote", default="origin")
    resolve_parser.add_argument("--branch", default="main")
    targets_parser = parsers["targets"]
    targets_parser.add_argument("--manifest", default="Package.swift")
    targets_parser.add_argument("--macos", default="")
    targets_parser.add_argument("--ios", default="")
    pin_parser = parsers["pin"]
    pin_parser.add_argument("--manifest", default="Package.swift")
    pin_parser.add_argument("--bundle-dir", default="dist/swift-artifactbundle")
    pin_parser.add_argument("--alef", default="alef")
    verify_parser = parsers["verify"]
    verify_parser.add_argument("--zip", type=Path, required=True)
    verify_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser.add_argument("--tag", required=True)
    verify_parser.add_argument("--repository", required=True)
    verify_parser.add_argument("--manifest", default="Package.swift")
    verify_parser.add_argument("--expected-triples", default="")
    finalize_parser = parsers["finalize"]
    finalize_parser.add_argument("--tag", required=True)
    finalize_parser.add_argument("--remote", default="origin")
    finalize_parser.add_argument("--branch", default="main")
    finalize_parser.add_argument("--manifest", default="Package.swift")
    finalize_parser.add_argument("--dry-run", action="store_true")
    return root


def run(arguments: argparse.Namespace, repo: Path) -> None:
    if arguments.command == "resolve":
        write_outputs(
            resolve(
                repo,
                tag=arguments.tag,
                cargo_toml=arguments.cargo_toml,
                remote=arguments.remote,
                branch=arguments.branch,
            )
        )
    elif arguments.command == "targets":
        targets = deployment_targets(
            (repo / arguments.manifest).read_text(encoding="utf-8"), macos=arguments.macos, ios=arguments.ios
        )
        exported = {"MACOSX_DEPLOYMENT_TARGET": targets["macos"]}
        if "ios" in targets:
            exported["IPHONEOS_DEPLOYMENT_TARGET"] = targets["ios"]
        write_outputs(targets, exported)
    elif arguments.command == "pin":
        restored = pin(repo, manifest=arguments.manifest, bundle_dir=arguments.bundle_dir, alef=arguments.alef)
        write_outputs({"restored": " ".join(restored)})
    elif arguments.command == "verify":
        triples = [triple for triple in re.split(r"[\s,]+", arguments.expected_triples) if triple]
        checksum = verify(
            repo,
            zip_path=arguments.zip,
            receipt_path=arguments.receipt,
            tag=arguments.tag,
            repository=arguments.repository,
            manifest=arguments.manifest,
            expected_triples=triples,
        )
        write_outputs({"checksum": checksum})
    else:
        write_outputs(
            finalize(
                repo,
                tag=arguments.tag,
                remote=arguments.remote,
                branch=arguments.branch,
                manifest=arguments.manifest,
                dry_run=arguments.dry_run,
            )
        )


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        run(arguments, Path.cwd())
    except (ReleaseError, OSError, UnicodeDecodeError) as error:
        print(f"::error::Swift release preparation: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
