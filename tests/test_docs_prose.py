"""Execute the reusable prose step with controlled CLI boundaries."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def prose_step():
    workflow = yaml.safe_load((ROOT / ".github/workflows/reusable-docs-deploy.yml").read_text())
    return workflow, next(step for step in workflow["jobs"]["build"]["steps"] if step.get("name") == "Lint prose")


@pytest.mark.parametrize("directory", [".", "docs site", "docs-$(touch INJECTED)"])
@pytest.mark.parametrize("install_status,lint_status", [(0, 0), (23, 0), (0, 19)])
def test_prose_install_and_lint_preserve_root_and_failures(tmp_path, directory, install_status, lint_status):
    workflow, step = prose_step()
    inputs = workflow.get("on", workflow.get(True))["workflow_call"]["inputs"]
    assert inputs["prose-dependency-directory"]["default"] == "."
    assert step["env"]["PROSE_DEPENDENCY_DIRECTORY"] == "${{ inputs.prose-dependency-directory }}"
    assert step["env"]["DOCS_DIRECTORY"] == "${{ inputs.working-directory }}"
    assert "${{" not in step["run"]
    binaries = tmp_path / "bin"
    binaries.mkdir()
    dependency = tmp_path / directory / "node_modules/.bin"
    dependency.mkdir(parents=True)
    recorder = "#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\nwith open(os.environ['CALLS'],'a') as f: f.write(json.dumps([Path(sys.argv[0]).name,os.getcwd(),sys.argv[1:]])+'\\n')\nsys.exit(int(os.environ['INSTALL_STATUS' if Path(sys.argv[0]).name=='pnpm' else 'LINT_STATUS']))\n"
    for executable in [binaries / "pnpm", dependency / "textlint"]:
        executable.write_text(recorder)
        executable.chmod(0o700)
    log = tmp_path / "calls.jsonl"
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "CALLS": str(log),
            "PROSE_DEPENDENCY_DIRECTORY": directory,
            "DOCS_DIRECTORY": "docs content",
            "INSTALL_STATUS": str(install_status),
            "LINT_STATUS": str(lint_status),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (install_status or lint_status), result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls[0] == ["pnpm", str(tmp_path), ["--dir", directory, "install", "--frozen-lockfile"]]
    assert len(calls) == (1 if install_status else 2)
    if not install_status:
        assert calls[1] == [
            "textlint",
            str(tmp_path),
            [
                "--rules-base-directory",
                str(tmp_path / directory / "node_modules"),
                "docs content/src/content/docs/**/*.{md,mdx}",
            ],
        ]
    assert not (tmp_path / "INJECTED").exists()
