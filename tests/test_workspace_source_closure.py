"""Policy checks for the decoded Cargo path-dependency graph; no fake Cargo success."""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / "build-python-sdist/scripts/validate-workspace-closure.py"


def guard():
    if sys.version_info < (3, 11):
        pytest.skip("workspace-closure guard requires Python 3.11 stdlib tomllib")
    specification = importlib.util.spec_from_file_location("source_closure_guard", _PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_rejects_missing_internal_manifest(tmp_path: Path):
    package = {"dependencies": [{"name": "core", "path": str(tmp_path / "missing")}]}
    with pytest.raises(ValueError, match="manifest is missing"):
        guard().local_dependencies(tmp_path, package)


def test_rejects_declared_dependency_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "Cargo.toml").write_text('[package]\nname="external"\nversion="1.0.0"\n')
    package = {"dependencies": [{"name": "external", "path": str(external)}]}
    with pytest.raises(ValueError, match="outside workspace"):
        guard().local_dependencies(workspace, package)


def test_checks_renamed_optional_build_dev_and_target_path_edges(tmp_path: Path):
    manifest = tmp_path / "core/Cargo.toml"
    manifest.parent.mkdir()
    manifest.write_text('[package]\nname="actual-core"\nversion="1.0.0"\n')
    edges = [
        {"name": "actual-core", "path": str(manifest.parent), "rename": "alias", "optional": False, "kind": None},
        {"name": "actual-core", "path": str(manifest.parent), "rename": None, "optional": True, "kind": None},
        {"name": "actual-core", "path": str(manifest.parent), "rename": None, "optional": False, "kind": "build"},
        {"name": "actual-core", "path": str(manifest.parent), "rename": None, "optional": False, "kind": "dev"},
        {
            "name": "actual-core",
            "path": str(manifest.parent),
            "rename": None,
            "optional": False,
            "kind": None,
            "target": "cfg(unix)",
        },
        {"name": "registry-only", "path": None, "optional": False, "kind": None},
    ]
    result = guard().local_dependencies(tmp_path, {"dependencies": edges})
    assert len(result) == 5
    assert [edge[0]["name"] for edge in result] == ["actual-core"] * 5
    assert [edge[1] for edge in result] == [manifest] * 5


def test_rejects_ambiguous_selected_package(tmp_path: Path):
    manifest = tmp_path / "Cargo.toml"
    package = {"manifest_path": str(manifest)}
    with pytest.raises(ValueError, match="exactly one"):
        guard().selected_package({"packages": [package, package]}, manifest)


def test_rejects_symlink_dependency_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "Cargo.toml").write_text('[package]\nname="external"\nversion="1.0.0"\n')
    link = workspace / "linked"
    link.symlink_to(external, target_is_directory=True)
    package = {"dependencies": [{"name": "external", "path": str(link)}]}
    with pytest.raises(ValueError, match="outside workspace"):
        guard().local_dependencies(workspace, package)


def test_reports_unsupported_python_capability_before_metadata(monkeypatch):
    import builtins
    import runpy

    original = builtins.__import__

    def without_tomllib(name, *args, **kwargs):
        if name == "tomllib":
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_tomllib)
    with pytest.raises(SystemExit, match=r"requires Python 3\.11 or newer"):
        runpy.run_path(str(_PATH), run_name="closure_capability_probe")


def test_rejects_resolved_local_override_even_inside_workspace(tmp_path: Path):
    manifest = tmp_path / "override/Cargo.toml"
    manifest.parent.mkdir()
    manifest.write_text('[package]\nname="patched"\nversion="1.0.0"\n')
    package = {"id": "patched-id", "manifest_path": str(manifest), "source": None}
    document = {"packages": [package], "resolve": {"nodes": [{"id": "patched-id", "deps": []}]}}
    with pytest.raises(ValueError, match="does not support local Cargo source overrides"):
        guard().resolved_local_packages(tmp_path, document, {tmp_path / "binding/Cargo.toml"}, "patched-id")


