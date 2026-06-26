import importlib.util
import tarfile
import zipfile
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "verify-package-contents" / "scripts" / "verify.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_mod = _import_script("verify", _SCRIPT_PATH)


@pytest.fixture
def good_python_wheel(tmp_path: Path) -> Path:
    whl = tmp_path / "liter_llm-1.4.0rc27-cp310-abi3-linux_x86_64.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("liter_llm/__init__.py", "")
        zf.writestr("liter_llm/py.typed", "")
        zf.writestr("liter_llm/_internal_bindings.pyi", "")
        zf.writestr("liter_llm/_internal_bindings.abi3.so", b"\x00" * 100)
        zf.writestr("liter_llm-1.4.0rc27.dist-info/METADATA", "Name: liter-llm\n")
        zf.writestr("liter_llm-1.4.0rc27.dist-info/WHEEL", "Wheel-Version: 1.0\n")
        zf.writestr("liter_llm-1.4.0rc27.dist-info/RECORD", "")
        zf.writestr("liter_llm-1.4.0rc27.dist-info/licenses/LICENSE", "MIT")
    return whl


@pytest.fixture
def bad_python_wheel(tmp_path: Path) -> Path:
    """Wheel missing py.typed + .pyi + LICENSE."""
    whl = tmp_path / "bad.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("liter_llm/__init__.py", "")
        zf.writestr("liter_llm/_internal_bindings.abi3.so", b"\x00")
        zf.writestr("liter_llm-1.0.dist-info/METADATA", "a")
        zf.writestr("liter_llm-1.0.dist-info/WHEEL", "b")
        zf.writestr("liter_llm-1.0.dist-info/RECORD", "")
    return whl


@pytest.fixture
def good_node_tgz(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "package.json").write_text("{}")
    (pkg / "index.js").write_text("")
    (pkg / "index.d.ts").write_text("")
    (pkg / "LICENSE").write_text("MIT")
    tgz = tmp_path / "xberg-liter-llm-node-1.4.0-rc.27.tgz"
    with tarfile.open(tgz, "w:gz") as tf:
        for f in pkg.iterdir():
            tf.add(f, arcname=f"package/{f.name}")
    return tgz


def test_list_archive_zip(good_python_wheel: Path) -> None:
    files = verify_mod.list_archive(good_python_wheel)
    assert "liter_llm/py.typed" in files
    assert "liter_llm/_internal_bindings.pyi" in files


def test_list_archive_tar(good_node_tgz: Path) -> None:
    files = verify_mod.list_archive(good_node_tgz)
    assert "package/package.json" in files
    assert "package/index.d.ts" in files


def test_match_patterns_all_match() -> None:
    files = ["a/b.py", "a/py.typed", "a/x.pyi"]
    patterns = ["*/py.typed", "*/*.pyi"]
    matched, missing = verify_mod.match_patterns(files, patterns)
    assert len(matched) == 2
    assert missing == []


def test_match_patterns_partial() -> None:
    files = ["a/b.py"]
    patterns = ["*/py.typed", "*/b.py"]
    matched, missing = verify_mod.match_patterns(files, patterns)
    assert matched == ["*/b.py"]
    assert missing == ["*/py.typed"]


def test_main_good_python_wheel(good_python_wheel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "python")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(good_python_wheel))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "")
    monkeypatch.setenv("INPUT_STRICT", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 0


def test_main_bad_python_wheel_strict_fails(bad_python_wheel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "python")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(bad_python_wheel))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "")
    monkeypatch.setenv("INPUT_STRICT", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 1


def test_main_bad_python_wheel_non_strict_passes(bad_python_wheel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "python")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(bad_python_wheel))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "")
    monkeypatch.setenv("INPUT_STRICT", "false")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 0


def test_main_unknown_language(good_python_wheel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "cobol")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(good_python_wheel))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "")
    monkeypatch.setenv("INPUT_STRICT", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 2


def test_main_missing_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "python")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(tmp_path / "does-not-exist.whl"))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "")
    monkeypatch.setenv("INPUT_STRICT", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 2


def test_main_extras_must_match(good_python_wheel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "python")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(good_python_wheel))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "*/totally_not_present_xyz")
    monkeypatch.setenv("INPUT_STRICT", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 1


def test_main_good_node_tgz(good_node_tgz: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "node")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(good_node_tgz))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "")
    monkeypatch.setenv("INPUT_STRICT", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 0


@pytest.fixture
def good_node_platform_tgz(tmp_path: Path) -> Path:
    """Node platform-specific package with .node binary."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "package.json").write_text("{}")
    (pkg / "index.darwin-arm64.node").write_bytes(b"\x00" * 100)
    tgz = tmp_path / "xberg-html-to-markdown-node-darwin-arm64-3.6.0-rc.12.tgz"
    with tarfile.open(tgz, "w:gz") as tf:
        for f in pkg.iterdir():
            tf.add(f, arcname=f"package/{f.name}")
    return tgz


@pytest.fixture
def bad_node_platform_tgz(tmp_path: Path) -> Path:
    """Node platform-specific package missing .node binary."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "package.json").write_text("{}")
    tgz = tmp_path / "bad-platform.tgz"
    with tarfile.open(tgz, "w:gz") as tf:
        for f in pkg.iterdir():
            tf.add(f, arcname=f"package/{f.name}")
    return tgz


def test_main_good_node_platform_tgz(good_node_platform_tgz: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "node-platform")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(good_node_platform_tgz))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "")
    monkeypatch.setenv("INPUT_STRICT", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 0


def test_main_bad_node_platform_tgz_strict_fails(bad_node_platform_tgz: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_LANGUAGE", "node-platform")
    monkeypatch.setenv("INPUT_ARTIFACT_PATH", str(bad_node_platform_tgz))
    monkeypatch.setenv("INPUT_REQUIRED_EXTRAS", "")
    monkeypatch.setenv("INPUT_STRICT", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert verify_mod.main() == 1
