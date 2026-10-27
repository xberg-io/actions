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


def test_source_setup_rejects_unpinned_revision(tmp_path):
    result = run_step(
        "setup-ai-rulez",
        "Check out pinned AI-Rulez source",
        tmp_path,
        {"SOURCE_REVISION": "main", "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(tmp_path / "output")},
    )
    assert result.returncode != 0
    assert "full 40-character commit SHA" in result.stderr


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
