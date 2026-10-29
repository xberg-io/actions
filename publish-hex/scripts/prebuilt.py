"""Validate and upload the immutable prebuilt Hex archive through its public API."""

import base64
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:  # noqa: ARG002, PLR0917 — stdlib override signature
        return None


def send(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=120) as response:
            if response.status != 201:
                raise ValueError("Hex did not confirm creation of the uploaded release")
            return response.read()
    except urllib.error.HTTPError as error:
        raise ValueError(f"Hex request failed with HTTP {error.code}; publication was not confirmed") from None


def metadata_bytes(payload: bytes) -> bytes:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            members = archive.getmembers()
            expected = {"VERSION", "CHECKSUM", "metadata.config", "contents.tar.gz"}
            if len(members) != len(expected) or {member.name for member in members} != expected:
                raise ValueError("Hex archive must contain exactly the four standard envelope entries")
            if any(not member.isfile() for member in members):
                raise ValueError("Hex envelope entries must be regular files")
            files = {}
            for member in members:
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Unreadable Hex archive entry")
                files[member.name] = stream.read()
    except (tarfile.TarError, EOFError) as error:
        raise ValueError("Hex artifact is not a readable tar archive") from error
    if files["VERSION"] != b"3":
        raise ValueError("Only Hex archive format version 3 is supported")
    checksum = hashlib.sha256(files["VERSION"] + files["metadata.config"] + files["contents.tar.gz"]).hexdigest()
    if files["CHECKSUM"].decode("ascii").strip().lower() != checksum:
        raise ValueError("Hex archive checksum does not match its final contents")
    return files["metadata.config"]


def read_metadata(payload: bytes) -> tuple[str, str]:
    # ~keep :file.consult parses Erlang terms as data. Evaluating package source here would run
    # project build hooks and lose the prebuilt-artifact boundary.
    script = """
    {:ok, terms} = :file.consult(String.to_charlist(hd(System.argv())))
    for key <- ["name", "version"] do
      [value] = for {^key, value} <- terms, do: value
      true = is_binary(value)
      IO.puts(Base.encode64(value))
    end
    """
    with tempfile.TemporaryDirectory(prefix="hex-metadata-") as directory:
        path = Path(directory) / "metadata.config"
        path.write_bytes(payload)
        result = subprocess.run(["elixir", "-e", script, str(path)], capture_output=True, check=False, timeout=60)
    lines = result.stdout.splitlines()
    if result.returncode or len(lines) != 2:
        raise ValueError("Hex metadata must contain one binary name and version")
    try:
        name, version = (base64.b64decode(line, validate=True).decode("utf-8") for line in lines)
    except ValueError as error:
        raise ValueError("Hex metadata name/version are invalid") from error
    return name, version


def publish_verified(
    payload: bytes,
    expected_name: str,
    expected_version: str,
    notices: Mapping[str, bytes],
    api_key: str,
    *,
    replace: bool,
    verifier: Callable[[bytes, str, Mapping[str, bytes]], None],
    metadata_reader: Callable[[bytes], tuple[str, str]] = read_metadata,
    transport: Callable[[urllib.request.Request], bytes] = send,
    dry_run: bool = False,
) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", expected_name) or not expected_version:
        raise ValueError("Guarded Hex publication requires expected-package and expected-version")
    name, version = metadata_reader(metadata_bytes(payload))
    if (name, version) != (expected_name, expected_version):
        raise ValueError("The prebuilt Hex artifact name/version differs from the expected release")
    verifier(payload, "hex", notices)
    if dry_run:
        print("Verified the final Hex archive; dry run uploads nothing")
        return
    if not api_key:
        raise ValueError("HEX_API_KEY is required for publication")
    if any(ord(character) <= 32 or ord(character) >= 127 for character in api_key):
        raise ValueError("HEX_API_KEY contains invalid HTTP header characters")
    query = urllib.parse.urlencode({"replace": str(replace).lower()})
    url = f"https://hex.pm/api/packages/{urllib.parse.quote(name, safe='')}/releases?{query}"
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/octet-stream",
            "User-Agent": "xberg-io/actions publish-hex",
        },
    )
    transport(request)
    print("Verified prebuilt Hex archive published successfully")


def main() -> None:
    required = [name.strip() for name in os.environ.get("INPUT_REQUIRED_NOTICE_FILES", "").splitlines() if name.strip()]
    if not required:
        raise ValueError("At least one required-notice-files entry is required for guarded publication")
    path = Path(os.environ.get("INPUT_TARBALL_PATH", ""))
    if not path.is_file():
        raise ValueError("Guarded Hex publication requires a prebuilt tarball-path")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "verify-package-contents" / "scripts"))
    from notices import load_notices, verify_archive_bytes

    notices = load_notices(Path(os.environ.get("INPUT_CANONICAL_ROOT", ".")), required)
    expected = os.environ.get("INPUT_EXPECTED_VERSION", "").strip().removeprefix("v").split("-dryrun-", 1)[0]
    publish_verified(
        path.read_bytes(),
        os.environ.get("INPUT_EXPECTED_PACKAGE", ""),
        expected,
        notices,
        os.environ.get("HEX_API_KEY", ""),
        replace=os.environ.get("INPUT_REPLACE", "true") == "true",
        verifier=verify_archive_bytes,
        dry_run=os.environ.get("INPUT_DRY_RUN", "false") == "true",
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
