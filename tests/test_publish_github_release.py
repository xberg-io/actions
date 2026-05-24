import importlib.util
from pathlib import Path

_ENSURE_RELEASE_PATH = Path(__file__).resolve().parents[1] / "publish-github-release" / "scripts" / "ensure_release.py"
_UPLOAD_ARTIFACTS_PATH = (
    Path(__file__).resolve().parents[1] / "publish-github-release" / "scripts" / "upload_artifacts.py"
)


def _import_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ensure_mod = _import_script("ensure_release", _ENSURE_RELEASE_PATH)
upload_mod = _import_script("upload_artifacts", _UPLOAD_ARTIFACTS_PATH)


# ---------------------------------------------------------------------------
# create_release — payload-building behaviour (replaces old build_create_flags)
# ---------------------------------------------------------------------------
#
# create_release() builds a REST payload dict and passes it to github_request().
# We monkeypatch github_request on the dynamically-imported module so the real
# HTTP call is never made, then assert the exact payload that was sent.


def _capture_payload(monkeypatch):
    """Return a list that will be populated with the body_dict passed to github_request."""
    captured = []

    def _fake_github_request(method, url, token, data=None):
        captured.append(data)
        return 201, {"id": 1, "upload_url": "https://uploads.example.com/assets{?name,label}"}

    monkeypatch.setattr(ensure_mod, "github_request", _fake_github_request)
    return captured


def test_create_release_default(monkeypatch):
    captured = _capture_payload(monkeypatch)

    ensure_mod.create_release("owner", "repo", "v1.2.3", "v1.2.3", generate_notes=True, draft=False, prerelease=False)

    payload = captured[0]
    assert payload["tag_name"] == "v1.2.3"
    assert payload["name"] == "v1.2.3"
    assert payload["draft"] is False
    assert payload["prerelease"] is False
    assert payload["generate_release_notes"] is True
    assert "body" not in payload
    assert "target_commitish" not in payload


def test_create_release_posts_to_releases_endpoint(monkeypatch):
    calls = []

    def _fake_github_request(method, url, token, data=None):
        calls.append((method, url))
        return 201, {"id": 1}

    monkeypatch.setattr(ensure_mod, "github_request", _fake_github_request)
    ensure_mod.create_release("owner", "repo", "v1.2.3", "v1.2.3", generate_notes=True, draft=False, prerelease=False)

    method, url = calls[0]
    assert method == "POST"
    assert url == "https://api.github.com/repos/owner/repo/releases"


def test_create_release_draft(monkeypatch):
    captured = _capture_payload(monkeypatch)

    ensure_mod.create_release("owner", "repo", "v1.2.3", "v1.2.3", generate_notes=True, draft=True, prerelease=False)

    payload = captured[0]
    assert payload["draft"] is True
    assert payload["prerelease"] is False


def test_create_release_prerelease(monkeypatch):
    captured = _capture_payload(monkeypatch)

    ensure_mod.create_release("owner", "repo", "v1.2.3", "v1.2.3", generate_notes=True, draft=False, prerelease=True)

    payload = captured[0]
    assert payload["prerelease"] is True
    assert payload["draft"] is False


def test_create_release_no_generate_notes(monkeypatch):
    captured = _capture_payload(monkeypatch)

    ensure_mod.create_release("owner", "repo", "v1.2.3", "v1.2.3", generate_notes=False, draft=False, prerelease=False)

    payload = captured[0]
    assert "generate_release_notes" not in payload
    assert "body" not in payload
    assert payload["tag_name"] == "v1.2.3"
    assert payload["name"] == "v1.2.3"


def test_create_release_target_commitish(monkeypatch):
    captured = _capture_payload(monkeypatch)

    ensure_mod.create_release(
        "owner",
        "repo",
        "v1.2.3",
        "v1.2.3",
        generate_notes=True,
        draft=False,
        prerelease=False,
        target="abc123",
    )

    payload = captured[0]
    assert payload["target_commitish"] == "abc123"


def test_create_release_notes_overrides_generate_notes(monkeypatch):
    captured = _capture_payload(monkeypatch)

    ensure_mod.create_release(
        "owner",
        "repo",
        "v1.2.3",
        "v1.2.3",
        generate_notes=True,
        draft=False,
        prerelease=False,
        notes="Release v1.2.3",
    )

    payload = captured[0]
    assert payload["body"] == "Release v1.2.3"
    # notes takes precedence — generate_release_notes must not be set
    assert "generate_release_notes" not in payload


def test_create_release_empty_notes_falls_back_to_generate(monkeypatch):
    captured = _capture_payload(monkeypatch)

    ensure_mod.create_release(
        "owner",
        "repo",
        "v1.2.3",
        "v1.2.3",
        generate_notes=True,
        draft=False,
        prerelease=False,
        notes="",
    )

    payload = captured[0]
    assert payload["generate_release_notes"] is True
    assert "body" not in payload


# ---------------------------------------------------------------------------
# expand_artifact_patterns
# ---------------------------------------------------------------------------


def test_expand_artifact_patterns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "package-1.0.0.whl").write_text("fake")
    (tmp_path / "package-1.0.0.tar.gz").write_text("fake")
    (tmp_path / "unrelated.txt").write_text("ignore me")

    result = upload_mod.expand_artifact_patterns("*.whl,*.tar.gz")

    names = {p.name for p in result}
    assert "package-1.0.0.whl" in names
    assert "package-1.0.0.tar.gz" in names
    assert "unrelated.txt" not in names


def test_expand_artifact_patterns_newline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "artifact.zip").write_text("fake")

    result = upload_mod.expand_artifact_patterns("*.zip\n*.tar.gz")

    assert any(p.name == "artifact.zip" for p in result)


def test_expand_artifact_patterns_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = upload_mod.expand_artifact_patterns("*.nupkg,*.whl")

    assert result == []


def test_expand_artifact_patterns_mixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "found.whl").write_text("fake")
    # No .tar.gz files present

    result = upload_mod.expand_artifact_patterns("*.whl,*.tar.gz")

    assert len(result) == 1
    assert result[0].name == "found.whl"
