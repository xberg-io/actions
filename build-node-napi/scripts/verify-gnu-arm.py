"""Validate the produced GNU ARM addon, then load it in the real host Node."""

import argparse
import json
import re
import struct
import subprocess
from pathlib import Path

GLIBC_FLOOR = (2, 17)
ELF_HEADER_BYTES = 64
ELF_SHARED_OBJECT = 3
ELF_AARCH64 = 183
NODE_API_CHECK = """
const assert = require('node:assert/strict');
const addon = require(require('node:path').resolve(process.argv[1]));
assert.equal(typeof addon.add, 'function');
assert.equal(addon.add(20, 22), 42);
console.log('Native addon add(20, 22) = 42');
"""


def verify_header(path: Path) -> None:
    """Check real ELF bytes rather than trusting a filename or tool description."""
    with path.open("rb") as artifact:
        header = artifact.read(ELF_HEADER_BYTES)
    if len(header) != ELF_HEADER_BYTES or header[:6] != b"\x7fELF\x02\x01":
        raise ValueError("expected a nonempty little-endian ELF64 addon")
    kind, machine = struct.unpack_from("<HH", header, 16)
    if kind != ELF_SHARED_OBJECT or machine != ELF_AARCH64:
        raise ValueError("expected an AArch64 ELF shared object")


def verify_versions(report: str) -> list[str]:
    """Reject missing, unknown and above-floor GLIBC version requirements."""
    symbols = set(re.findall(r"\bGLIBC_[A-Za-z0-9_.]+\b", report))
    if not symbols:
        raise ValueError("no GLIBC version-symbol requirements were inspected")
    versions = []
    for symbol in sorted(symbols):
        if not re.fullmatch(r"GLIBC_\d+(?:\.\d+)+", symbol):
            raise ValueError(f"unsupported GLIBC version requirement: {symbol}")
        version = tuple(int(part) for part in symbol.removeprefix("GLIBC_").split("."))
        if version > GLIBC_FLOOR:
            raise ValueError(f"GLIBC requirement exceeds 2.17: {symbol}")
        versions.append(symbol)
    return versions


def verify_api(path: Path) -> None:
    """The native loader and exact function result must both succeed."""
    subprocess.run(["node", "--eval", NODE_API_CHECK, str(path.resolve())], check=True, timeout=30)


def main() -> None:
    """Run the artifact checks without a fallback or ignored subprocess failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    verify_header(args.artifact)
    report = subprocess.run(
        ["readelf", "--version-info", "--wide", str(args.artifact)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    versions = verify_versions(report.stdout)
    print(json.dumps({"artifact": str(args.artifact), "architecture": "AArch64", "glibc_requirements": versions}))
    verify_api(args.artifact)


if __name__ == "__main__":
    main()
