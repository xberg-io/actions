import os
import subprocess
from pathlib import Path

import yaml

_ACTION = Path(__file__).resolve().parents[1] / "publish-zig" / "action.yml"


def _package(tmp_path):
    action = yaml.safe_load(_ACTION.read_text())
    step = next(step for step in action["runs"]["steps"] if step.get("id") == "package-multi")
    package = tmp_path / "package"
    natives = tmp_path / "natives"
    package.mkdir()
    (package / "build.zig").write_text('const std = @import("std");\n')
    (package / "build.zig.zon").write_text('.{\n    .paths = .{\n        "src",\n    },\n}\n')
    (package / "src").mkdir()
    (package / "src" / "sample.zig").write_text('pub const c = @import("c");\n')
    (natives / "include").mkdir(parents=True)
    (natives / "include" / "sample.h").write_text("int sample_version(void);\n")
    for rid, library in (
        ("linux-x64", "libsample_ffi.so"),
        ("linux-arm64", "libsample_ffi.so"),
        ("osx-arm64", "libsample_ffi.dylib"),
        ("osx-x64", "libsample_ffi.dylib"),
    ):
        (natives / rid).mkdir()
        (natives / rid / library).write_bytes(b"platform-library")
    (natives / "win-x64").mkdir()
    (natives / "win-x64" / "sample_ffi.dll").write_bytes(b"shared-library")
    (natives / "win-x64" / "sample_ffi.lib").write_bytes(b"import-or-static-library")
    env = dict(
        os.environ,
        WORKING_DIR=str(package),
        FFI_DIR=str(natives),
        MODULE_NAME="sample",
        FFI_LIB_NAME="sample_ffi",
        PKG_NAME="sample",
        TAG="v1.0.0",
        RUNNER_TEMP=str(tmp_path),
        GITHUB_OUTPUT=str(tmp_path / "output"),
        FFI_HEADER_PATH="",
    )
    result = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return package


def test_should_expose_translated_c_module_in_distributed_build(tmp_path):
    package = _package(tmp_path)
    rendered = (package / "build.zig").read_text()
    assert 'b.path("include/sample.h")' in rendered
    assert 'module.addImport("c", translate_c.createModule());' in rendered
    assert (package / "include" / "sample.h").read_text() == "int sample_version(void);\n"


def test_should_bundle_windows_link_library_alongside_dll(tmp_path):
    package = _package(tmp_path)
    library = package / "lib" / "x86_64-windows-msvc" / "sample_ffi.lib"
    assert library.is_file(), "Windows link library was silently dropped"
    assert library.read_bytes() == b"import-or-static-library"


def test_should_preserve_libraries_for_every_supported_target(tmp_path):
    package = _package(tmp_path)
    libraries = package / "lib"
    observed = {
        path.relative_to(libraries).as_posix(): path.read_bytes() for path in libraries.rglob("*") if path.is_file()
    }
    assert observed == {
        "x86_64-linux-gnu/libsample_ffi.so": b"platform-library",
        "aarch64-linux-gnu/libsample_ffi.so": b"platform-library",
        "aarch64-darwin/libsample_ffi.dylib": b"platform-library",
        "x86_64-darwin/libsample_ffi.dylib": b"platform-library",
        "x86_64-windows-msvc/sample_ffi.dll": b"shared-library",
        "x86_64-windows-msvc/sample_ffi.lib": b"import-or-static-library",
    }
