"""Decode MIT-licensed libheif examples through the explicitly selected system ABI."""

import argparse
import ctypes as c
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ARCHIVE_URL = "https://github.com/strukturag/libheif/releases/download/v1.23.7/libheif-1.23.7.tar.gz"
ARCHIVE_SHA256 = "f7483e818503ea6224c8863e4a56ac02c7089021a98472c811c12aa19faf2475"
FIXTURES = {
    "example.heic": (718114, "7f8b363e4936c0666a25f64f3a92fda10bd8e5453be4592530b65a55dd98f3f2"),
    "example.avif": (113604, "54a0dc31d02b6f5d9d4b66027d4787861b7af15ffd8fab8eab963d10c5411469"),
}


class HeifError(c.Structure):
    """Native libheif error ABI."""

    _fields_ = [("code", c.c_int), ("subcode", c.c_int), ("message", c.c_char_p)]


def bind_library(path: Path, version: str) -> c.CDLL:
    """Bind only APIs available at the supported 1.19 runtime floor."""
    library = c.CDLL(str(path))
    pointer = c.c_void_p
    signatures = {
        "heif_get_version": (c.c_char_p, []),
        "heif_context_alloc": (pointer, []),
        "heif_context_free": (None, [pointer]),
        "heif_context_read_from_file": (HeifError, [pointer, c.c_char_p, pointer]),
        "heif_context_get_primary_image_handle": (HeifError, [pointer, c.POINTER(pointer)]),
        "heif_decode_image": (HeifError, [pointer, c.POINTER(pointer), c.c_int, c.c_int, pointer]),
        "heif_image_get_width": (c.c_int, [pointer, c.c_int]),
        "heif_image_get_height": (c.c_int, [pointer, c.c_int]),
        "heif_image_get_plane_readonly": (pointer, [pointer, c.c_int, c.POINTER(c.c_int)]),
        "heif_image_release": (None, [pointer]),
        "heif_image_handle_release": (None, [pointer]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(library, name)
        function.restype = result
        function.argtypes = arguments
    if not (library.heif_get_version().decode() == version):
        raise RuntimeError("wrong selected runtime")
    return library


def materialize_examples(destination: Path) -> None:
    """Fetch and verify upstream MIT examples, preserving their license."""
    with urllib.request.urlopen(ARCHIVE_URL, timeout=120) as response:
        archive = response.read()
    if not (hashlib.sha256(archive).hexdigest() == ARCHIVE_SHA256):
        raise RuntimeError("source archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for name, (size, digest) in FIXTURES.items():
            stream = source.extractfile("libheif-1.23.7/examples/" + name)
            if not (stream is not None):
                raise RuntimeError("native runtime qualification failed")
            data = stream.read()
            if not (len(data) == size):
                raise RuntimeError(name)
            if not (hashlib.sha256(data).hexdigest() == digest):
                raise RuntimeError(name)
            (destination / name).write_bytes(data)
        license_stream = source.extractfile("libheif-1.23.7/examples/COPYING")
        if not (license_stream is not None):
            raise RuntimeError("native runtime qualification failed")
        (destination / "COPYING").write_bytes(license_stream.read())


def checked(error: HeifError) -> None:
    """Reject any native decoder error."""
    if not (error.code == 0):
        raise RuntimeError((error.code, error.subcode, error.message))


def header_dimensions(path: Path) -> tuple[int, int]:
    """Check expected dimensions against BMFF ispe boxes independently of libheif."""
    data = path.read_bytes()
    expected = (1280, 854) if path.suffix == ".heic" else (800, 533)
    sizes = set()
    offset = 0
    while (offset := data.find(b"ispe", offset)) >= 0:
        if offset >= 4 and int.from_bytes(data[offset - 4 : offset], "big") == 20:
            width = int.from_bytes(data[offset + 8 : offset + 12], "big")
            height = int.from_bytes(data[offset + 12 : offset + 16], "big")
            sizes.add((width, height))
        offset += 4
    if expected not in sizes:
        raise RuntimeError(f"expected dimensions absent from verified BMFF input: {sizes}")
    return expected


def decode(library: c.CDLL, path: Path) -> dict[str, object]:
    """Read actual decoded RGBA dimensions, stride and nonconstant pixels."""
    context = library.heif_context_alloc()
    if not (context):
        raise RuntimeError("native runtime qualification failed")
    handle, image = c.c_void_p(), c.c_void_p()
    try:
        checked(library.heif_context_read_from_file(context, str(path).encode(), None))
        checked(library.heif_context_get_primary_image_handle(context, c.byref(handle)))
        checked(library.heif_decode_image(handle, c.byref(image), 1, 11, None))
        width, height = library.heif_image_get_width(image, 10), library.heif_image_get_height(image, 10)
        expected = header_dimensions(path)
        if not ((width, height) == expected):
            raise RuntimeError("unexpected official example dimensions")
        stride = c.c_int()
        plane = library.heif_image_get_plane_readonly(image, 10, c.byref(stride))
        if not (plane):
            raise RuntimeError("native runtime qualification failed")
        if not (stride.value >= width * 4):
            raise RuntimeError("native runtime qualification failed")
        pixels = b"".join(c.string_at(plane + row * stride.value, width * 4) for row in range(height))
        if not (len(pixels) == width * height * 4):
            raise RuntimeError("native runtime qualification failed")
        if not (len(set(pixels)) > 1):
            raise RuntimeError("native runtime qualification failed")
        return {
            "input": path.name,
            "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "width": width,
            "height": height,
            "rgba_bytes": len(pixels),
            "rgba_sha256": hashlib.sha256(pixels).hexdigest(),
        }
    finally:
        if image:
            library.heif_image_release(image)
        if handle:
            library.heif_image_handle_release(handle)
        library.heif_context_free(context)


def check_codec_prefix(prefix: Path) -> list[str]:
    """Prove manylinux loaded both provisioned shared codec libraries."""
    loaded = {
        Path(line.split()[-1]).resolve()
        for line in Path("/proc/self/maps").read_text().splitlines()
        if "/" in line.split()[-1]
    }
    selected = []
    for name, function_name, expected in (
        ("libde265.so", "de265_get_version", "1.1.3"),
        ("libaom.so", "aom_codec_version_str", "3.15.2"),
    ):
        matches = {path for path in loaded if path.name.startswith(name)}
        if not (len(matches) == 1):
            raise RuntimeError(f"expected one loaded {name}: {matches}")
        path = matches.pop()
        if not (path.parent == prefix.resolve()):
            raise RuntimeError(f"{name} loaded outside provisioned prefix: {path}")
        native = c.CDLL(str(path))
        version_function = getattr(native, function_name)
        version_function.restype = c.c_char_p
        version_function.argtypes = []
        version = version_function().decode().removeprefix("v")
        if version != expected:
            raise RuntimeError(f"{name} reports {version}, expected {expected}")
        selected.append(str(path))
    return selected


def main() -> None:
    """Qualify one selected system runtime and reject malformed input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--version", choices=("1.19.8", "1.23.7"), required=True)
    parser.add_argument("--require-codec-prefix", type=Path)
    args = parser.parse_args()
    path = args.library.resolve(strict=True)
    library = bind_library(path, args.version)
    with tempfile.TemporaryDirectory(prefix="heif-runtime-") as temporary:
        root = Path(temporary)
        materialize_examples(root)
        rows = [decode(library, root / name) for name in FIXTURES]
        if not (len(rows) == 2):
            raise RuntimeError("native runtime qualification failed")
        codecs = check_codec_prefix(args.require_codec_prefix) if args.require_codec_prefix else []
        invalid = root / "invalid.heic"
        invalid.write_bytes(b"not a HEIF image")
        context = library.heif_context_alloc()
        if not (context):
            raise RuntimeError("native runtime qualification failed")
        try:
            if not (library.heif_context_read_from_file(context, str(invalid).encode(), None).code != 0):
                raise RuntimeError("native runtime qualification failed")
        finally:
            library.heif_context_free(context)
        sys.stdout.write(
            json.dumps(
                {
                    "library": str(path),
                    "library_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "runtime": args.version,
                    "expected_decodes": 2,
                    "actual_decodes": len(rows),
                    "invalid_input_rejected": True,
                    "loaded_codecs": codecs,
                    "rows": rows,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
