import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-crates" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crates_mod = _import_script("publish_crates", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# is_already_published
# ---------------------------------------------------------------------------


def test_is_already_published_uploaded():
    assert crates_mod.is_already_published("error: crate version has already uploaded") is True


def test_is_already_published_exists():
    assert crates_mod.is_already_published("error: already exists in the registry") is True


def test_is_already_published_false():
    assert crates_mod.is_already_published("error: could not find `Cargo.toml`") is False


# ---------------------------------------------------------------------------
# is_new_crate_trusted_publishing
# ---------------------------------------------------------------------------


def test_is_new_crate_trusted_publishing_true():
    output = (
        "error: failed to publish to registry at https://crates.io\n"
        "Caused by:\n"
        "  the remote server responded with an error (status 400 Bad Request): "
        "Trusted Publishing tokens do not support creating new crates. "
        "Publish the crate manually, first"
    )
    assert crates_mod.is_new_crate_trusted_publishing(output) is True


def test_is_new_crate_trusted_publishing_false():
    assert crates_mod.is_new_crate_trusted_publishing("error: already exists in the registry") is False


# ---------------------------------------------------------------------------
# build_manifest_args
# ---------------------------------------------------------------------------


def test_build_manifest_args_empty():
    assert crates_mod.build_manifest_args("") == []


def test_build_manifest_args_set():
    result = crates_mod.build_manifest_args("Cargo.toml")
    assert result == ["--manifest-path", "Cargo.toml"]


# ---------------------------------------------------------------------------
# parse_crate_list
# ---------------------------------------------------------------------------


def test_parse_crate_list():
    result = crates_mod.parse_crate_list("crate1 crate2")
    assert result == ["crate1", "crate2"]


def test_parse_crate_list_extra_whitespace():
    result = crates_mod.parse_crate_list("  crate1   crate2  ")
    assert result == ["crate1", "crate2"]


def test_parse_crate_list_single():
    result = crates_mod.parse_crate_list("only-one")
    assert result == ["only-one"]


# ---------------------------------------------------------------------------
# publish_crate --allow-dirty handling
# ---------------------------------------------------------------------------


def test_publish_crate_always_passes_allow_dirty(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(cmd: list[str]):
        captured.append(cmd)
        return 0, "ok"

    monkeypatch.setattr(crates_mod, "_run", fake_run)
    # publish_crate always appends --allow-dirty: publish-time path-dep version
    # injection is an intentional transform that may dirty the working tree.
    exit_code, _ = crates_mod.publish_crate("xberg-tesseract", ["--manifest-path", "Cargo.toml"])
    assert exit_code == 0
    assert captured == [
        ["cargo", "publish", "-p", "xberg-tesseract", "--manifest-path", "Cargo.toml", "--allow-dirty"]
    ]


def test_publish_crate_does_not_retry_new_crate_trusted_publishing(monkeypatch):
    """A new-crate OIDC rejection must fail fast — retrying never grants create permission."""
    calls = 0

    def fake_run(cmd: list[str]):
        nonlocal calls
        calls += 1
        return 1, "Trusted Publishing tokens do not support creating new crates. Publish the crate manually, first"

    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(crates_mod, "_run", fake_run)
    monkeypatch.setattr(crates_mod.time, "sleep", fake_sleep)

    exit_code, output = crates_mod.publish_crate("xberg-candle-ocr", [])

    assert exit_code == 1
    assert crates_mod.is_new_crate_trusted_publishing(output) is True
    assert calls == 1, "must not retry the new-crate rejection"
    assert slept == [], "must not sleep between (non-existent) retries"
