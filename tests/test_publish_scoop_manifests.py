"""Tests for the publish-scoop-manifests action's render script."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from types import ModuleType

_ROOT = Path(__file__).resolve().parents[1]
_ACTION = _ROOT / "publish-scoop-manifests"
_SCRIPT = _ACTION / "scripts" / "render.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_scoop", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stage_repo(tmp_path: Path, template_body: str, assets: dict[str, str]) -> tuple[Path, Path, Path]:
    """Build a fake source repo + bucket checkout. Returns (bucket_dir, repo_root, config_file)."""
    bucket_dir = tmp_path / "scoop-bucket"
    (bucket_dir / "bucket").mkdir(parents=True)

    repo_root = tmp_path / "source"
    (repo_root / ".git").mkdir(parents=True)
    template_dir = repo_root / "scripts" / "publish"
    template_dir.mkdir(parents=True)
    (template_dir / "demo.json.tmpl").write_text(template_body)

    config_file = template_dir / "scoop.json"
    config_file.write_text(
        json.dumps(
            {
                "manifests": [
                    {
                        "name": "demo",
                        "template": "scripts/publish/demo.json.tmpl",
                        "assets": assets,
                    }
                ]
            }
        )
    )
    return bucket_dir, repo_root, config_file


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bucket_dir: Path,
    repo_root: Path,
    config_file: Path,
    github_output: Path,
    dry_run: str = "false",
) -> None:
    monkeypatch.setenv("INPUT_BUCKET_DIR", str(bucket_dir))
    monkeypatch.setenv("INPUT_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("INPUT_TAG", "v9.9.9")
    monkeypatch.setenv("INPUT_VERSION", "9.9.9")
    monkeypatch.setenv("INPUT_GITHUB_REPO", "xberg-io/demo")
    monkeypatch.setenv("INPUT_DRY_RUN", dry_run)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo_root))
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))


_MINIMAL_TEMPLATE = """{
  "version": "${version}",
  "architecture": {
    "64bit": {
      "url": "https://example.invalid/${tag}/demo.zip",
      "hash": "${win_x64_sha}"
    }
  },
  "bin": "demo.exe"
}
"""


def test_action_yml_calls_render_script() -> None:
    action = (_ACTION / "action.yml").read_text()
    assert "python3" in action
    assert "scripts/render.py" in action
    assert "ensure-gh@v1" in action
    assert "dry-run:" in action
    assert "manifests-changed" in action


def test_zero_sha_is_64_hex_zeros() -> None:
    module = _load_module()
    assert module.ZERO_SHA == "0" * 64


def test_manifest_path_constants_match_scoop_layout() -> None:
    module = _load_module()
    assert module.MANIFEST_DIR == "bucket"
    assert module.MANIFEST_SUFFIX == ".json"


def test_asset_name_interpolation_resolves_tag_and_version() -> None:
    module = _load_module()
    resolved = module._interpolate_asset_name("cli-${version}-x64.zip", tag="v1.2.3", version="1.2.3")
    assert resolved == "cli-1.2.3-x64.zip"


def test_asset_name_interpolation_leaves_unknown_placeholders_alone() -> None:
    module = _load_module()
    resolved = module._interpolate_asset_name("cli-$unknown.zip", tag="v1.2.3", version="1.2.3")
    assert resolved == "cli-$unknown.zip"


def test_sha256_matches_hashlib(tmp_path: Path) -> None:
    module = _load_module()
    payload = b"scoop manifest bytes"
    target = tmp_path / "asset.zip"
    target.write_bytes(payload)
    assert module._compute_sha256(target) == hashlib.sha256(payload).hexdigest()


def test_template_undefined_placeholder_raises(tmp_path: Path) -> None:
    module = _load_module()
    template = tmp_path / "demo.json.tmpl"
    template.write_text('{"version": "${version}", "hash": "${missing_sha}"}')
    with pytest.raises(KeyError):
        module._render_template(template, {"version": "1.0.0"})


def test_main_writes_manifest_and_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    bucket_dir, repo_root, config_file = _stage_repo(
        tmp_path, _MINIMAL_TEMPLATE, {"win_x64_sha": "demo-x86_64-pc-windows-msvc.zip"}
    )
    asset_bytes = b"zip bytes"

    def _fake_download(_repo: str, _tag: str, asset: str, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        local = out_dir / asset
        local.write_bytes(asset_bytes)
        return local

    monkeypatch.setattr(module, "_download_asset", _fake_download)
    github_output = tmp_path / "github_output.txt"
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=github_output,
    )

    assert module.main() == 0

    written = bucket_dir / "bucket" / "demo.json"
    manifest: dict[str, Any] = json.loads(written.read_text())
    assert manifest["version"] == "9.9.9"
    assert manifest["architecture"]["64bit"]["hash"] == hashlib.sha256(asset_bytes).hexdigest()
    assert manifest["architecture"]["64bit"]["url"] == "https://example.invalid/v9.9.9/demo.zip"
    assert "manifests-changed<<EOF" in github_output.read_text()
    assert str(written) in github_output.read_text()


def test_main_dry_run_substitutes_zero_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    bucket_dir, repo_root, config_file = _stage_repo(
        tmp_path, _MINIMAL_TEMPLATE, {"win_x64_sha": "demo-x86_64-pc-windows-msvc.zip"}
    )
    monkeypatch.setattr(module, "_download_asset", lambda *_a, **_kw: None)
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
        dry_run="true",
    )

    assert module.main() == 0
    manifest = json.loads((bucket_dir / "bucket" / "demo.json").read_text())
    assert manifest["architecture"]["64bit"]["hash"] == "0" * 64


def test_main_fails_when_asset_missing_and_not_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    bucket_dir, repo_root, config_file = _stage_repo(
        tmp_path, _MINIMAL_TEMPLATE, {"win_x64_sha": "demo-x86_64-pc-windows-msvc.zip"}
    )
    monkeypatch.setattr(module, "_download_asset", lambda *_a, **_kw: None)
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
    )

    assert module.main() == 1
    assert "could not fetch" in capsys.readouterr().err
    assert not (bucket_dir / "bucket" / "demo.json").exists()


def test_main_errors_when_bucket_dir_has_no_bucket_subdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    bucket_dir, repo_root, config_file = _stage_repo(tmp_path, _MINIMAL_TEMPLATE, {"win_x64_sha": "demo.zip"})
    (bucket_dir / "bucket").rmdir()
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
    )

    assert module.main() == 1
    assert "does not exist" in capsys.readouterr().err


def test_main_rejects_template_that_renders_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A trailing comma survives templating but breaks every `scoop update` in the bucket."""
    module = _load_module()
    broken = '{\n  "version": "${version}",\n}\n'
    bucket_dir, repo_root, config_file = _stage_repo(tmp_path, broken, {"win_x64_sha": "demo.zip"})
    monkeypatch.setattr(module, "_download_asset", lambda *_a, **_kw: None)
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
        dry_run="true",
    )

    assert module.main() == 1
    assert "rendered invalid JSON" in capsys.readouterr().err
    assert not (bucket_dir / "bucket" / "demo.json").exists()


