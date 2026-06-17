"""Tests for the path-dep version injection in publish-crates.

Covers the rewriter that fixes the cargo-publish failure mode where a manifest
omits `version = ...` on a `path = "../sibling"` dep — cargo rejects publish
with `all dependencies must have a version requirement specified`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-crates" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crates_mod = _import_script("publish_crates_inject", _SCRIPT_PATH)
VERSION = "5.0.0-rc.19"


# ---------------------------------------------------------------------------
# Inline table form
# ---------------------------------------------------------------------------


def test_inline_table_without_version_gets_injection():
    manifest = (
        "[dependencies]\n"
        'kreuzberg-tesseract = { path = "../kreuzberg-tesseract", optional = true }\n'
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert (
        f'kreuzberg-tesseract = {{ path = "../kreuzberg-tesseract", version = "{VERSION}", optional = true }}'
        in rewritten
    )


def test_inline_table_with_version_is_left_alone():
    manifest = (
        "[dependencies]\n"
        'kreuzberg-libheif = { path = "../kreuzberg-libheif", version = "1.2.3", optional = true }\n'
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert rewritten == manifest


def test_workspace_true_entry_is_left_alone():
    manifest = "[dependencies]\nfoo = { workspace = true, optional = true }\n"
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert rewritten == manifest


def test_workspace_true_with_path_is_left_alone():
    # Defensive: even if both appear, workspace inheritance owns the version.
    manifest = (
        "[dependencies]\n"
        'foo = { workspace = true, path = "../foo", optional = true }\n'
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert rewritten == manifest


# ---------------------------------------------------------------------------
# Dotted-table form: [dependencies.foo]
# ---------------------------------------------------------------------------


def test_dotted_table_without_version_gets_injection():
    manifest = (
        "[dependencies.foo]\n"
        'path = "../foo"\n'
        "optional = true\n"
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert (
        "[dependencies.foo]\n"
        f'version = "{VERSION}"\n'
        'path = "../foo"\n'
        "optional = true\n"
    ) == rewritten


def test_dotted_table_with_version_is_left_alone():
    manifest = (
        "[dependencies.foo]\n"
        'path = "../foo"\n'
        'version = "1.2.3"\n'
        "optional = true\n"
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert rewritten == manifest


def test_dotted_table_with_workspace_is_left_alone():
    manifest = (
        "[dependencies.foo]\n"
        "workspace = true\n"
        "features = [\"bar\"]\n"
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert rewritten == manifest


# ---------------------------------------------------------------------------
# Target-conditional dependencies table
# ---------------------------------------------------------------------------


def test_target_conditional_table_gets_injection():
    manifest = (
        "[target.'cfg(target_arch = \"wasm32\")'.dependencies]\n"
        'kreuzberg-tesseract = { path = "../kreuzberg-tesseract", default-features = false, '
        'features = ["build-tesseract-wasm"], optional = true }\n'
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert f'version = "{VERSION}"' in rewritten
    assert 'path = "../kreuzberg-tesseract"' in rewritten
    # Idempotent on re-run.
    again = crates_mod.inject_path_dep_versions(rewritten, VERSION)
    assert again == rewritten


def test_target_conditional_table_with_version_left_alone():
    manifest = (
        "[target.'cfg(unix)'.dependencies]\n"
        'foo = { path = "../foo", version = "1.0.0" }\n'
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert rewritten == manifest


# ---------------------------------------------------------------------------
# Dev / build dependencies
# ---------------------------------------------------------------------------


def test_dev_dependencies_get_injection():
    manifest = "[dev-dependencies]\nfoo = { path = \"../foo\" }\n"
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert f'version = "{VERSION}"' in rewritten


def test_build_dependencies_get_injection():
    manifest = "[build-dependencies]\nfoo = { path = \"../foo\" }\n"
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert f'version = "{VERSION}"' in rewritten


# ---------------------------------------------------------------------------
# Multi-line inline table
# ---------------------------------------------------------------------------


def test_multiline_inline_table_without_version_gets_injection():
    manifest = (
        "[dependencies]\n"
        "kreuzberg-tesseract = { path = \"../kreuzberg-tesseract\", default-features = false, features = [\n"
        '    "build-tesseract-wasm",\n'
        '    "bundle-tessdata-eng",\n'
        "], optional = true }\n"
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert f'version = "{VERSION}"' in rewritten
    # Re-running is a no-op.
    again = crates_mod.inject_path_dep_versions(rewritten, VERSION)
    assert again == rewritten


def test_multiline_inline_table_with_version_left_alone():
    manifest = (
        "[dependencies]\n"
        'kreuzberg-libheif = { path = "../kreuzberg-libheif", version = "5.0.0-rc.19", features = [\n'
        '    "decode",\n'
        "], optional = true }\n"
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert rewritten == manifest


# ---------------------------------------------------------------------------
# Section-awareness: workspace + lib + features sections must not be touched
# ---------------------------------------------------------------------------


def test_non_dependency_sections_are_ignored():
    manifest = (
        "[package]\n"
        'name = "kreuzberg"\n'
        "[features]\n"
        'foo = ["path"]\n'
        "[workspace.dependencies]\n"
        'bar = { path = "../bar" }\n'
        "[dependencies]\n"
        'real = { path = "../real" }\n'
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    # The [workspace.dependencies] bar entry must NOT be touched, but the
    # [dependencies] real entry must be rewritten.
    assert 'bar = { path = "../bar" }' in rewritten
    assert f'real = {{ path = "../real", version = "{VERSION}" }}' in rewritten


def test_dep_without_path_is_left_alone():
    manifest = (
        "[dependencies]\n"
        'serde = { version = "1.0" }\n'
        'thiserror = "1"\n'
    )
    rewritten = crates_mod.inject_path_dep_versions(manifest, VERSION)
    assert rewritten == manifest


# ---------------------------------------------------------------------------
# Round-trip preservation through the context manager
# ---------------------------------------------------------------------------


def test_temporary_injection_restores_original_bytes(tmp_path):
    original = (
        "[package]\n"
        'name = "kreuzberg"\n'
        "[dependencies]\n"
        'kreuzberg-tesseract = { path = "../kreuzberg-tesseract", optional = true }\n'
    )
    manifest_path = tmp_path / "Cargo.toml"
    manifest_path.write_text(original, encoding="utf-8")
    original_bytes = manifest_path.read_bytes()

    with crates_mod._temporarily_inject_versions(str(manifest_path), VERSION):
        rewritten_bytes = manifest_path.read_bytes()
        assert original_bytes != rewritten_bytes
        assert f'version = "{VERSION}"' in rewritten_bytes.decode("utf-8")

    assert manifest_path.read_bytes() == original_bytes


def test_temporary_injection_restores_on_exception(tmp_path):
    original = (
        "[dependencies]\n"
        'foo = { path = "../foo" }\n'
    )
    manifest_path = tmp_path / "Cargo.toml"
    manifest_path.write_text(original, encoding="utf-8")
    original_bytes = manifest_path.read_bytes()

    class Boom(RuntimeError):
        pass

    try:
        with crates_mod._temporarily_inject_versions(str(manifest_path), VERSION):
            raise Boom
    except Boom:
        pass

    assert manifest_path.read_bytes() == original_bytes


def test_temporary_injection_no_op_when_manifest_already_correct(tmp_path):
    original = (
        "[dependencies]\n"
        'foo = { path = "../foo", version = "1.0.0" }\n'
    )
    manifest_path = tmp_path / "Cargo.toml"
    manifest_path.write_text(original, encoding="utf-8")
    original_bytes = manifest_path.read_bytes()

    with crates_mod._temporarily_inject_versions(str(manifest_path), VERSION):
        # Inside the context, the manifest should be byte-identical because no
        # injection was required.
        assert manifest_path.read_bytes() == original_bytes

    assert manifest_path.read_bytes() == original_bytes


def test_temporary_injection_silently_skips_missing_path(tmp_path):
    missing = tmp_path / "does-not-exist.toml"
    # Must not raise.
    with crates_mod._temporarily_inject_versions(str(missing), VERSION):
        pass
    assert not missing.exists()


def test_temporary_injection_silently_skips_empty_path():
    # Must not raise when manifest_path is empty/None.
    with crates_mod._temporarily_inject_versions("", VERSION):
        pass
    with crates_mod._temporarily_inject_versions(None, VERSION):
        pass
