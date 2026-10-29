#!/usr/bin/env bash
#MISE description="Provision machine preferences and install reviewed AI governance hooks"
#MISE depends=["governance:runtime"]
set -euo pipefail

python3 - <<'PYTHON'
import pathlib
import shutil
import subprocess
import tomllib

if shutil.which("ai-rulez") is None:
    raise SystemExit("Install the reviewed ai-rulez CLI before installing hooks")
preferences = pathlib.Path("poly.local.toml")
text = preferences.read_text() if preferences.exists() else ""
data = tomllib.loads(text)
if "hook_preferences" not in data:
    preferences.write_text(text.rstrip() + '\n\n[hook_preferences]\nchannels = ["system"]\n')
elif "system" not in data["hook_preferences"].get("channels", []):
    raise SystemExit("Add system to hook_preferences.channels in poly.local.toml")
subprocess.run(["poly", "hooks", "install"], check=True)
PYTHON
