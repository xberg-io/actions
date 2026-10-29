"""Compare canonical notice bytes inside distribution archives without extracting them."""

from __future__ import annotations

import fnmatch
import importlib
import io
import re
import stat
import tarfile
import unicodedata
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence


class NoticeVerificationError(ValueError):
    """A source notice or packaged notice cannot be verified unambiguously."""


def _path(name: str) -> str:
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise NoticeVerificationError(f"unsafe archive path: {name!r}")
    parts = PurePosixPath(name).parts
    if ".." in parts:
        raise NoticeVerificationError(f"unsafe archive path alias: {name!r}")
    return PurePosixPath(name).as_posix()


def _required_names(names: Sequence[str]) -> list[str]:
    if isinstance(names, (str, bytes)) or not names:
        raise NoticeVerificationError("required notice inventory is empty or is not a sequence of file names")
    normalized = []
    for name in names:
        if not isinstance(name, str) or not name.strip() or name != _path(name) or name == ".":
            raise NoticeVerificationError(f"invalid required notice file name: {name!r}")
        normalized.append(name)
    if len({name.casefold() for name in normalized}) != len(normalized):
        raise NoticeVerificationError("duplicate or case-aliased required notice file names")
    return normalized


def load_notices(canonical_root: str | Path, required_names: Sequence[str]) -> dict[str, bytes]:
    """Load a nonempty, unambiguous set of regular canonical notice files."""
    names = _required_names(required_names)
    if not str(canonical_root).strip():
        raise NoticeVerificationError("canonical source root must not be empty")
    root = Path(canonical_root).resolve()
    notices = {}
    for name in names:
        source = root / name
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(root):
            raise NoticeVerificationError(f"canonical notice is not a regular file under {root}: {name}")
        try:
            content = source.read_bytes()
        except OSError as error:
            raise NoticeVerificationError(f"cannot read canonical notice {name}: {error}") from error
        if not content:
            raise NoticeVerificationError(f"empty canonical notice: {name}")
        notices[name] = content
    return notices


class _Member(NamedTuple):
    regular: bool
    directory: bool
    archive: tarfile.TarFile | zipfile.ZipFile
    entry: tarfile.TarInfo | zipfile.ZipInfo

    def read(self) -> bytes:
        if not self.regular:
            raise NoticeVerificationError("archive notice or container must be a regular file")
        if isinstance(self.archive, zipfile.ZipFile) and isinstance(self.entry, zipfile.ZipInfo):
            return self.archive.read(self.entry)
        if not isinstance(self.archive, tarfile.TarFile) or not isinstance(self.entry, tarfile.TarInfo):
            raise NoticeVerificationError("archive member has an incompatible container")
        stream = self.archive.extractfile(self.entry)
        if stream is None:
            raise NoticeVerificationError("unreadable regular archive member")
        with stream:
            return stream.read()


@contextmanager
def _members(payload: bytes, zip_container: bool = False) -> Iterator[dict[str, _Member]]:
    with (
        zipfile.ZipFile(io.BytesIO(payload))
        if zip_container
        else tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive
    ):
        entries = archive.infolist() if isinstance(archive, zipfile.ZipFile) else archive.getmembers()
        index = {}
        for entry in entries:
            if isinstance(entry, zipfile.ZipInfo):
                name = entry.filename
                mode = stat.S_IFMT(entry.external_attr >> 16)
                directory = entry.is_dir() or mode == stat.S_IFDIR or bool(entry.external_attr & 0x10)
                regular = not directory and mode in (0, stat.S_IFREG)
            else:
                name, regular, directory = entry.name, entry.isfile(), entry.isdir()
            path = _path(name)
            if path in index:
                raise NoticeVerificationError(f"duplicate effective archive path or alias: {name}")
            index[path] = _Member(regular, directory, archive, entry)
        yield index


def _notice_key(path: str) -> str:
    return unicodedata.normalize("NFC", "/".join(part.rstrip(" .") for part in path.split("/"))).casefold()


def _member(index: Mapping[str, _Member], expected: str) -> _Member:
    aliases = [name for name in index if _notice_key(name) == _notice_key(expected)]
    if aliases != [expected]:
        if aliases:
            raise NoticeVerificationError(f"notice path alias or duplicate for {expected}: {aliases}")
        raise NoticeVerificationError(f"missing packaged notice or container: {expected}")
    for parent in PurePosixPath(expected).parents:
        ancestor = index.get(parent.as_posix())
        if ancestor is not None and not ancestor.directory:
            raise NoticeVerificationError(f"notice ancestor is not a regular directory: {parent}")
    entry = index[expected]
    if not entry.regular:
        raise NoticeVerificationError(f"packaged notice or container is not a regular file: {expected}")
    return entry


