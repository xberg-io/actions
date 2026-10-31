"""The manual Ruby action fixture must expose its crate and package task."""

import subprocess
from pathlib import Path

import pytest
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gem_fixture(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/test-build-ruby-gem.yml").read_text())
    stages = [
        step["run"] for step in workflow["jobs"]["test"]["steps"] if step.get("name") == "Stage a tiny Magnus gem"
    ]
    assert len(stages) == 1
    subprocess.run(["bash", "-e", "-c", stages[0]], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path / "packages/ruby"


def test_rb_sys_metadata_can_find_the_extension_from_the_gem_directory(gem_fixture):
    manifest = gem_fixture / "Cargo.toml"
    assert manifest.exists(), "rb_sys runs cargo metadata from the gem directory"
    workspace = tomllib.loads(manifest.read_text())
    assert workspace["workspace"]["members"] == ["ext/fixture_magnus"]
    crate = tomllib.loads((gem_fixture / "ext/fixture_magnus/Cargo.toml").read_text())
    assert crate["package"]["name"] == "fixture_magnus"
    assert crate["lib"]["crate-type"] == ["cdylib"]


def test_rakefile_registers_the_gem_build_task_used_by_the_action(gem_fixture):
    rakefile = (gem_fixture / "Rakefile").read_text()
    assert 'require "bundler/gem_tasks"' in rakefile
    assert 'RbSys::ExtensionTask.new("fixture_magnus", GEMSPEC)' in rakefile


def test_ruby_four_fixture_uses_supported_magnus_bindings(gem_fixture):
    workflow = yaml.safe_load((ROOT / ".github/workflows/test-build-ruby-gem.yml").read_text())
    ruby_steps = [step for step in workflow["jobs"]["test"]["steps"] if step.get("uses") == "./setup-mise"]
    assert len(ruby_steps) == 1
    assert ruby_steps[0]["with"]["tools"] == "ruby=4.0.9"
    crate = tomllib.loads((gem_fixture / "ext/fixture_magnus/Cargo.toml").read_text())
    assert crate["dependencies"]["magnus"] == "0.9", "Magnus 0.7 does not support Ruby 4's C API"