@pytest.mark.parametrize("field", ("readme", "license_file"))
@pytest.mark.parametrize("kind", ("missing", "outside", "symlink"))
def test_rejects_unconfined_or_missing_packaged_assets(tmp_path: Path, field: str, kind: str):
    root = tmp_path / "workspace"
    root.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("external")
    value = "missing.txt"
    if kind == "outside":
        value = "../external.txt"
    elif kind == "symlink":
        (root / "linked.txt").symlink_to(external)
        value = "linked.txt"
    package = {"manifest_path": str(root / "Cargo.toml"), field: value}
    diagnostic = "is missing" if kind == "missing" else "outside workspace"
    with pytest.raises(ValueError, match=diagnostic):
        guard().packaged_assets(root, package)


def test_accepts_inherited_asset_path_relative_to_package_manifest(tmp_path: Path):
    package = tmp_path / "crates/binding"
    package.mkdir(parents=True)
    (tmp_path / "README.md").write_text("shared readme")
    (tmp_path / "LICENSE").write_text("shared license")
    guard().packaged_assets(
        tmp_path,
        {
            "manifest_path": str(package / "Cargo.toml"),
            "readme": "../../README.md",
            "license_file": "../../LICENSE",
        },
    )


def test_metadata_uses_exact_maturin_directory_for_nested_cargo_configuration(tmp_path: Path, monkeypatch):
    module = guard()
    package = tmp_path / "packages/python"
    package.mkdir(parents=True)
    (package / ".cargo").mkdir()
    (package / ".cargo/config.toml").write_text("[net]\noffline=true\n")
    calls = []

    def capture(arguments, **options):
        calls.append((arguments, options))
        return type("Result", (), {"returncode": 0, "stdout": "{}"})()

    monkeypatch.setattr(module.subprocess, "run", capture)
    manifest = tmp_path / "crates/binding/Cargo.toml"
    module.metadata(manifest, cwd=package, no_dependencies=True)
    module.metadata(manifest, cwd=tmp_path, no_dependencies=False)
    assert [options["cwd"] for _, options in calls] == [package, tmp_path]
    assert [arguments[arguments.index("--manifest-path") + 1] for arguments, _ in calls] == [str(manifest)] * 2


def test_ignores_unrelated_workspace_member_but_checks_selected_dependency_closure(tmp_path: Path):
    packages = []
    for name in ("binding", "core", "unrelated"):
        manifest = tmp_path / name / "Cargo.toml"
        manifest.parent.mkdir()
        manifest.write_text(f'[package]\nname="{name}"\nversion="1.0.0"\n')
        packages.append({"id": name, "manifest_path": str(manifest), "source": None, "dependencies": []})
    document = {
        "packages": packages,
        "resolve": {
            "nodes": [
                {"id": "binding", "deps": [{"pkg": "core", "dep_kinds": [{"kind": "build", "target": "cfg(unix)"}]}]},
                {"id": "core", "deps": []},
                {"id": "unrelated", "deps": []},
            ]
        },
    }
    declared = {tmp_path / "binding/Cargo.toml", tmp_path / "core/Cargo.toml"}
    module = guard()
    assert module.reachable_package_ids(document, "binding") == {"binding", "core"}
    assert module.resolved_local_packages(tmp_path, document, declared, "binding") == 2


def test_rejects_missing_reachable_dependency_node():
    document = {"resolve": {"nodes": [{"id": "binding", "deps": [{"pkg": "missing"}]}]}}
    with pytest.raises(ValueError, match="missing a selected dependency node"):
        guard().reachable_package_ids(document, "binding")


@pytest.mark.parametrize(
    "configuration,expected",
    (
        ({}, []),
        ({"features": ["gate", "other/selected"]}, ["--features", "gate", "--features", "other/selected"]),
        ({"no-default-features": True}, ["--no-default-features"]),
        ({"all-features": True}, ["--all-features"]),
        ({"all-features": False, "no-default-features": False}, []),
    ),
)
def test_preserves_actual_maturin_feature_selection(configuration, expected):
    assert guard().maturin_feature_arguments(configuration) == expected