def _compare(index: Mapping[str, _Member], prefix: str, notices: Mapping[str, bytes]) -> None:
    for name, expected in notices.items():
        path = (PurePosixPath(prefix) / name).as_posix()
        if _member(index, path).read() != expected:
            raise NoticeVerificationError(f"{path} differs from canonical {name}")


def _glob_matches(path: str, pattern: str) -> bool:
    parts, patterns = path.split("/"), pattern.split("/")
    if pattern == "**":
        return True
    if patterns[0] == "**":
        return _glob_matches(path, "/".join(patterns[1:])) or (
            len(parts) > 1 and _glob_matches("/".join(parts[1:]), pattern)
        )
    if len(patterns) == 1:
        return len(parts) == 1 and fnmatch.fnmatchcase(parts[0], patterns[0])
    return (
        len(parts) > 1
        and fnmatch.fnmatchcase(parts[0], patterns[0])
        and _glob_matches("/".join(parts[1:]), "/".join(patterns[1:]))
    )


def _verify_sdist(index: Mapping[str, _Member], notices: Mapping[str, bytes]) -> None:
    try:
        tomllib = importlib.import_module("tomllib")
    except ImportError as error:
        raise NoticeVerificationError("sdist notice verification requires Python 3.11 or newer") from error
    roots = {PurePosixPath(name).parts[0] for name in index if name != "."}
    if len(roots) != 1:
        raise NoticeVerificationError(f"sdist must have one distribution root, found {sorted(roots)}")
    root = roots.pop()
    _member(index, f"{root}/PKG-INFO")
    project = tomllib.loads(_member(index, f"{root}/pyproject.toml").read().decode("utf-8"))
    declarations = project.get("project", {}).get("license-files")
    if (
        not isinstance(declarations, list)
        or not declarations
        or not all(isinstance(item, str) for item in declarations)
    ):
        raise NoticeVerificationError("distribution pyproject must declare a nonempty project.license-files list")
    for pattern in declarations:
        _path(pattern)
    for name in notices:
        if not any(_glob_matches(name, pattern) for pattern in declarations):
            raise NoticeVerificationError(f"distribution project.license-files does not declare {name}")
    _compare(index, root, notices)


def _verify_wheel(index: Mapping[str, _Member], notices: Mapping[str, bytes]) -> None:
    metadata = [name for name in index if len(PurePosixPath(name).parts) == 2 and name.endswith(".dist-info/METADATA")]
    if len(metadata) != 1:
        raise NoticeVerificationError(f"wheel must contain one distribution METADATA file, found {len(metadata)}")
    _member(index, metadata[0])
    _compare(index, f"{PurePosixPath(metadata[0]).parent}/licenses", notices)


def verify_archive_bytes(payload: bytes, artifact_format: str, notices: Mapping[str, bytes]) -> None:
    """Verify required notice bytes; raise NoticeVerificationError on any ambiguity or failure.

    Supported formats are wheel, sdist, gem, jar, nuget (also nupkg), and hex.
    JAR notices live under META-INF; gem and Hex notice payloads are nested tarballs.
    """
    _required_names(list(notices))
    if not all(isinstance(content, bytes) and content for content in notices.values()):
        raise NoticeVerificationError("canonical notice mapping contains empty or non-byte content")
    artifact_format = "nuget" if artifact_format == "nupkg" else artifact_format
    if artifact_format not in {"wheel", "sdist", "gem", "jar", "nuget", "hex"}:
        raise NoticeVerificationError(f"unsupported notice artifact format: {artifact_format!r}")
    try:
        with _members(payload, artifact_format in {"wheel", "jar", "nuget"}) as index:
            if artifact_format in {"gem", "hex"}:
                container = "data.tar.gz" if artifact_format == "gem" else "contents.tar.gz"
                with _members(_member(index, container).read()) as nested:
                    _compare(nested, ".", notices)
            elif artifact_format == "sdist":
                _verify_sdist(index, notices)
            elif artifact_format == "wheel":
                _verify_wheel(index, notices)
            else:
                _compare(index, "META-INF" if artifact_format == "jar" else ".", notices)
    except (OSError, UnicodeError, ValueError, tarfile.TarError, zipfile.BadZipFile, RuntimeError) as error:
        raise NoticeVerificationError(str(error)) from error
