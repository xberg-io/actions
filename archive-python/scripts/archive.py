"""Archive Python distributions and render a hash-pinned simple repository."""

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import tarfile
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any, BinaryIO

MANIFEST_PREFIX = "python-archive-"


def digest_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def normalize(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("Invalid project name")
    return re.sub(r"[-_.]+", "-", name).lower()


def metadata(path: Path) -> dict[str, str]:
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError("Expected exactly one wheel METADATA")
            payload = archive.read(names[0])
    else:
        with tarfile.open(path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.name.count("/") == 1 and member.name.endswith("/PKG-INFO") and member.isfile()
            ]
            if len(members) != 1:
                raise ValueError("Expected exactly one root sdist PKG-INFO")
            stream = archive.extractfile(members[0])
            if stream is None:
                raise ValueError("Missing sdist metadata")
            payload = stream.read()
    parsed = BytesParser().parsebytes(payload)
    return {
        "name": normalize(str(parsed["Name"] or "")),
        "version": str(parsed["Version"] or ""),
        "requires_python": str(parsed["Requires-Python"] or ""),
    }


def download_digest(url: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def verify_asset(path: Path, url: str) -> None:
    with path.open("rb") as stream:
        expected = digest_stream(stream)
    if download_digest(url) != (expected, path.stat().st_size):
        raise ValueError(f"Public archive digest mismatch: {path.name}")


def validate_row(row: dict[str, Any]) -> str:
    name = normalize(row["name"])
    filename = row["filename"]
    if Path(filename).name != filename or not filename.endswith((".whl", ".tar.gz")):
        raise ValueError("Invalid distribution filename")
    url = urllib.parse.urlsplit(row["url"])
    if url.scheme != "https" or url.netloc != "github.com" or "/releases/download/" not in url.path:
        raise ValueError("Expected a public GitHub release download URL")
    if urllib.parse.unquote(url.path.rsplit("/", 1)[1]) != filename or url.fragment or url.query:
        raise ValueError("Download URL does not identify the distribution")
    if not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]) or row["size"] <= 0:
        raise ValueError("Invalid artifact digest or size")
    return name


def write_index(rows: list[dict[str, Any]], destination: Path) -> None:
    if not rows:
        raise ValueError("Cannot publish an empty Python archive")
    packages: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        name = validate_row(row)
        files = packages.setdefault(name, {})
        previous = files.setdefault(row["filename"], row)
        if previous != row:
            raise ValueError(f"Conflicting archive records: {row['filename']}")
    simple = destination / "simple"
    if simple.exists():
        raise ValueError("Index output must be fresh to prevent stale package links")
    simple.mkdir(parents=True)
    (destination / ".nojekyll").touch()
    links = [f'<a href="{name}/">{name}</a>' for name in sorted(packages)]
    (simple / "index.html").write_text(page(links), encoding="utf-8")
    for name, files in sorted(packages.items()):
        directory = simple / name
        directory.mkdir(exist_ok=True)
        links = []
        for filename, row in sorted(files.items()):
            url = html.escape(row["url"] + "#sha256=" + row["sha256"], quote=True)
            requires = html.escape(row.get("requires_python", ""), quote=True)
            links.append(f'<a href="{url}" data-requires-python="{requires}">{html.escape(filename)}</a>')
        (directory / "index.html").write_text(page(links), encoding="utf-8")


def page(links: list[str]) -> str:
    return (
        '<!DOCTYPE html>\n<html><head><meta name="pypi:repository-version" content="1.0"></head><body>\n'
        + "\n".join(links)
        + "\n</body></html>\n"
    )


def gh(*args: str) -> Any:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def release_rows(repository: str) -> list[dict[str, Any]]:
    pages = gh("api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100")
    rows = []
    for release in [release for batch in pages for release in batch]:
        if release["draft"]:
            continue
        assets = {asset["name"]: asset for asset in release["assets"]}
        for filename, asset in assets.items():
            if not filename.startswith(MANIFEST_PREFIX) or not filename.endswith(".json"):
                continue
            with urllib.request.urlopen(asset["browser_download_url"], timeout=30) as response:  # noqa: S310
                manifest = json.load(response)
            if not manifest["files"]:
                raise ValueError("Empty archive manifest")
            for row in manifest["files"]:
                validate_row(row)
                remote = assets.get(row["filename"])
                if remote is None or remote["size"] != row["size"] or remote["browser_download_url"] != row["url"]:
                    raise ValueError("Archive manifest references a missing or changed release asset")
                if remote.get("digest") and remote["digest"] != "sha256:" + row["sha256"]:
                    raise ValueError("Archive manifest does not match GitHub asset digest")
                if not remote.get("digest") and download_digest(row["url"]) != (row["sha256"], row["size"]):
                    raise ValueError("Archive digest could not be verified")
                rows.append(row)
    return rows