def test_autoupdate_dollar_version_survives_rendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scoop's literal `$version` must reach the published manifest unexpanded.

    `$$version` in the template collapses to `$version`. Without the escape, string.Template
    would substitute this release's version and silently freeze autoupdate on it — every later
    release would keep resolving the same URL.
    """
    module = _load_module()
    template = """{
  "version": "${version}",
  "architecture": { "64bit": { "url": "https://example.invalid/${tag}/demo.zip", "hash": "${win_x64_sha}" } },
  "autoupdate": {
    "architecture": {
      "64bit": {
        "url": "https://example.invalid/v$$version/demo.zip",
        "extract_dir": "demo-$$version-x86_64-pc-windows-msvc"
      }
    }
  }
}
"""
    bucket_dir, repo_root, config_file = _stage_repo(tmp_path, template, {"win_x64_sha": "demo.zip"})
    monkeypatch.setattr(module, "_download_asset", lambda *_a, **_kw: None)
    _set_env(
        monkeypatch,
        bucket_dir=bucket_dir,
        repo_root=repo_root,
        config_file=config_file,
        github_output=tmp_path / "github_output.txt",
        dry_run="true",
    )

    assert module.main() == 0
    autoupdate = json.loads((bucket_dir / "bucket" / "demo.json").read_text())["autoupdate"]
    arch = autoupdate["architecture"]["64bit"]
    assert arch["url"] == "https://example.invalid/v$version/demo.zip"
    assert arch["extract_dir"] == "demo-$version-x86_64-pc-windows-msvc"
    assert "9.9.9" not in json.dumps(autoupdate)


_COMMIT_SCRIPT = _ACTION / "scripts" / "commit-and-push.sh"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _bucket_with_origin(tmp_path: Path) -> tuple[Path, Path]:
    """A bare `origin` holding one existing manifest, and a clone of it."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "--quiet", str(origin), str(seed))
    (seed / "bucket").mkdir()
    (seed / "bucket" / "other.json").write_text('{"version": "1.0.0"}\n')
    _git(seed, "add", "bucket/other.json")
    _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "seed")
    _git(seed, "push", "--quiet", "origin", "HEAD:main")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "--quiet", str(origin), str(clone))
    return origin, clone


