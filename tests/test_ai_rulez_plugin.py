import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]


def run_step(action_name, step_name, cwd, environment):
    action = yaml.safe_load((_ROOT / action_name / "action.yml").read_text())
    step = next(step for step in action["runs"]["steps"] if step["name"] == step_name)
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=cwd,
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def plugin(tmp_path):
    if shutil.which("ai-rulez") is None:
        pytest.fail("ai-rulez is required for plugin integration tests")
    config = tmp_path / "plugin" / ".ai-rulez"
    config.mkdir(parents=True)
    source = (_ROOT / "tests/fixtures/plugin-config.toml").read_text()
    base, authoring = source.split("[plugin]", 1)
    (config / "config.toml").write_text(base + 'default_layers = ["plugins"]\n')
    (config / "config.plugins.toml").write_text("[plugin]" + authoring)
    for command in (["generate", "--plugin"], ["lock", "--content-only"]):
        subprocess.run(["ai-rulez", "-C", str(config), *command], cwd=tmp_path, check=True)
    return tmp_path


def test_verifier_accepts_fresh_bundles_and_rejects_drift(plugin):
    environment = {"CONFIG_DIRECTORY": "plugin/.ai-rulez"}
    result = run_step("verify-ai-rulez-plugin", "Verify generated plugin bundles are current", plugin, environment)
    assert result.returncode == 0, result.stderr
    manifest = plugin / "plugin" / ".claude-plugin" / "plugin.json"
    manifest.write_text(manifest.read_text().replace("1.0.0", "9.0.0"))
    result = run_step("verify-ai-rulez-plugin", "Verify generated plugin bundles are current", plugin, environment)
    assert result.returncode != 0
    assert "Drifted plugin outputs" in result.stdout + result.stderr


def test_verifier_rejects_changed_plugin_source(plugin):
    config = plugin / "plugin/.ai-rulez/config.plugins.toml"
    config.write_text(config.read_text().replace('version = "1.0.0"', 'version = "9.0.0"'))
    result = run_step(
        "verify-ai-rulez-plugin",
        "Verify generated plugin bundles are current",
        plugin,
        {"CONFIG_DIRECTORY": "plugin/.ai-rulez"},
    )
    assert result.returncode != 0
    assert "Drifted plugin outputs" in result.stdout + result.stderr


def test_verifier_rejects_missing_plugin_config(tmp_path):
    result = run_step(
        "verify-ai-rulez-plugin",
        "Verify generated plugin bundles are current",
        tmp_path,
        {"CONFIG_DIRECTORY": "plugin/.ai-rulez"},
    )
    assert result.returncode != 0


def test_verifier_rejects_config_without_plugin(tmp_path):
    config = tmp_path / "plugin/.ai-rulez"
    config.mkdir(parents=True)
    (config / "config.toml").write_text('version = "5.0"\nname = "empty"\npresets = ["claude"]\n')
    result = run_step(
        "verify-ai-rulez-plugin",
        "Verify generated plugin bundles are current",
        tmp_path,
        {"CONFIG_DIRECTORY": "plugin/.ai-rulez"},
    )
    assert result.returncode != 0
    assert "no [plugin] block configured" in result.stderr