def archive_distributions(directory: Path, repository: str, tag: str, expected_version: str) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not tag:
        raise ValueError("Invalid repository or empty release tag")
    release = gh("api", f"repos/{repository}/releases/tags/{urllib.parse.quote(tag, safe='')}")
    if release["draft"]:
        raise ValueError("Archives require a public release; draft assets cannot serve installers")
    files = sorted(path for path in directory.iterdir() if path.name.endswith((".whl", ".tar.gz")))
    if not files:
        raise ValueError("No distributions to archive")
    rows = []
    assets = {asset["name"]: asset for asset in release["assets"]}
    for path in files:
        info = metadata(path)
        if not expected_version or info["version"] != expected_version.removeprefix("v"):
            raise ValueError(f"Unexpected distribution version: {path.name}")
        prefix = f"{info['name'].replace('-', '_')}-{info['version']}"
        if path.name.endswith(".whl"):
            filename_name, filename_version = path.name.split("-")[:2]
        else:
            filename_name, filename_version = path.name.removesuffix(".tar.gz").rsplit("-", 1)
        if normalize(filename_name) != info["name"] or filename_version != info["version"]:
            raise ValueError(f"Distribution filename differs from metadata: {prefix}")
        with path.open("rb") as stream:
            digest = digest_stream(stream)
        url = f"https://github.com/{repository}/releases/download/{urllib.parse.quote(tag, safe='')}/{path.name}"
        if path.name not in assets:
            subprocess.run(["gh", "release", "upload", tag, str(path), "--repo", repository], check=True)
        verify_asset(path, url)
        rows.append(dict(info, filename=path.name, sha256=digest, size=path.stat().st_size, url=url))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--packages-dir", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--expected-version")
    parser.add_argument("--existing-manifests-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    previous = release_rows(args.repository)
    if args.existing_manifests_dir:
        manifests = sorted(args.existing_manifests_dir.glob("*.json"))
        if not manifests:
            raise ValueError("Existing manifest directory is empty")
        for manifest in manifests:
            previous.extend(json.loads(manifest.read_text())["files"])
    if args.index_only:
        write_index(previous, args.output_dir)
        if output := os.environ.get("GITHUB_OUTPUT"):
            with Path(output).open("a", encoding="utf-8") as stream:
                stream.write(f"index-dir={args.output_dir}\nfile-count={len(previous)}\n")
        print(f"Indexed {len(previous)} verified archived distributions")
        return
    if not args.packages_dir or not args.tag or not args.expected_version:
        parser.error("Archive mode requires --packages-dir, --tag, and --expected-version")
    current = archive_distributions(args.packages_dir, args.repository, args.tag, args.expected_version)
    write_index(previous + current, args.output_dir)
    for name in sorted({row["name"] for row in current}):
        manifest = args.output_dir / f"{MANIFEST_PREFIX}{name}.json"
        selected = [
            row
            for row in previous + current
            if row["name"] == name
            and row["url"].startswith(
                f"https://github.com/{args.repository}/releases/download/{urllib.parse.quote(args.tag, safe='')}/"
            )
        ]
        unique = {row["filename"]: row for row in selected}
        manifest.write_text(json.dumps({"files": list(unique.values())}, indent=2) + "\n")
        subprocess.run(
            ["gh", "release", "upload", args.tag, str(manifest), "--repo", args.repository, "--clobber"], check=True
        )
    receipt = args.output_dir / "python-archive.json"
    receipt.write_text(json.dumps({"files": current}, indent=2) + "\n")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"index-dir={args.output_dir}\nmanifest={receipt}\nfile-count={len(current)}\n")
    print(f"Verified {len(current)} archived distributions; indexed {len(previous + current)} records")


if __name__ == "__main__":
    main()