def test_rejects_unsupported_conditional_features_instead_of_using_default_graph():
    with pytest.raises(ValueError, match="only plain Maturin feature names"):
        guard().maturin_feature_arguments({"features": [{"feature": "gate", "python-version": ">=3.11"}]})


def test_reads_package_or_manifest_ancestor_pyproject_feature_configuration(tmp_path: Path):
    manifest = tmp_path / "crates/binding/Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[package]\nname="binding"\nversion="1.0.0"\n')
    package = tmp_path / "packages/python"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text('[tool.maturin]\nfeatures=["package-gate"]\n')
    (tmp_path / "pyproject.toml").write_text('[tool.maturin]\nfeatures=["manifest-gate"]\nno-default-features=true\n')
    module = guard()
    assert module.maturin_configuration(tmp_path, package, manifest, tmp_path) == {"features": ["package-gate"]}
    assert module.maturin_configuration(tmp_path, manifest, manifest, tmp_path) == {
        "features": ["manifest-gate"],
        "no-default-features": True,
    }


def test_full_binding_metadata_receives_features_without_adding_them_to_dependency_scans(tmp_path: Path, monkeypatch):
    module = guard()
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text('[package]\nname="binding"\nversion="1.0.0"\n')
    (tmp_path / "pyproject.toml").write_text('[tool.maturin]\nfeatures=["gate"]\nno-default-features=true\n')
    calls = []
    package = {"id": "binding", "name": "binding", "manifest_path": str(manifest), "source": None, "dependencies": []}

    def decoded(_manifest, **options):
        calls.append(options)
        return {
            "workspace_root": str(tmp_path),
            "packages": [package],
            "resolve": {"nodes": [{"id": "binding", "deps": []}]},
        }

    monkeypatch.setattr(module, "metadata", decoded)
    assert module.validate_closure(tmp_path, manifest, tmp_path, tmp_path)["resolved_local_packages"] == 1
    assert calls[0]["no_dependencies"] is True
    assert "feature_arguments" not in calls[0]
    assert calls[1]["feature_arguments"] == ("--features", "gate", "--no-default-features")


@pytest.mark.parametrize(
    "key,value",
    (
        ("config", ['patch.crates-io.core.path="../external-core"']),
        ("unstable-flags", ["bindeps"]),
    ),
)
def test_rejects_unsupported_maturin_cargo_resolution_overrides(key, value):
    with pytest.raises(ValueError, match="does not support Maturin " + key + " overrides"):
        guard().maturin_feature_arguments({key: value})


def test_preserves_maturin_lock_switches_and_accepts_empty_override_lists():
    assert guard().maturin_feature_arguments(
        {
            "locked": True,
            "frozen": True,
            "config": [],
            "unstable-flags": [],
        }
    ) == ["--frozen", "--locked"]


@pytest.mark.parametrize(
    "switches,expected_locked",
    (
        ((), 1),
        (("--locked",), 1),
        (("--frozen",), 0),
        (("--frozen", "--locked"), 1),
    ),
)
def test_existing_lock_does_not_duplicate_maturin_lock_arguments(
    tmp_path: Path, monkeypatch, switches, expected_locked
):
    module = guard()
    calls = []

    def capture(arguments, **_options):
        calls.append(arguments)
        return type("Result", (), {"returncode": 0, "stdout": "{}"})()

    monkeypatch.setattr(module.subprocess, "run", capture)
    module.metadata(
        tmp_path / "Cargo.toml", cwd=tmp_path, no_dependencies=False, locked=True, feature_arguments=switches
    )
    assert len(calls) == 1
    assert calls[0].count("--locked") == expected_locked
    assert calls[0].count("--frozen") == switches.count("--frozen")