def test_package_verifies_deterministic_artifacts_and_rejects_tampering(plugin):
    subprocess.run(["git", "init", "-q"], cwd=plugin, check=True)
    subprocess.run(["git", "add", "plugin"], cwd=plugin, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-qm", "fixture"],
        cwd=plugin,
        check=True,
    )
    environment = {
        "CONFIG_DIRECTORY": "plugin/.ai-rulez",
        "DIST_DIRECTORY": "dist/plugin",
        "RELEASE_TAG": "v1.0.0",
        "CURSOR_MARKETPLACE": "true",
    }
    first = run_step("package-ai-rulez-plugin", "Package and verify release artifacts", plugin, environment)
    assert first.returncode == 0, first.stderr
    archive = next((plugin / "dist/plugin").glob("*.tar.gz"))
    original = archive.read_bytes()
    manifest = json.loads(next((plugin / "dist/plugin").glob("*.manifest.json")).read_text())
    assert manifest["runtimes"] == [
        "agent-plugins",
        "claude",
        "codex",
        "copilot",
        "cursor",
        "factory",
        "gemini",
        "hermes",
        "kimi",
        "opencode",
        "pi",
    ]
    assert len(manifest["files"]) == 19
    with tarfile.open(archive) as bundle:
        packaged_paths = set(bundle.getnames())
    assert {
        ".claude-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
        ".codex-plugin/plugin.json",
        "gemini-extension.json",
        "kimi.plugin.json",
        ".factory-plugin/plugin.json",
        ".opencode/plugins/fixture.js",
        ".hermes/plugins/fixture/plugin.yaml",
        "package.json",
        "plugin.json",
    } <= packaged_paths
    second = run_step("package-ai-rulez-plugin", "Package and verify release artifacts", plugin, environment)
    assert second.returncode == 0, second.stderr
    assert archive.read_bytes() == original
    assert (plugin / "dist/plugin/marketplace").is_dir()
    assert (plugin / "dist/plugin/emit").is_dir()
    cursor_root = plugin / "dist/plugin/emit/cursor-team-marketplace"
    cursor_index = json.loads((cursor_root / ".cursor-plugin/marketplace.json").read_text())
    assert cursor_index["plugins"][0]["name"] == "fixture"
    assert (cursor_root / "plugins/fixture/.cursor-plugin/plugin.json").is_file()
    archive.write_bytes(original + b"tampered")
    result = subprocess.run(["ai-rulez", "publish", "verify", "dist/plugin"], cwd=plugin, check=False)
    assert result.returncode != 0


def test_package_rejects_an_invalid_cursor_marketplace_value(plugin):
    result = run_step(
        "package-ai-rulez-plugin",
        "Package and verify release artifacts",
        plugin,
        {
            "CONFIG_DIRECTORY": "plugin/.ai-rulez",
            "DIST_DIRECTORY": "dist/plugin",
            "RELEASE_TAG": "v1.0.0",
            "CURSOR_MARKETPLACE": "invalid",
        },
    )
    assert result.returncode == 1
    assert "cursor-marketplace must be true or false" in result.stderr


def test_release_setup_installs_the_latest_release_through_the_floating_major_tag():
    action = yaml.safe_load((_ROOT / "setup-ai-rulez/action.yml").read_text())
    assert action["inputs"]["ai-rulez-version"]["default"] == "latest"
    install = next(step for step in action["runs"]["steps"] if step["name"] == "Install AI-Rulez release")
    assert install["uses"] == "Goldziher/ai-rulez@v5"
    assert install["with"] == {"version": "latest"}


def test_release_setup_warns_that_a_specific_version_is_ignored(tmp_path):
    action = yaml.safe_load((_ROOT / "setup-ai-rulez/action.yml").read_text())
    warn = next(step for step in action["runs"]["steps"] if step["name"] == "Warn on a deprecated AI-Rulez version")
    assert warn["if"] == "inputs.ai-rulez-version != 'latest' && inputs.source-revision == ''"
    result = run_step("setup-ai-rulez", warn["name"], tmp_path, {"AI_RULEZ_VERSION": "5.9.2"})
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "::warning title=setup-ai-rulez::ai-rulez-version is deprecated and ignored (got '5.9.2');"
        " the latest AI-Rulez release is installed. Remove the input.\n"
    )


def test_release_setup_does_not_warn_on_a_source_build():
    action = yaml.safe_load((_ROOT / "setup-ai-rulez/action.yml").read_text())
    steps = {step["name"]: step for step in action["runs"]["steps"]}
    release_guard = steps["Install AI-Rulez release"]["if"]
    assert release_guard == "inputs.source-revision == ''"
    assert steps["Warn on a deprecated AI-Rulez version"]["if"].split(" && ") == [
        "inputs.ai-rulez-version != 'latest'",
        release_guard,
    ]