def _run_commit(clone: Path, tmp_path: Path, manifests: list[Path]) -> tuple[subprocess.CompletedProcess[str], str]:
    github_output = tmp_path / "commit_output"
    github_output.write_text("")
    env = {
        **os.environ,
        "BUCKET_DIR": str(clone),
        "MANIFESTS_CHANGED": "\n".join(str(m) for m in manifests),
        "COMMIT_MESSAGE": "demo 9.9.9",
        "GIT_USER_NAME": "bot",
        "GIT_USER_EMAIL": "bot@example.invalid",
        "PUSH_BACKOFF": "0",
        "GITHUB_OUTPUT": str(github_output),
    }
    result = subprocess.run(["bash", str(_COMMIT_SCRIPT)], env=env, capture_output=True, text=True, check=False)
    return result, github_output.read_text()


def test_commit_pushes_a_manifest_new_to_the_bucket(tmp_path: Path) -> None:
    """`git diff --quiet` ignores untracked files, so xberg's first manifest was never committed."""
    origin, clone = _bucket_with_origin(tmp_path)
    manifest = clone / "bucket" / "demo.json"
    manifest.write_text('{"version": "9.9.9"}\n')

    result, outputs = _run_commit(clone, tmp_path, [manifest])

    assert result.returncode == 0, result.stderr
    assert "committed=true" in outputs
    assert _git(origin, "show", "main:bucket/demo.json") == '{"version": "9.9.9"}\n'
    assert _git(origin, "log", "-1", "--format=%s %an", "main").strip() == "demo 9.9.9 bot"


def test_commit_skips_when_the_manifest_already_matches(tmp_path: Path) -> None:
    origin, clone = _bucket_with_origin(tmp_path)
    before = _git(origin, "rev-parse", "main")

    result, outputs = _run_commit(clone, tmp_path, [clone / "bucket" / "other.json"])

    assert result.returncode == 0, result.stderr
    assert "committed=false" in outputs
    assert _git(origin, "rev-parse", "main") == before


def test_commit_rebases_over_a_concurrent_push(tmp_path: Path) -> None:
    origin, clone = _bucket_with_origin(tmp_path)
    racer = tmp_path / "racer"
    _git(tmp_path, "clone", "--quiet", str(origin), str(racer))
    (racer / "bucket" / "racer.json").write_text('{"version": "2.0.0"}\n')
    _git(racer, "add", "bucket/racer.json")
    _git(racer, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "racer")
    _git(racer, "push", "--quiet", "origin", "HEAD:main")
    manifest = clone / "bucket" / "demo.json"
    manifest.write_text('{"version": "9.9.9"}\n')

    result, outputs = _run_commit(clone, tmp_path, [manifest])

    assert result.returncode == 0, result.stderr
    assert "committed=true" in outputs
    assert "Push rejected (attempt 1/5)" in result.stdout
    tree = _git(origin, "ls-tree", "--name-only", "main", "bucket/").split()
    assert tree == ["bucket/demo.json", "bucket/other.json", "bucket/racer.json"]


def test_commit_with_no_rendered_manifests_is_a_no_op(tmp_path: Path) -> None:
    origin, clone = _bucket_with_origin(tmp_path)
    before = _git(origin, "rev-parse", "main")

    result, outputs = _run_commit(clone, tmp_path, [])

    assert result.returncode == 0, result.stderr
    assert "committed=false" in outputs
    assert _git(origin, "rev-parse", "main") == before


def test_action_commit_step_is_opt_in_and_never_runs_on_dry_run() -> None:
    action = yaml.safe_load((_ACTION / "action.yml").read_text())
    step = next(s for s in action["runs"]["steps"] if s.get("id") == "commit")

    assert action["inputs"]["commit"]["default"] == "false"
    assert step["if"] == "${{ inputs.commit == 'true' && inputs.dry-run != 'true' }}"
    assert "commit-and-push.sh" in step["run"]


def test_commit_stops_after_the_last_rejected_push(tmp_path: Path) -> None:
    """The final failed push must not be followed by another fetch, rebase and sleep."""
    origin, clone = _bucket_with_origin(tmp_path)
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    manifest = clone / "bucket" / "demo.json"
    manifest.write_text('{"version": "9.9.9"}\n')

    result, outputs = _run_commit(clone, tmp_path, [manifest])

    assert result.returncode == 1
    assert "Could not push to the bucket after 5 attempts" in result.stdout
    assert result.stdout.count("rebasing onto the current bucket tip") == 4
    assert "committed=true" not in outputs
