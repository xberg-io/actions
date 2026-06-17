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


def test_publish_crate_passes_allow_dirty_when_injected(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(cmd: list[str]):
        captured.append(cmd)
        return 0, "ok"

    monkeypatch.setattr(crates_mod, "_run", fake_run)
    exit_code, _ = crates_mod.publish_crate("kreuzberg", [], allow_dirty=True)
    assert exit_code == 0
    assert captured == [["cargo", "publish", "-p", "kreuzberg", "--allow-dirty"]]


def test_publish_crate_omits_allow_dirty_by_default(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(cmd: list[str]):
        captured.append(cmd)
        return 0, "ok"

    monkeypatch.setattr(crates_mod, "_run", fake_run)
    exit_code, _ = crates_mod.publish_crate("kreuzberg-tesseract", ["--manifest-path", "Cargo.toml"])
    assert exit_code == 0
    assert "--allow-dirty" not in captured[0]
    assert captured == [["cargo", "publish", "-p", "kreuzberg-tesseract", "--manifest-path", "Cargo.toml"]]
