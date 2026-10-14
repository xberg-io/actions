import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "validate-ai-rulez/scripts/validate.py"


def cli(root, *arguments):
    return subprocess.run(["ai-rulez", *arguments], cwd=root, capture_output=True, text=True, check=True)


def commit(root, *paths):
    subprocess.run(["git", "add", *paths], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-qm", "fixture"],
        cwd=root,
        check=True,
    )


@pytest.fixture
def governance(tmp_path):
    config = tmp_path / ".ai-rulez"
    skill = config / "skills/example"
    (skill / "references").mkdir(parents=True)
    (config / "config.toml").write_text(
        'version="5.0"\nname="fixture"\npresets=["claude"]\ngitignore=true\n'
        'gitignore_exclude=[".ai-rulez/.generated-manifest.json"]\n[mcp]\nself_server=false\n'
        "[lock]\ninclude_outputs=false\n",
    )
    (skill / "SKILL.md").write_text(
        "---\ntype: Playbook\ntitle: Example\ndescription: Read the example resource when checking fixtures.\n"
        "x-ai-rulez:\n  kind: skill\n  id: example\n  metadata:\n    name: example\n---\n\n"
        "Read [the resource](references/example.md) before applying this example.\n",
    )
    (skill / "references/example.md").write_text("# Example Resource\n\nKeep the complete example.\n")
    cli(tmp_path, "migrate", "okf")
    cli(tmp_path, "generate")
    cli(tmp_path, "lock", "--content-only")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    commit(tmp_path, ".ai-rulez", ".gitignore")
    return tmp_path