def test_verifier_routes_a_legacy_version_to_the_latest_release(tmp_path):
    action = yaml.safe_load((_ROOT / "verify-ai-rulez-plugin/action.yml").read_text())
    steps = action["runs"]["steps"]
    assert not [step for step in steps if "uv tool" in step.get("run", "") or "setup-uv" in step.get("uses", "")]
    install = next(step for step in steps if step["name"] == "Install the latest AI-Rulez release for a legacy caller")
    assert install["if"] == "inputs.ai-rulez-version != ''"
    assert install["uses"] == "Goldziher/ai-rulez@v5"
    assert install["with"] == {"version": "latest"}
    warn = next(step for step in steps if step["name"] == "Warn on a deprecated AI-Rulez version")
    assert warn["if"] == "inputs.ai-rulez-version != '' && inputs.ai-rulez-version != 'latest'"
    result = run_step("verify-ai-rulez-plugin", warn["name"], tmp_path, {"AI_RULEZ_VERSION": "5.9.2"})
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "::warning title=verify-ai-rulez-plugin::ai-rulez-version is deprecated (got '5.9.2');"
        " the latest AI-Rulez release is installed. Use setup-ai-rulez instead.\n"
    )


def test_repository_does_not_pin_ai_rulez():
    assert "ai-rulez" not in (_ROOT / "mise.toml").read_text().split("[tools]", 1)[1].split("\n[", 1)[0]
    hook_source = (
        'id = "ai-rulez"\ngit = "https://github.com/Goldziher/ai-rulez.git"\nrevision = "v5"\n'
        'hooks = ["ai-rulez-validate"]\n'
    )
    assert hook_source in (_ROOT / "poly.toml").read_text()
    workflow = yaml.safe_load((_ROOT / ".github/workflows/test-ai-rulez-plugin.yml").read_text())
    assert "MISE_DISABLE_TOOLS" not in workflow["jobs"]["test"].get("env", {})


