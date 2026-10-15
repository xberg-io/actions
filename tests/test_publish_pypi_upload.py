import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "publish-pypi/scripts/upload.py"


def load():
    spec = importlib.util.spec_from_file_location("pypi_upload", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "message,expected",
    [
        ("400 Bad Request: Project size too large. Limit for project: 10 GB", True),
        ("403 Forbidden: invalid credentials", False),
        ("400 Bad Request: filename already exists", False),
        ("Connection timeout", False),
        ("400 Bad Request: File too large", False),
    ],
)
def test_only_project_storage_quota_qualifies(message, expected):
    assert load().storage_quota_failure(message) is expected


def test_parser_preserves_hash_and_python_requirement():
    module = load()
    parser = module.IndexLinks()
    parser.feed(
        '<a href="https://github.com/o/r/releases/download/v1/a.whl#sha256=abc" data-requires-python="&gt;=3.10">a.whl</a>'
    )
    assert parser.links == [("https://github.com/o/r/releases/download/v1/a.whl#sha256=abc", ">=3.10")]


@pytest.mark.parametrize(
    "code,message,index,expected",
    [
        (0, "", "", False),
        (1, "400 Project size too large", "https://example.org/simple/", True),
        (1, "400 Project size too large", "", None),
        (1, "403 Forbidden", "https://example.org/simple/", None),
    ],
)
def test_publishing_attempts_pypi_first_and_gates_fallback(tmp_path, monkeypatch, *, code, message, index, expected):
    from types import SimpleNamespace

    module = load()
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "a-1-py3-none-any.whl").write_bytes(b"wheel")
    calls = []
    monkeypatch.setenv("PACKAGES_DIR", str(dist))
    monkeypatch.setenv("UV_PUBLISH_URL", "https://upload.pypi.org/legacy/")
    monkeypatch.setenv("INPUT_FALLBACK_INDEX_URL", index)
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def publish(args, **kwargs):
        calls.append("publish")
        assert args[:2] == ["uv", "publish"]
        assert "https://pypi.org/simple/" in args
        return SimpleNamespace(returncode=code, stdout="", stderr=message)

    def verify(files, url):
        calls.append("verify")
        assert len(files) == 1
        assert url == index

    monkeypatch.setattr(module.subprocess, "run", publish)
    monkeypatch.setattr(module, "verify_index", verify)
    if expected is None:
        with pytest.raises(SystemExit) as error:
            module.main()
        assert error.value.code == code
        assert calls == ["publish"]
        assert not output.exists()
    else:
        module.main()
        assert calls == (["publish", "verify"] if expected else ["publish"])
        assert output.read_text() == f"published={str(not expected).lower()}\nfallback={str(expected).lower()}\n"


def test_verification_failure_cannot_suppress_quota_error(tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = load()
    (tmp_path / "a-1.tar.gz").write_bytes(b"sdist")
    monkeypatch.setenv("PACKAGES_DIR", str(tmp_path))
    monkeypatch.setenv("UV_PUBLISH_URL", "https://upload.pypi.org/legacy/")
    monkeypatch.setenv("INPUT_FALLBACK_INDEX_URL", "https://example.org/simple/")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="400 Project size too large"),
    )

    def reject(*args):
        raise ValueError("archive missing")

    monkeypatch.setattr(module, "verify_index", reject)
    with pytest.raises(ValueError, match="archive missing"):
        module.main()


@pytest.mark.parametrize("corrupt", ["none", "index-hash", "asset-bytes", "requires-python", "duplicate"])
def test_fallback_checks_index_and_downloaded_bytes(tmp_path, monkeypatch, corrupt):
    import hashlib
    import io
    import zipfile

    module = load()
    wheel = tmp_path / "a-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("a-1.dist-info/METADATA", "Name: a\nVersion: 1\nRequires-Python: >=3.10\n")
    payload = wheel.read_bytes()
    digest = hashlib.sha256(payload).hexdigest() if corrupt != "index-hash" else "0" * 64
    requires = "&gt;=3.10" if corrupt != "requires-python" else "&gt;=3.11"
    link = f'<a href="https://github.com/o/r/releases/download/v1/{wheel.name}#sha256={digest}" data-requires-python="{requires}">a</a>'
    if corrupt == "duplicate":
        link += link
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        if url.endswith("/simple/a/"):
            return io.BytesIO(link.encode())
        return io.BytesIO(payload if corrupt != "asset-bytes" else b"corrupt")

    monkeypatch.setattr(module.urllib.request, "urlopen", request)
    if corrupt == "none":
        module.verify_index([wheel], "https://example.org/simple/")
        assert len(calls) == 2
    else:
        with pytest.raises(ValueError, match=r"hash|digest|Requires-Python"):
            module.verify_index([wheel], "https://example.org/simple/")


@pytest.mark.parametrize("requires", ["&gt;=3.10", "&gt;=999"])
def test_sdist_python_requirement_must_match_pkg_info(tmp_path, monkeypatch, requires):
    import hashlib
    import io
    import tarfile

    module = load()
    path = tmp_path / "some-project-1.tar.gz"
    metadata = b"Name: some-project\nVersion: 1\nRequires-Python: >=3.10\n"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("some-project-1/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    link = f'<a href="https://github.com/o/r/releases/download/v1/{path.name}#sha256={digest}" data-requires-python="{requires}">sdist</a>'
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return io.BytesIO(link.encode() if url.endswith("/simple/some-project/") else payload)

    monkeypatch.setattr(module.urllib.request, "urlopen", request)
    if requires == "&gt;=3.10":
        module.verify_index([path], "https://example.org/simple/")
        assert len(calls) == 2
    else:
        with pytest.raises(ValueError, match="Requires-Python"):
            module.verify_index([path], "https://example.org/simple/")
        assert len(calls) == 1
