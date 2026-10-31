"""Keep macOS extension linker options out of cross-target Cargo invocations."""

import os
import subprocess
import sys


def without_dynamic_lookup(flags: list[str]) -> list[str]:
    groups: list[tuple[str | None, list[str]]] = []
    index = 0
    while index < len(flags):
        argument = flags[index]
        if argument == "-C" and index + 1 < len(flags):
            groups.append((flags[index + 1], flags[index : index + 2]))
            index += 2
        else:
            groups.append((argument[2:] if argument.startswith("-C") else None, [argument]))
            index += 1
    result: list[str] = []
    index = 0
    while index < len(groups):
        option, original = groups[index]
        if option == "link-arg=-Wl,-undefined,dynamic_lookup":
            index += 1
            continue
        if (
            option == "link-arg=-undefined"
            and index + 1 < len(groups)
            and groups[index + 1][0] == "link-arg=dynamic_lookup"
        ):
            index += 2
            continue
        result.extend(original)
        index += 1
    return result


def main() -> None:
    target, *command = sys.argv[1:]
    if not target.endswith("-apple-darwin"):
        # Cargo gives encoded flags precedence, including an explicitly empty value. ~keep
        if "CARGO_ENCODED_RUSTFLAGS" in os.environ:
            encoded = os.environ["CARGO_ENCODED_RUSTFLAGS"]
            flags = encoded.split("\x1f") if encoded else []
        else:
            flags = os.environ.get("RUSTFLAGS", "").split()
        filtered = without_dynamic_lookup(flags)
        if filtered != flags:
            os.environ["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(filtered)
    raise SystemExit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()