def test_source_setup_rejects_unpinned_revision(tmp_path):
    result = run_step(
        "setup-ai-rulez",
        "Check out pinned AI-Rulez source",
        tmp_path,
        {"SOURCE_REVISION": "main", "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(tmp_path / "output")},
    )
    assert result.returncode != 0
    assert "full 40-character commit SHA" in result.stderr


def test_source_build_installs_the_pinned_go_task_outside_path(tmp_path):
    action = yaml.safe_load((_ROOT / "setup-ai-rulez/action.yml").read_text())
    assert not [step for step in action["runs"]["steps"] if "install-task" in str(step.get("uses", ""))]
    build = next(step for step in action["runs"]["steps"] if step["name"].startswith("Build pinned AI-Rulez"))
    assert build["env"]["GO_TASK_MODULE"] == "github.com/go-task/task/v3/cmd/task@v3.54.0"
    stubs, source, runner_temp = tmp_path / "stubs", tmp_path / "source", tmp_path / "runner"
    for directory in (stubs, source, runner_temp):
        directory.mkdir()
    calls = tmp_path / "calls.log"
    task_stub = tmp_path / "task"
    task_stub.write_text(
        '#!/usr/bin/env bash\necho "task $*" >>"$CALLS"\nmkdir -p bin\n'
        "printf '#!/bin/sh\\necho ai-rulez version 0.0.0\\n' >bin/ai-rulez\nchmod +x bin/ai-rulez\n"
    )
    go = stubs / "go"
    go.write_text(
        '#!/usr/bin/env bash\necho "go $* GOBIN=$GOBIN" >>"$CALLS"\ninstall -m 755 "$TASK_STUB" "$GOBIN/task"\n'
    )
    go.chmod(0o755)
    github_path = tmp_path / "github_path"
    result = run_step(
        "setup-ai-rulez",
        build["name"],
        source,
        {
            "PATH": f"{stubs}:/usr/bin:/bin",
            "CALLS": str(calls),
            "TASK_STUB": str(task_stub),
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_PATH": str(github_path),
            "GO_TASK_MODULE": build["env"]["GO_TASK_MODULE"],
        },
    )
    assert result.returncode == 0, result.stderr
    go_call, task_call = calls.read_text().splitlines()
    assert go_call.startswith("go install github.com/go-task/task/v3/cmd/task@v3.54.0 GOBIN=" + str(runner_temp))
    assert task_call == "task build"
    assert "ai-rulez version 0.0.0" in result.stdout
    assert github_path.read_text() == f"{source}/bin\n"


def test_package_verifies_root_marketplace_layout(plugin):
    config = plugin / ".ai-rulez"
    config.mkdir()
    (config / "config.toml").write_text(
        'version="5.0"\nname="fixture-marketplace"\npresets=["claude"]\n'
        '[marketplace]\nname="fixture-marketplace"\nmembers=["plugin"]\n'
        '[marketplace.owner]\nname="xberg"\n',
    )
    commands = [
        ["ai-rulez", "generate", "--plugin"],
        ["ai-rulez", "lock", "--content-only"],
        ["git", "init", "-q"],
        ["git", "remote", "add", "origin", "https://github.com/xberg-io/fixture.git"],
        ["git", "add", ".ai-rulez", "plugin", ".claude-plugin", ".agents", ".ai-rulez-generated.json"],
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-qm", "fixture"],
    ]
    for command in commands:
        subprocess.run(command, cwd=plugin, check=True)
    environment = {"CONFIG_DIRECTORY": ".ai-rulez", "DIST_DIRECTORY": "dist/plugin", "RELEASE_TAG": "v1.0.0"}
    result = run_step("package-ai-rulez-plugin", "Package and verify release artifacts", plugin, environment)
    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in (plugin / "dist/plugin/plugins").iterdir()) == ["fixture"]
    assert (plugin / "dist/plugin/plugins/fixture/fixture-1.0.0.tar.gz").is_file()
    assert (plugin / "dist/plugin/aggregate/SHA256SUMS").is_file()
    assert (plugin / "dist/plugin/aggregate/marketplace/.claude-plugin/marketplace.json").is_file()


@pytest.mark.parametrize(
    ("go_mod", "expected"),
    [
        ("module example\n\ngo 1.25.0\n\ntoolchain go1.26.4\n", "1.26.4"),
        ("module example\n\ngo 1.25\n", "1.25"),
    ],
    ids=["toolchain", "go-directive"],
)
def test_source_build_installs_the_go_its_go_mod_names_through_mise(tmp_path, go_mod, expected):
    action = yaml.safe_load((_ROOT / "setup-ai-rulez/action.yml").read_text())
    steps = action["runs"]["steps"]
    assert not [step for step in steps if str(step.get("uses", "")).startswith("actions/setup-go@")]
    install = next(step for step in steps if step["name"] == "Install Go through mise for the source build")
    assert install["if"] == "inputs.source-revision != ''"
    assert install["env"]["GO_VERSION"] == "${{ steps.go.outputs.version }}"
    assert install["run"].endswith('install-tools.sh" . "go=$GO_VERSION"')
    source = tmp_path / "source"
    source.mkdir()
    (source / "go.mod").write_text(go_mod)
    (source / "go.sum").write_text("example.com/module v1.0.0 h1:abc=\n")
    output = tmp_path / "github-output"
    result = run_step(
        "setup-ai-rulez",
        "Read the Go version of the AI-Rulez source",
        tmp_path,
        {"SOURCE_DIRECTORY": str(source), "GITHUB_OUTPUT": str(output)},
    )
    assert result.returncode == 0, result.stderr
    lines = output.read_text().splitlines()
    assert lines[0] == f"version={expected}"
    assert lines[1].startswith("go-sum=")
    assert len(lines[1].removeprefix("go-sum=")) == 64
