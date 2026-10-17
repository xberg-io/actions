"""Validate local Rust source dependencies before maturin builds a source archive."""

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("workspace-closure requires Python 3.11 or newer") from None

MAX_INTERNAL_PACKAGES = 256
METADATA_TIMEOUT_SECONDS = 180

JsonObject = dict[str, object]


def contained_path(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("internal Rust source path resolves outside workspace")
    return resolved


def binding_manifest(root: Path, source: Path) -> Path:
    source = contained_path(root, source)
    if source.is_file():
        manifest = source
    else:
        project = source / "pyproject.toml"
        if not project.is_file():
            raise ValueError("workspace-closure input has no pyproject.toml")
        configuration = cast("JsonObject", tomllib.loads(project.read_text()))
        tool = cast("JsonObject", configuration.get("tool", {}))
        maturin = cast("JsonObject", tool.get("maturin", {}))
        relative = cast("str", maturin.get("manifest-path", "Cargo.toml"))
        manifest = source / relative
    manifest = contained_path(root, manifest)
    if not manifest.is_file():
        raise ValueError("internal Rust dependency manifest is missing")
    return manifest


def maturin_configuration(root: Path, source: Path, manifest: Path, workspace_root: Path) -> JsonObject:
    if source.is_dir():
        project = source / "pyproject.toml"
    else:
        project = manifest.parent / "pyproject.toml"
        for parent in manifest.parents:
            if not parent.is_relative_to(workspace_root.parent):
                break
            candidate = parent / "pyproject.toml"
            if candidate.is_file():
                project = candidate
                break
    if not project.is_file():
        return {}
    project = contained_path(root, project)
    configuration = cast("JsonObject", tomllib.loads(project.read_text()))
    tool = cast("JsonObject", configuration.get("tool", {}))
    return cast("JsonObject", tool.get("maturin", {}))


def maturin_feature_arguments(configuration: JsonObject) -> list[str]:
    for key in ("config", "unstable-flags"):
        if configuration.get(key):
            raise ValueError("workspace-closure does not support Maturin " + key + " overrides")
    features = configuration.get("features", [])
    if not isinstance(features, list) or any(not isinstance(feature, str) for feature in features):
        raise ValueError("workspace-closure supports only plain Maturin feature names")
    arguments = []
    for feature in cast("list[str]", features):
        arguments.extend(("--features", feature))
    for key in ("all-features", "no-default-features", "frozen", "locked"):
        value = configuration.get(key, False)
        if not isinstance(value, bool):
            raise ValueError("Maturin resolution switches must be booleans")
        if value:
            arguments.append("--" + key)
    return arguments


def metadata(
    manifest: Path,
    *,
    cwd: Path,
    no_dependencies: bool,
    locked: bool = False,
    feature_arguments: tuple[str, ...] = (),
) -> JsonObject:
    arguments = ["cargo", "metadata", "--format-version", "1", "--manifest-path", str(manifest)]
    arguments.extend(feature_arguments)
    if no_dependencies:
        arguments.append("--no-deps")
    if locked and "--locked" not in arguments and "--frozen" not in arguments:
        arguments.append("--locked")
    result = subprocess.run(
        arguments, cwd=cwd, capture_output=True, text=True, check=False, timeout=METADATA_TIMEOUT_SECONDS
    )
    if result.returncode:
        raise ValueError("Cargo metadata rejected source dependencies: " + result.stderr)
    return cast("JsonObject", json.loads(result.stdout))


def selected_package(document: JsonObject, manifest: Path) -> JsonObject:
    candidates = cast("list[JsonObject]", document["packages"])
    packages = [item for item in candidates if Path(cast("str", item["manifest_path"])).resolve() == manifest]
    if len(packages) != 1:
        raise ValueError("Cargo metadata must identify exactly one binding package")
    return packages[0]


def local_dependencies(root: Path, package: JsonObject) -> list[tuple[JsonObject, Path]]:
    result = []
    for dependency in cast("list[JsonObject]", package["dependencies"]):
        if dependency.get("path") is None:
            continue
        manifest = contained_path(root, Path(cast("str", dependency["path"])) / "Cargo.toml")
        if not manifest.is_file():
            raise ValueError("internal Rust dependency manifest is missing")
        result.append((dependency, manifest))
    return result


def packaged_assets(root: Path, package: JsonObject) -> None:
    origin = Path(cast("str", package["manifest_path"])).parent
    for field in ("readme", "license_file"):
        value = package.get(field)
        if value is None:
            continue
        asset = contained_path(root, origin / cast("str", value))
        if not asset.is_file():
            raise ValueError("packaged Rust metadata asset is missing")


def reachable_package_ids(document: JsonObject, selected_id: str) -> set[str]:
    resolve = cast("JsonObject", document.get("resolve", {}))
    nodes = {cast("str", node["id"]): node for node in cast("list[JsonObject]", resolve.get("nodes", []))}
    pending = [selected_id]
    visited = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        if current not in nodes:
            raise ValueError("Cargo resolved graph is missing a selected dependency node")
        visited.add(current)
        dependencies = cast("list[JsonObject]", nodes[current]["deps"])
        pending.extend(cast("str", dependency["pkg"]) for dependency in dependencies)
    return visited


def resolved_local_packages(root: Path, document: JsonObject, declared_manifests: set[Path], selected_id: str) -> int:
    ids = reachable_package_ids(document, selected_id)
    local_count = 0
    for package in cast("list[JsonObject]", document["packages"]):
        if package["id"] not in ids or package.get("source") is not None:
            continue
        manifest = contained_path(root, Path(cast("str", package["manifest_path"])))
        if not manifest.is_file():
            raise ValueError("resolved internal Rust dependency manifest is missing")
        if manifest not in declared_manifests:
            raise ValueError("workspace-closure does not support local Cargo source overrides")
        packaged_assets(root, package)
        local_dependencies(root, package)
        local_count += 1
    if not local_count:
        raise ValueError("Cargo resolved no local packages for source archive validation")
    return local_count


def validate_closure(root: Path, manifest: Path, cwd: Path, source: Path) -> dict[str, int]:
    pending: list[tuple[Path, str | None]] = [(manifest, None)]
    visited = set()
    path_count = 0
    workspace_root = None
    while pending:
        current, expected_name = pending.pop()
        current = contained_path(root, current)
        document = metadata(current, cwd=cwd, no_dependencies=True)
        if current == manifest:
            workspace_root = contained_path(root, Path(cast("str", document["workspace_root"])))
        package = selected_package(document, current)
        packaged_assets(root, package)
        if expected_name is not None and package["name"] != expected_name:
            raise ValueError("internal Rust dependency package name does not match its declaration")
        if current in visited:
            continue
        visited.add(current)
        if len(visited) > MAX_INTERNAL_PACKAGES:
            raise ValueError("internal Rust dependency closure exceeds package limit")
        dependencies = local_dependencies(root, package)
        path_count += len(dependencies)
        pending.extend((path, cast("str", dependency["name"])) for dependency, path in dependencies)
    if workspace_root is None:
        raise ValueError("Cargo metadata did not identify a workspace root")
    configuration = maturin_configuration(root, source, manifest, workspace_root)
    features = tuple(maturin_feature_arguments(configuration))
    resolved = metadata(
        manifest,
        cwd=cwd,
        no_dependencies=False,
        locked=(workspace_root / "Cargo.lock").is_file(),
        feature_arguments=features,
    )
    resolve = cast("JsonObject", resolved.get("resolve", {}))
    nodes = cast("list[JsonObject]", resolve.get("nodes", []))
    if not nodes:
        raise ValueError("Cargo resolved no packages for source archive validation")
    local_count = resolved_local_packages(
        root, resolved, visited, cast("str", selected_package(resolved, manifest)["id"])
    )
    return {
        "internal_packages": len(visited),
        "declared_path_dependencies": path_count,
        "resolved_packages": len(nodes),
        "resolved_local_packages": local_count,
    }


def main() -> int:
    try:
        root = Path(sys.argv[1]).resolve()
        source = contained_path(root, root / sys.argv[2])
        manifest = binding_manifest(root, source)
        cwd = root if source.is_file() else source
        print(json.dumps(validate_closure(root, manifest, cwd, source)))
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
