import os
import subprocess
import sys
from pathlib import Path


def run(*arguments: str) -> None:
    subprocess.run(arguments, check=True, env={**os.environ, "AI_RULEZ_STRICT": "1"})


def config_directories(root: Path) -> list[Path]:
    primary = os.environ.get("CONFIG_DIRECTORY", ".ai-rulez").strip()
    if not primary:
        raise ValueError("CONFIG_DIRECTORY must not be empty")
    supplied = [primary]
    supplied.extend(os.environ.get("ADDITIONAL_CONFIG_DIRECTORIES", "").splitlines())
    directories = [(root / value.strip()).resolve() for value in supplied if value.strip()]
    expected = int(os.environ.get("EXPECTED_CONFIG_COUNT", "1"))
    if expected < 1 or len(directories) != expected:
        raise ValueError(f"expected configs={expected}; supplied configs={len(directories)}; count must be positive")
    if len(set(directories)) != expected:
        raise ValueError("configuration directories must be unique")
    for directory in directories:
        if not directory.resolve().is_relative_to(root) or not (directory / "config.toml").is_file():
            raise ValueError(f"configuration directory missing or outside repository: {directory}")
    return directories


def verify_plugin(directory: Path, root: Path) -> None:
    enabled = os.environ.get("VERIFY_PLUGIN", "false")
    if enabled not in {"true", "false"}:
        raise ValueError("VERIFY_PLUGIN must be true or false")
    if enabled == "false":
        return
    run("ai-rulez", "-C", str(directory), "verify", "--plugin")
    for variable, default in (
        ("VERSION_SYNC_SCRIPT", "scripts/sync_plugin_version.py"),
        ("PUBLIC_SKILLS_CHECK_SCRIPT", "scripts/sync_public_skills.py"),
    ):
        script = root / os.environ.get(variable, default)
        if not script.is_file():
            raise ValueError(f"required plugin check script missing: {script}")
        run("python3", str(script), "--check")


def check_tracked_outputs() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"]).split(b"\0")
    count = len([path for path in tracked if path])
    if count == 0:
        raise ValueError("no tracked files examined")
    run("git", "diff", "--exit-code", "HEAD", "--")
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"])
    if untracked:
        raise ValueError(f"generation left untracked files: {os.fsdecode(untracked).replace(chr(0), ', ')}")
    return count


def main() -> None:
    root = Path.cwd().resolve()
    git_root = Path(os.fsdecode(subprocess.check_output(["git", "rev-parse", "--show-toplevel"])).strip()).resolve()
    if git_root != root:
        raise ValueError(f"working directory must be repository root: {git_root}")
    directories = config_directories(root)
    print(f"expected configs={len(directories)}; supplied configs={len(directories)}", flush=True)
    verify_plugin(directories[0], root)
    for directory in directories:
        run("ai-rulez", "-C", str(directory), "migrate", "okf", "--check")
    for directory in directories:
        run("ai-rulez", "-C", str(directory), "validate", "--strict", "--no-local")
    for index, directory in enumerate(directories):
        if index == 0 or (directory / "ai-rulez.lock").is_file():
            run("ai-rulez", "-C", str(directory), "lock", "--check")
    run("ai-rulez", "-C", str(directories[0]), "generate", "--no-local", "--strict-config")
    run("ai-rulez", "-C", str(directories[0]), "generate", "--check", "--no-local", "--strict-config")
    count = check_tracked_outputs()
    print(f"expected configs={len(directories)}; validated configs={len(directories)}; tracked files checked={count}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"AI-Rulez validation failed: {error}", file=sys.stderr)
        sys.exit(1)
