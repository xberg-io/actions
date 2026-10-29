"""Stage and verify explicitly configured artifact-bundle notice files."""

import argparse
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Notice:
    relative_path: Path
    contents: bytes


def notice_paths(configured: str) -> list[Path]:
    names = [line.strip() for line in configured.splitlines() if line.strip()]
    if not names:
        raise ValueError("additional license configuration contains no file paths")
    keys: list[str] = []
    for name in names:
        if "\\" in name or ":" in name or any(part in {"", ".", ".."} for part in name.split("/")):
            raise ValueError(f"invalid relative additional license path: {name!r}")
        key = name.casefold()
        if any(key == prior or key.startswith(f"{prior}/") or prior.startswith(f"{key}/") for prior in keys):
            raise ValueError(f"additional license path collision: {name!r}")
        keys.append(key)
    return [Path(name) for name in names]


def resolve_notices(workspace: Path, configured: str) -> list[Notice]:
    paths = notice_paths(configured)
    root = workspace.resolve(strict=True)
    notices: list[Notice] = []
    for relative_path in paths:
        source = (root / relative_path).resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError(f"additional license {relative_path} escapes workspace")
        if not source.is_file():
            raise ValueError(f"additional license {relative_path} is not a regular file")
        contents = source.read_bytes()
        if not contents:
            raise ValueError(f"additional license {relative_path} is empty")
        notices.append(Notice(relative_path, contents))
    return notices


def check_destination(bundle: Path, relative_path: Path) -> None:
    current = bundle
    for index, part in enumerate(relative_path.parts):
        matches = [entry for entry in current.iterdir() if entry.name.casefold() == part.casefold()]
        if not matches:
            return
        if len(matches) != 1 or matches[0].name != part:
            raise ValueError(f"additional license destination collision: {relative_path}")
        current = matches[0]
        if current.is_symlink() or index == len(relative_path.parts) - 1 or not current.is_dir():
            raise ValueError(f"additional license destination collision: {relative_path}")


def stage_notices(notices: list[Notice], bundle: Path) -> None:
    root = bundle.resolve(strict=True)
    for notice in notices:
        check_destination(root, notice.relative_path)
    for notice in notices:
        destination = root / notice.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(notice.contents)


def verify_notices(notices: list[Notice], bundle: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        for notice in notices:
            member = f"{bundle.name}/{notice.relative_path.as_posix()}"
            count = names.count(member)
            if count != 1:
                raise ValueError(f"expected exactly one ZIP entry for additional license {member}, found {count}")
            if zipped.read(member) != notice.contents:
                raise ValueError(f"additional license ZIP contents differ: {member}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "stage", "verify"])
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    notices = resolve_notices(args.workspace, os.environ.get("INPUT_ADDITIONAL_LICENSE_FILES", ""))
    if args.command == "stage":
        if args.bundle is None:
            parser.error("stage requires --bundle")
        stage_notices(notices, args.bundle)
    elif args.command == "verify":
        if args.bundle is None or args.archive is None:
            parser.error("verify requires --bundle and --archive")
        verify_notices(notices, args.bundle, args.archive)
        print(f"Verified {len(notices)} additional license files in {args.archive}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"additional license error: {error}", file=sys.stderr)
        sys.exit(1)
