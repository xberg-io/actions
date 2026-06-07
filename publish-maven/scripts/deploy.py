#!/usr/bin/env python3
"""Deploy a Maven project to Maven Central.

Usage (GitHub Actions via env vars):
    INPUT_POM_FILE=pom.xml INPUT_DRY_RUN=false python3 deploy.py
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


def build_mvn_args(
    pom_file: str,
    maven_profile: str,
    extra_args: str,
    settings_file: str | None = None,
) -> list[str]:
    """Build the Maven argument list from config values."""
    args: list[str] = [
        "-f",
        pom_file,
        "-P",
        maven_profile,
        "-B",
        "--no-transfer-progress",
    ]
    if settings_file:
        args.extend(["-s", settings_file])
    if extra_args.strip():
        args.extend(extra_args.split())
    return args


def is_already_published(log_content: str) -> bool:
    """Return True if the Maven log indicates the version already exists."""
    return bool(re.search(r"component with package url.*already exists", log_content, re.IGNORECASE))


def write_settings_xml(server_id: str, username: str, password: str, gpg_passphrase: str) -> str:
    """Write a settings.xml with literal, XML-escaped credentials.

    Bypasses the silent-empty-string failure mode where ``${env.MAVEN_USERNAME}``
    references in setup-java's settings.xml resolve to empty strings inside
    a subprocess, producing an empty Authorization header that Sonatype
    Central rejects with HTTP 403 (empty body).

    Every interpolated value is run through :func:`xml.sax.saxutils.escape`
    so that ``&``/``<``/``>`` in a token cannot break the document.
    """
    safe_id = xml_escape(server_id)
    safe_user = xml_escape(username)
    safe_pass = xml_escape(password)
    safe_gpg = xml_escape(gpg_passphrase)
    settings = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">\n'
        "  <servers>\n"
        "    <server>\n"
        f"      <id>{safe_id}</id>\n"
        f"      <username>{safe_user}</username>\n"
        f"      <password>{safe_pass}</password>\n"
        "    </server>\n"
        "  </servers>\n"
        "  <profiles>\n"
        "    <profile>\n"
        "      <id>gpg-passphrase</id>\n"
        "      <properties>\n"
        f"        <gpg.passphrase>{safe_gpg}</gpg.passphrase>\n"
        "      </properties>\n"
        "    </profile>\n"
        "  </profiles>\n"
        "  <activeProfiles>\n"
        "    <activeProfile>gpg-passphrase</activeProfile>\n"
        "  </activeProfiles>\n"
        "</settings>\n"
    )
    fd, path = tempfile.mkstemp(suffix="-settings.xml", text=True)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(settings)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    Path(path).chmod(0o600)
    return path


def main() -> None:
    pom_file = os.environ.get("INPUT_POM_FILE", "")
    maven_profile = os.environ.get("INPUT_MAVEN_PROFILE", "publish")
    extra_args = os.environ.get("INPUT_EXTRA_ARGS", "")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    server_id = os.environ.get("INPUT_SERVER_ID", "ossrh")
    username = os.environ.get("MAVEN_USERNAME", "")
    password = os.environ.get("MAVEN_PASSWORD", "")
    gpg_passphrase = os.environ.get("MAVEN_GPG_PASSPHRASE", "")

    if not pom_file:
        print("Error: INPUT_POM_FILE is required", file=sys.stderr)
        sys.exit(1)

    if not Path(pom_file).is_file():
        print(f"Error: POM file not found: {pom_file}", file=sys.stderr)
        sys.exit(1)

    settings_file: str | None = None
    if not dry_run and username and password:
        settings_file = write_settings_xml(server_id, username, password, gpg_passphrase)
        print(f"Wrote credentials settings.xml to {settings_file} (server-id={server_id})")
    elif not dry_run:
        print(
            "Warning: MAVEN_USERNAME or MAVEN_PASSWORD unset; falling back to default settings.xml",
            file=sys.stderr,
        )

    mvn_args = build_mvn_args(pom_file, maven_profile, extra_args, settings_file)

    if dry_run:
        print(f"[dry-run] mvn clean deploy {' '.join(mvn_args)}")
        subprocess.run(["mvn", "-f", pom_file, "clean", "verify", "-B", "--no-transfer-progress"], check=False)
        sys.exit(0)

    print("Deploying to Maven Central...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["mvn", "clean", "deploy", *mvn_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        log_content = result.stdout or ""
        Path(tmp_path).write_text(log_content)
        print(log_content, end="")

        if result.returncode == 0:
            print("Maven deploy completed successfully")
        elif is_already_published(log_content):
            print("Version already published to Maven Central, skipping")
            github_actions = os.environ.get("GITHUB_ACTIONS", "")
            if github_actions:
                print("::notice::Version already exists on Maven Central")
        else:
            print("Maven deploy failed", file=sys.stderr)
            sys.exit(1)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if settings_file:
            Path(settings_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
