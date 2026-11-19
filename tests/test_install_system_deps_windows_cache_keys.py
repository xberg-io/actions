from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_STEPS = yaml.safe_load((_ROOT / "install-system-deps" / "action.yml").read_text())["runs"]["steps"]
_TOOLSET = "${{ steps.msvc-toolset.outputs.id }}"


def _step(name_prefix: str) -> dict:
    matches = [s for s in _STEPS if s.get("name", "").startswith(name_prefix)]
    assert len(matches) == 1, name_prefix
    return matches[0]


def test_msvc_toolset_step_precedes_every_toolset_keyed_cache() -> None:
    names = [s.get("name", "") for s in _STEPS]
    toolset = names.index(_step("Identify MSVC toolset").get("name"))
    for prefix in ("Cache Tesseract (Windows)", "Cache libheif + boost + zlib vcpkg (Windows)"):
        assert toolset < names.index(_step(prefix).get("name"))


def test_msvc_toolset_id_combines_runner_image_and_msvc_minor() -> None:
    step = _step("Identify MSVC toolset")
    assert step["id"] == "msvc-toolset"
    assert "ImageOS" in step["run"]
    assert "Microsoft.VCToolsVersion.default.txt" in step["run"]


def test_compiled_cpp_windows_caches_key_and_restore_on_the_toolset() -> None:
    for prefix in ("Cache Tesseract (Windows)", "Cache libheif + boost + zlib vcpkg (Windows)"):
        cache = _step(prefix)["with"]
        assert _TOOLSET in cache["key"], prefix
        restore_keys = [k for k in cache["restore-keys"].splitlines() if k.strip()]
        assert restore_keys, prefix
        for restore_key in restore_keys:
            assert _TOOLSET in restore_key, f"{prefix}: {restore_key}"


def test_toolset_independent_windows_caches_stay_unkeyed() -> None:
    for prefix in ("Cache LLVM (Windows)", "Cache CMake (Windows)"):
        assert _TOOLSET not in _step(prefix)["with"]["key"]
