#!/usr/bin/env python3
"""Write the ``~/.m2/settings.xml`` server entry that actions/setup-java wrote for ``server-id``.

The entry references ``MAVEN_USERNAME`` and ``MAVEN_PASSWORD`` as ``${env.*}``, so no credential is
written to disk. deploy.py passes its own settings file when both are set; this file is what Maven
reads otherwise.

Usage (GitHub Actions via env vars):
    INPUT_SERVER_ID=ossrh python3 server_settings.py
"""

import os
import re
import sys
from pathlib import Path

SERVER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

SETTINGS_TEMPLATE = """<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">
  <servers>
    <server>
      <id>{server_id}</id>
      <username>${{env.MAVEN_USERNAME}}</username>
      <password>${{env.MAVEN_PASSWORD}}</password>
    </server>
  </servers>
</settings>
"""


def render_settings(server_id: str) -> str:
    if not SERVER_ID_PATTERN.match(server_id):
        raise ValueError(f"server-id must be letters, digits, '.', '_' or '-', got {server_id!r}")
    return SETTINGS_TEMPLATE.format(server_id=server_id)


def write_settings(server_id: str, home: Path) -> Path:
    """Overwrite ``<home>/.m2/settings.xml``, as setup-java's default ``overwrite-settings: true`` did."""
    path = home / ".m2" / "settings.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_settings(server_id), encoding="utf-8")
    return path


def main() -> None:
    server_id = os.environ.get("INPUT_SERVER_ID", "ossrh")
    try:
        path = write_settings(server_id, Path.home())
    except ValueError as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
    print(f"Wrote the {server_id} server entry to {path}")


if __name__ == "__main__":
    main()
