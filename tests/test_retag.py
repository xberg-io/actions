import importlib.util
import json
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "retag-for-republish" / "scripts" / "retag.py"

spec = importlib.util.spec_from_file_location("retag", str(_SCRIPT))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_build_delete_url():
    result = mod.build_delete_url("org/repo", "v1.2.3")
    assert result == "repos/org/repo/git/refs/tags/v1.2.3"


def test_build_delete_url_nested_repo():
    result = mod.build_delete_url("xberg-io/actions", "v0.5.0")
    assert result == "repos/xberg-io/actions/git/refs/tags/v0.5.0"


def test_build_delete_url_starts_with_repos():
    result = mod.build_delete_url("org/repo", "v1.0.0")
    assert result.startswith("repos/")


def test_build_create_payload():
    sha = "a" * 40
    result = mod.build_create_payload("v1.2.3", sha)
    assert result == {"ref": "refs/tags/v1.2.3", "sha": sha}


def test_build_create_payload_format():
    sha = "deadbeef" * 5
    result = mod.build_create_payload("v0.1.0", sha)
    assert result["ref"] == "refs/tags/v0.1.0"
    assert result["sha"] == sha


def test_build_create_payload_ref_prefix():
    sha = "b" * 40
    result = mod.build_create_payload("v2.0.0", sha)
    assert result["ref"].startswith("refs/tags/")


def _completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr="")


def test_find_orphaned_drafts_returns_only_drafts_on_the_tag(monkeypatch):
    payload = json.dumps(
        [
            {"id": 1, "tag_name": "v1.1.3", "draft": True, "assets": [{"name": "stale.zip"}]},
            {"id": 2, "tag_name": "v1.1.3", "draft": False, "assets": []},
            {"id": 3, "tag_name": "v1.1.2", "draft": True, "assets": []},
        ]
    )
    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_kw: _completed(stdout=payload))
    drafts = mod.find_orphaned_drafts("o/r", "v1.1.3")
    assert [draft["id"] for draft in drafts] == [1]


def test_find_orphaned_drafts_reads_paginated_output(monkeypatch):
    payload = (
        json.dumps([{"id": 1, "tag_name": "v9", "draft": False}])
        + "\n"
        + json.dumps([{"id": 2, "tag_name": "v9", "draft": True}])
    )
    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_kw: _completed(stdout=payload))
    assert [draft["id"] for draft in mod.find_orphaned_drafts("o/r", "v9")] == [2]


def test_find_orphaned_drafts_is_silent_when_gh_fails(monkeypatch):
    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_kw: _completed(returncode=1))
    assert mod.find_orphaned_drafts("o/r", "v1") == []


def test_report_orphaned_drafts_warns_with_the_draft_id(monkeypatch, capsys):
    monkeypatch.setattr(mod, "find_orphaned_drafts", lambda _repo, _tag: [{"id": 384891430, "assets": [{"name": "a"}]}])
    mod.report_orphaned_drafts("o/r", "v1.1.3")
    out = capsys.readouterr().out
    assert "::warning::1 draft release(s) remain on tag v1.1.3" in out
    assert "draft id=384891430 with 1 asset(s)" in out


def test_report_orphaned_drafts_prints_nothing_when_clean(monkeypatch, capsys):
    monkeypatch.setattr(mod, "find_orphaned_drafts", lambda _repo, _tag: [])
    mod.report_orphaned_drafts("o/r", "v1")
    assert capsys.readouterr().out == ""
