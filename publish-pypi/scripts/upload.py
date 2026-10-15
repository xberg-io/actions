"""Publish primarily to PyPI, allowing a verified archive only for storage quota errors."""

import hashlib
import os
import re
import subprocess
import tarfile
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path


class IndexLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append((str(values["href"]), str(values.get("data-requires-python") or "")))


def storage_quota_failure(message: str) -> bool:
    return bool(
        re.search(r"\b400\b", message)
        and re.search(r"project size too large|total project size", message, re.IGNORECASE)
    )


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def requires_python(path: Path) -> str:
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError("Invalid wheel metadata")
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
    return str(BytesParser().parsebytes(payload)["Requires-Python"] or "")


def verify_index(files: list[Path], index_url: str) -> None:
    if not files or urllib.parse.urlsplit(index_url).scheme != "https":
        raise ValueError("Fallback requires distributions and a public HTTPS simple index")
    for path in files:
        project = path.name.split("-")[0] if path.name.endswith(".whl") else path.name.rsplit("-", 1)[0]
        name = re.sub(r"[-_.]+", "-", project).lower()
        with urllib.request.urlopen(index_url.rstrip("/") + "/" + name + "/", timeout=30) as response:  # noqa: S310
            parser = IndexLinks()
            parser.feed(response.read().decode())
        expected = digest_file(path)
        links = [
            link
            for link, _ in parser.links
            if urllib.parse.unquote(urllib.parse.urlsplit(link).path.rsplit("/", 1)[-1]) == path.name
        ]
        if len(links) != 1 or urllib.parse.urlsplit(links[0]).fragment != "sha256=" + expected:
            raise ValueError(f"Fallback index has no unique matching hash for {path.name}")
        link = urllib.parse.urlsplit(links[0])
        if link.scheme != "https" or link.netloc != "github.com" or "/releases/download/" not in link.path:
            raise ValueError("Fallback artifact must be a public GitHub Release asset")
        if next(value for url, value in parser.links if url == links[0]) != requires_python(path):
            raise ValueError("Fallback Requires-Python differs from distribution metadata")
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(urllib.parse.urlunsplit(link._replace(fragment="")), timeout=120) as response:  # noqa: S310
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if digest.hexdigest() != expected or size != path.stat().st_size:
            raise ValueError(f"Fallback artifact digest differs: {path.name}")


def main() -> None:
    directory = Path(os.environ["PACKAGES_DIR"])
    files = sorted(path for path in directory.iterdir() if path.name.endswith((".whl", ".tar.gz")))
    if not files:
        raise ValueError("No distributions to publish")
    upload_url = os.environ["UV_PUBLISH_URL"]
    base = re.sub(r"^([a-z]+://)upload\.", r"\1", upload_url.rstrip("/").removesuffix("/legacy"))
    result = subprocess.run(
        [
            "uv",
            "publish",
            "--trusted-publishing",
            "automatic",
            "--publish-url",
            upload_url,
            "--check-url",
            base + "/simple/",
            *map(str, files),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    print(result.stdout, end="")
    print(result.stderr, end="")
    fallback = False
    if result.returncode:
        index = os.environ.get("INPUT_FALLBACK_INDEX_URL", "")
        if not index or not storage_quota_failure(result.stdout + result.stderr):
            raise SystemExit(result.returncode)
        verify_index(files, index)
        fallback = True
        print(f"::warning::PyPI project storage quota exceeded; all {len(files)} distributions are verified at {index}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"published={str(not fallback).lower()}\nfallback={str(fallback).lower()}\n")


if __name__ == "__main__":
    main()
