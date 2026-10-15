import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "archive-python/scripts/archive.py"


def load():
    spec = importlib.util.spec_from_file_location("archive_python", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_index_normalizes_names_and_escapes_metadata(tmp_path):
    module = load()
    row = {
        "name": "Some_Package",
        "filename": "some_package-1-py3-none-any.whl",
        "sha256": "a" * 64,
        "url": "https://github.com/o/r/releases/download/v1/some_package-1-py3-none-any.whl",
        "requires_python": ">=3.10",
        "size": 100,
    }
    module.write_index([row], tmp_path)
    text = (tmp_path / "simple/some-package/index.html").read_text()
    assert "#sha256=" + "a" * 64 in text
    assert 'data-requires-python="&gt;=3.10"' in text
    assert "some-package/" in (tmp_path / "simple/index.html").read_text()


@pytest.mark.parametrize("rows", [[], [{"name": "../escape"}]])
def test_index_rejects_empty_or_invalid_manifest(tmp_path, rows):
    with pytest.raises(ValueError, match=r"empty|Invalid"):
        load().write_index(rows, tmp_path)


def test_index_rejects_conflicting_assets(tmp_path):
    module = load()
    row = {
        "name": "a",
        "filename": "a-1-py3-none-any.whl",
        "sha256": "a" * 64,
        "url": "https://github.com/o/r/releases/download/v1/a-1-py3-none-any.whl",
        "requires_python": "",
        "size": 100,
    }
    with pytest.raises(ValueError, match="Conflicting"):
        module.write_index([row, dict(row, sha256="b" * 64)], tmp_path)


def test_archive_hashes_actual_uploaded_bytes(tmp_path, monkeypatch):
    module = load()
    wheel = tmp_path / "a-1-py3-none-any.whl"
    wheel.write_bytes(b"actual bytes")
    monkeypatch.setattr(module, "download_digest", lambda url: ("0" * 64, 12))
    with pytest.raises(ValueError, match="digest"):
        module.verify_asset(wheel, "https://github.com/o/r/releases/download/v1/" + wheel.name)


def wheel(path, version="1", name="a"):
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{name}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nRequires-Python: >=3.10\n",
        )


def test_archive_rejects_stale_metadata_before_upload(tmp_path, monkeypatch):
    module = load()
    wheel(tmp_path / "a-1-py3-none-any.whl")
    monkeypatch.setattr(module, "gh", lambda *args: {"draft": False, "assets": []})
    with pytest.raises(ValueError, match="Unexpected distribution version"):
        module.archive_distributions(tmp_path, "o/r", "v2", "2")


def test_draft_is_rejected_before_archiving(tmp_path, monkeypatch):
    module = load()
    monkeypatch.setattr(module, "gh", lambda *args: {"draft": True})
    with pytest.raises(ValueError, match="public release"):
        module.archive_distributions(tmp_path, "o/r", "v1", "1")


def test_archive_uploads_then_anonymously_checks_every_file(tmp_path, monkeypatch):
    module = load()
    wheel(tmp_path / "a-1-py3-none-any.whl")
    monkeypatch.setattr(module, "gh", lambda *args: {"draft": False, "assets": []})
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: calls.append("upload"))
    monkeypatch.setattr(module, "verify_asset", lambda *args: calls.append("verify"))
    rows = module.archive_distributions(tmp_path, "o/r", "v1", "1")
    assert calls == ["upload", "verify"]
    assert len(rows) == 1
    assert rows[0]["name"] == "a"
    assert rows[0]["requires_python"] == ">=3.10"
    assert rows[0]["size"] == (tmp_path / "a-1-py3-none-any.whl").stat().st_size


def test_filename_metadata_disagreement_cannot_enter_index(tmp_path, monkeypatch):
    module = load()
    wheel(tmp_path / "wrong-1-py3-none-any.whl")
    monkeypatch.setattr(module, "gh", lambda *args: {"draft": False, "assets": []})
    with pytest.raises(ValueError, match="filename differs"):
        module.archive_distributions(tmp_path, "o/r", "v1", "1")


def test_reusing_output_cannot_leave_stale_links(tmp_path):
    module = load()
    row = {
        "name": "a",
        "filename": "a-1-py3-none-any.whl",
        "sha256": "a" * 64,
        "url": "https://github.com/o/r/releases/download/v1/a-1-py3-none-any.whl",
        "requires_python": "",
        "size": 100,
    }
    module.write_index([row], tmp_path)
    with pytest.raises(ValueError, match="fresh"):
        module.write_index([row], tmp_path)


def test_index_only_does_not_require_or_upload_distributions(tmp_path, monkeypatch):
    module = load()
    row = {
        "name": "a",
        "filename": "a-1-py3-none-any.whl",
        "sha256": "a" * 64,
        "url": "https://github.com/o/r/releases/download/v1/a-1-py3-none-any.whl",
        "requires_python": "",
        "size": 100,
    }
    monkeypatch.setattr(module, "release_rows", lambda repository: [row])
    monkeypatch.setattr(module, "archive_distributions", lambda *args: pytest.fail("Index-only attempted upload"))
    monkeypatch.setattr(
        sys, "argv", ["archive.py", "--index-only", "--repository", "o/r", "--output-dir", str(tmp_path)]
    )
    module.main()
    assert (tmp_path / "simple/a/index.html").is_file()


@pytest.mark.parametrize("mutation", ["none", "missing-asset", "wrong-digest", "old-api-no-digest"])
def test_release_catalog_verifies_paginated_manifests(tmp_path, monkeypatch, mutation):
    import io
    import json

    module = load()
    row = {
        "name": "a",
        "filename": "a-1-py3-none-any.whl",
        "sha256": "a" * 64,
        "url": "https://github.com/o/r/releases/download/v1/a-1-py3-none-any.whl",
        "requires_python": "",
        "size": 100,
    }
    asset = {
        "name": row["filename"],
        "size": 100,
        "browser_download_url": row["url"],
        "digest": "sha256:" + row["sha256"],
    }
    if mutation == "wrong-digest":
        asset["digest"] = "sha256:" + "b" * 64
    if mutation == "old-api-no-digest":
        asset.pop("digest")
    assets = [
        {
            "name": "python-archive-a.json",
            "browser_download_url": "https://github.com/o/r/releases/download/v1/python-archive-a.json",
        }
    ]
    if mutation != "missing-asset":
        assets.append(asset)
    pages = [[{"draft": True, "assets": []}], [{"draft": False, "assets": assets}]]
    monkeypatch.setattr(module, "gh", lambda *args: pages)
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps({"files": [row]}).encode())
    )
    checked = []

    def digest(url):
        checked.append(url)
        return row["sha256"], row["size"]

    monkeypatch.setattr(module, "download_digest", digest)
    if mutation in ["missing-asset", "wrong-digest"]:
        with pytest.raises(ValueError, match="manifest"):
            module.release_rows("o/r")
    else:
        assert module.release_rows("o/r") == [row]
        assert len(checked) == (1 if mutation == "old-api-no-digest" else 0)
