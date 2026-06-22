import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "announce-release-discord" / "scripts" / "announce.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


announce = _import_script("announce_release_discord", _SCRIPT_PATH)


def test_release_log_from_body_strips_zig_install_section():
    body = """What's Changed
- fix parser regression

<!-- zig-fetch -->
## Zig

Add to your build.zig.zon.
"""

    assert announce.release_log_from_body(body, "v1.2.3") == "What's Changed\n- fix parser regression"


def test_release_log_from_body_returns_empty_for_swift_only_body():
    body = """## Swift Package Manager

The Swift binding is distributed as a pre-built artifact bundle.
"""

    assert announce.release_log_from_body(body, "v1.2.3") == ""


def test_generate_release_notes_calls_github_api_with_target(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append((cmd, capture_output, text, check))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"body": "What's Changed\n- fix"}), stderr="")

    monkeypatch.setattr(announce.subprocess, "run", fake_run)

    result = announce.generate_release_notes("v1.2.3", "owner/project", "abc123")

    assert result == {"body": "What's Changed\n- fix"}
    cmd, capture_output, text, check = calls[0]
    assert cmd == [
        "gh",
        "api",
        "repos/owner/project/releases/generate-notes",
        "-X",
        "POST",
        "-f",
        "tag_name=v1.2.3",
        "-f",
        "target_commitish=abc123",
    ]
    assert capture_output is True
    assert text is True
    assert check is False


def test_main_uses_generated_notes_when_release_body_is_swift_only(monkeypatch, capsys):
    monkeypatch.setenv("INPUT_TAG", "v1.2.3")
    monkeypatch.setenv("INPUT_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("INPUT_REPO", "owner/project")
    monkeypatch.setenv("INPUT_PROJECT_NAME", "project")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.delenv("INPUT_NOTES", raising=False)

    monkeypatch.setattr(
        announce,
        "fetch_release",
        lambda tag, repo: {
            "body": "## Swift Package Manager\n\nAdd to Package.swift.",
            "publishedAt": "2026-06-22T10:00:00Z",
            "targetCommitish": "abc123",
        },
    )
    monkeypatch.setattr(announce, "generate_release_notes", lambda tag, repo, target: {"body": "What's Changed\n- fix"})

    announce.main()

    output = capsys.readouterr().out
    assert "What's Changed" in output
    assert "Swift Package Manager" not in output


def test_main_strips_install_sections_without_regenerating(monkeypatch, capsys):
    monkeypatch.setenv("INPUT_TAG", "v1.2.3")
    monkeypatch.setenv("INPUT_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("INPUT_REPO", "owner/project")
    monkeypatch.setenv("INPUT_PROJECT_NAME", "project")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.delenv("INPUT_NOTES", raising=False)

    release_body = """What's Changed
- fix parser regression

<!-- zig-fetch -->
## Zig

Add to build.zig.zon.
"""
    monkeypatch.setattr(
        announce,
        "fetch_release",
        lambda tag, repo: {
            "body": release_body,
            "publishedAt": "2026-06-22T10:00:00Z",
            "targetCommitish": "abc123",
        },
    )

    def fail_generate(tag, repo, target):
        raise AssertionError("generate_release_notes should not be called")

    monkeypatch.setattr(announce, "generate_release_notes", fail_generate)

    announce.main()

    output = capsys.readouterr().out
    assert "What's Changed" in output
    assert "Zig" not in output