def validate(root, **overrides):
    environment = {
        "CONFIG_DIRECTORY": ".ai-rulez",
        "ADDITIONAL_CONFIG_DIRECTORIES": "",
        "EXPECTED_CONFIG_COUNT": "1",
        "VERIFY_PLUGIN": "false",
        "VERSION_SYNC_SCRIPT": "scripts/sync_plugin_version.py",
        "PUBLIC_SKILLS_CHECK_SCRIPT": "scripts/sync_public_skills.py",
        **overrides,
    }
    return subprocess.run(
        ["python3", str(_SCRIPT)],
        cwd=root,
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_materializes_ignored_outputs_and_checks_one_config(governance):
    (governance / "CLAUDE.md").unlink()
    result = validate(governance)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "expected configs=1; validated configs=1" in result.stdout
    assert (governance / "CLAUDE.md").is_file()


def test_rejects_malformed_okf_before_materializing(governance):
    skill = governance / ".ai-rulez/skills/example/SKILL.md"
    skill.write_text(skill.read_text().replace("type: Playbook", "type: []"))
    commit(governance, ".ai-rulez/skills/example/SKILL.md")
    (governance / "CLAUDE.md").unlink()
    result = validate(governance)
    assert result.returncode != 0
    assert "type" in result.stdout + result.stderr
    assert "AR9B1 okf-type-invalid" in result.stdout
    assert not (governance / "CLAUDE.md").exists()


def test_rejects_missing_skill_resource(governance):
    (governance / ".ai-rulez/skills/example/references/example.md").unlink()
    commit(governance, ".ai-rulez/skills/example/references/example.md")
    result = validate(governance)
    assert result.returncode != 0
    assert "references/example.md" in result.stdout + result.stderr


def test_rejects_unknown_configuration_field(governance):
    config = governance / ".ai-rulez/config.toml"
    config.write_text("unknown_option=true\n" + config.read_text())
    commit(governance, ".ai-rulez/config.toml")
    result = validate(governance)
    assert result.returncode != 0
    assert "unknown_option" in result.stdout + result.stderr


def test_rejects_stale_source_lock(governance):
    resource = governance / ".ai-rulez/skills/example/references/example.md"
    resource.write_text("# Example Resource\n\nThe resource changed.\n")
    commit(governance, ".ai-rulez/skills/example/references/example.md")
    result = validate(governance)
    assert result.returncode != 0
    assert "lock" in result.stdout + result.stderr


def test_rejects_zero_or_mismatched_configuration_counts(governance):
    zero = validate(governance, EXPECTED_CONFIG_COUNT="0")
    mismatch = validate(governance, EXPECTED_CONFIG_COUNT="2")
    assert zero.returncode != 0
    assert mismatch.returncode != 0
    assert "expected configs=2; supplied configs=1" in mismatch.stderr


def test_validates_explicit_module_without_recursive_peer_discovery(governance):
    module = governance / "modules/core"
    module.mkdir(parents=True)
    (module / "config.toml").write_text('version="5.0"\nname="module"\npresets=["claude"]\n[mcp]\nself_server=false\n')
    cli(governance, "-C", str(module), "migrate", "okf")
    peer = governance / "peer/.ai-rulez"
    peer.mkdir(parents=True)
    (peer / "config.toml").write_text("malformed peer config")
    commit(governance, "modules", "peer")
    result = validate(governance, ADDITIONAL_CONFIG_DIRECTORIES="modules/core", EXPECTED_CONFIG_COUNT="2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "expected configs=2; validated configs=2" in result.stdout


def test_rejects_tracked_generated_drift_after_materializing(governance):
    manifest = governance / ".ai-rulez/.generated-manifest.json"
    manifest.write_text("{}\n")
    commit(governance, ".ai-rulez/.generated-manifest.json")
    result = validate(governance)
    assert result.returncode != 0
    assert "diff --git a/.ai-rulez/.generated-manifest.json" in result.stdout


def test_rejects_stale_shipped_plugin_before_any_generation(governance):
    source = Path(__file__).parent / "fixtures/plugin-config.toml"
    authoring = "[plugin]" + source.read_text().split("[plugin]", 1)[1]
    config = governance / ".ai-rulez/config.toml"
    config.write_text(config.read_text() + authoring)
    cli(governance, "generate", "--plugin")
    cli(governance, "generate")
    cli(governance, "lock", "--content-only")
    manifest = governance / ".claude-plugin/plugin.json"
    manifest.write_text(manifest.read_text().replace("1.0.0", "9.0.0"))
    commit(governance, ".ai-rulez", ".claude-plugin")
    (governance / "CLAUDE.md").unlink()
    result = validate(governance, VERIFY_PLUGIN="true")
    assert result.returncode != 0
    assert "Drifted plugin outputs" in result.stdout + result.stderr
    assert not (governance / "CLAUDE.md").exists()


def test_rejects_failed_public_export_check_before_materialization(governance):
    source = Path(__file__).parent / "fixtures/plugin-config.toml"
    config = governance / ".ai-rulez/config.toml"
    config.write_text(config.read_text() + "[plugin]" + source.read_text().split("[plugin]", 1)[1])
    cli(governance, "generate", "--plugin")
    cli(governance, "generate")
    cli(governance, "lock", "--content-only")
    scripts = governance / "scripts"
    scripts.mkdir()
    (scripts / "sync_plugin_version.py").write_text("import sys\nassert sys.argv[1:] == ['--check']\n")
    (scripts / "sync_public_skills.py").write_text("import sys\nprint('public export drift')\nsys.exit(7)\n")
    commit(governance, ".ai-rulez", "scripts")
    (governance / "CLAUDE.md").unlink()
    result = validate(governance, VERIFY_PLUGIN="true")
    assert result.returncode != 0
    assert "public export drift" in result.stdout
    assert "sync_public_skills.py" in result.stderr
    assert not (governance / "CLAUDE.md").exists()


def test_rejects_legacy_skill_format_even_when_source_lock_is_current(governance):
    skill = governance / ".ai-rulez/skills/example/SKILL.md"
    skill.write_text(
        "---\nname: example\ndescription: Read the example resource when checking fixtures.\n---\n\n"
        "Read [the resource](references/example.md) before applying this example.\n",
    )
    cli(governance, "lock", "--content-only")
    cli(governance, "lock", "--check")
    commit(governance, ".ai-rulez/skills/example/SKILL.md", ".ai-rulez/ai-rulez.lock")
    (governance / "CLAUDE.md").unlink()
    result = validate(governance)
    assert result.returncode != 0
    assert "migrate" in result.stderr
    assert "okf" in result.stderr
    assert "exit status 2" in result.stderr
    assert not (governance / "CLAUDE.md").exists()
