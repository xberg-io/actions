import hashlib
import importlib.util
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "build-go-ffi" / "scripts" / "build.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


go_mod = _import_script("build_go_ffi", _SCRIPT_PATH)

_ENV_VARS = (
    "INPUT_TARGET",
    "INPUT_CRATE_NAME",
    "INPUT_LIB_NAME",
    "INPUT_HEADER_PATH",
    "INPUT_OUTPUT_DIR",
    "INPUT_ARCHIVE_NAME",
    "INPUT_DRY_RUN",
    "INPUT_GLIBC_VERSION",
    "GITHUB_OUTPUT",
)

LINUX_TARGET = "x86_64-unknown-linux-gnu"

SHA256_OF_HELLO = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


@pytest.fixture
def isolated_env(tmp_path, monkeypatch) -> Path:
    """Run from an empty cwd with no inherited INPUT_*/GITHUB_OUTPUT."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def output_sink(isolated_env, monkeypatch) -> Path:
    """GITHUB_OUTPUT pointed at a fresh file; depends on isolated_env so it wins the ordering."""
    sink = isolated_env / "github_output.txt"
    sink.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(sink))
    return sink


@pytest.fixture
def recorded_commands(monkeypatch) -> list[list[str]]:
    """Replace subprocess.run with a recorder so no real cargo/zig toolchain is required."""
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(
            list(cmd), 0, stdout="", stderr="note: native-static-libs: -lpthread -ldl -lm\n"
        )

    monkeypatch.setattr(go_mod.subprocess, "run", fake_run)
    return calls


def _install_runner(monkeypatch, calls: list[list[str]], on_build: Callable[[], None] | None = None) -> None:
    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if on_build is not None:
            on_build()
        return subprocess.CompletedProcess(
            list(cmd), 0, stdout="", stderr="note: native-static-libs: -lpthread -ldl -lm\n"
        )

    monkeypatch.setattr(go_mod.subprocess, "run", fake_run)


def _emit_libraries(
    root: Path,
    target: str,
    shared_filename: str | None,
    static_filename: str | None = None,
    payload: bytes = b"\x7fELF" + b"\x00" * 60,
):
    """Return a callback that drops the libraries cargo would have produced for ``target``."""

    def build() -> None:
        release_dir = root / "target" / target / "release"
        release_dir.mkdir(parents=True, exist_ok=True)
        if shared_filename is not None:
            (release_dir / shared_filename).write_bytes(payload)
        if static_filename is not None:
            (release_dir / static_filename).write_bytes(b"!<arch>\n")

    return build


def _set_inputs(monkeypatch, **inputs: str) -> None:
    for key, value in inputs.items():
        monkeypatch.setenv(f"INPUT_{key.upper()}", value)


def _write_header(root: Path, name: str = "xberg.h") -> Path:
    header = root / "include" / name
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text("#pragma once\n", encoding="utf-8")
    return header


def _cargo_rustc_command(crate_name: str, target: str) -> list[str]:
    return [
        "cargo",
        "rustc",
        "--locked",
        "-p",
        crate_name,
        "--release",
        "--lib",
        "--target",
        target,
        "--",
        "--print",
        "native-static-libs",
    ]


def test_should_use_a_dll_name_when_the_target_is_windows():
    assert go_mod.library_filename("xberg_ffi", "x86_64-pc-windows-msvc") == "xberg_ffi.dll"


def test_should_use_a_dylib_name_when_the_target_is_apple():
    assert go_mod.library_filename("xberg_ffi", "aarch64-apple-darwin") == "libxberg_ffi.dylib"


def test_should_use_an_so_name_when_the_target_is_linux_gnu():
    assert go_mod.library_filename("xberg_ffi", LINUX_TARGET) == "libxberg_ffi.so"


def test_should_use_an_so_name_when_the_target_is_linux_musl():
    assert go_mod.library_filename("xberg_ffi", "aarch64-unknown-linux-musl") == "libxberg_ffi.so"


def test_should_use_an_archive_name_for_unix_static_libraries():
    assert go_mod.static_library_filename("xberg_ffi", LINUX_TARGET) == "libxberg_ffi.a"


def test_should_use_a_lib_name_for_windows_static_libraries():
    assert go_mod.static_library_filename("xberg_ffi", "x86_64-pc-windows-msvc") == "xberg_ffi.lib"


def test_should_place_artifacts_under_target_triple_release():
    assert go_mod.cargo_release_dir(LINUX_TARGET) == Path("target") / LINUX_TARGET / "release"


def test_should_parse_the_last_native_static_libs_record():
    output = "noise\nnote: native-static-libs: -lold\nnote: native-static-libs: -lpthread -ldl -lm\n"

    assert go_mod.parse_native_static_libs(output) == "-lpthread -ldl -lm"


def test_should_run_plain_cargo_build_when_no_glibc_floor_is_requested(recorded_commands):
    go_mod.run_cargo_build("xberg-ffi", LINUX_TARGET)

    assert recorded_commands == [_cargo_rustc_command("xberg-ffi", LINUX_TARGET)]


def test_should_run_zigbuild_with_a_suffixed_triple_when_a_glibc_floor_is_requested(recorded_commands):
    go_mod.run_cargo_build("xberg-ffi", LINUX_TARGET, "2.28")

    assert recorded_commands == [
        [
            "cargo",
            "zigbuild",
            "--locked",
            "-p",
            "xberg-ffi",
            "--release",
            "--lib",
            "--target",
            f"{LINUX_TARGET}.2.28",
        ]
    ]


def test_should_ignore_the_glibc_floor_when_the_target_is_not_linux_gnu(recorded_commands):
    """A musl or darwin triple has no glibc to lower — suffixing it would make cargo reject the triple."""
    go_mod.run_cargo_build("xberg-ffi", "aarch64-unknown-linux-musl", "2.28")

    assert recorded_commands == [
        [
            "cargo",
            "rustc",
            "--locked",
            "-p",
            "xberg-ffi",
            "--release",
            "--lib",
            "--target",
            "aarch64-unknown-linux-musl",
            "--",
            "--print",
            "native-static-libs",
        ]
    ]


def test_should_hash_a_file_that_fits_in_one_chunk(tmp_path):
    target = tmp_path / "payload.bin"
    target.write_bytes(b"hello")

    assert go_mod.compute_sha256(target) == SHA256_OF_HELLO


def test_should_hash_a_file_spanning_several_chunks(tmp_path):
    """The read loop is chunked; a multi-chunk file proves no chunk is dropped or double-counted."""
    payload = bytes(range(256)) * ((go_mod.CHUNK_SIZE * 2 // 256) + 3)
    target = tmp_path / "big.bin"
    target.write_bytes(payload)

    assert len(payload) > go_mod.CHUNK_SIZE * 2
    assert go_mod.compute_sha256(target) == hashlib.sha256(payload).hexdigest()


def test_should_append_to_the_github_output_file_when_the_sink_is_set(github_output):
    github_output.write_text("archive-path=/old\n", encoding="utf-8")

    go_mod.write_github_output("archive-sha256", SHA256_OF_HELLO)

    assert github_output.read_text(encoding="utf-8") == f"archive-path=/old\narchive-sha256={SHA256_OF_HELLO}\n"


def test_should_write_to_stdout_when_github_output_is_unset(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    go_mod.write_github_output("archive-sha256", "")

    assert capsys.readouterr().out == "archive-sha256=\n"


def test_should_return_the_value_when_a_required_input_is_present():
    assert go_mod.ensure_input("INPUT_TARGET", LINUX_TARGET) == LINUX_TARGET


def test_should_exit_one_when_a_required_input_is_empty(capsys):
    with pytest.raises(SystemExit) as exc_info:
        go_mod.ensure_input("INPUT_TARGET", "")

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == "Error: INPUT_TARGET is required\n"


def test_should_copy_the_libraries_link_metadata_and_header_into_the_staging_directory(tmp_path):
    library = tmp_path / "libxberg_ffi.so"
    library.write_bytes(b"\x7fELF")
    static_library = tmp_path / "libxberg_ffi.a"
    static_library.write_bytes(b"!<arch>\n")
    native_static_libs = tmp_path / "native-static-libs.txt"
    native_static_libs.write_text("-lpthread -ldl -lm\n", encoding="utf-8")
    header = _write_header(tmp_path)
    staging = tmp_path / "stage"

    go_mod.stage_artifacts(library, static_library, native_static_libs, header, staging)

    assert sorted(p.name for p in staging.iterdir()) == [
        "libxberg_ffi.a",
        "libxberg_ffi.so",
        "native-static-libs.txt",
        "xberg.h",
    ]
    assert (staging / "libxberg_ffi.so").read_bytes() == b"\x7fELF"
    assert (staging / "libxberg_ffi.a").read_bytes() == b"!<arch>\n"
    assert (staging / "native-static-libs.txt").read_text(encoding="utf-8") == "-lpthread -ldl -lm\n"
    assert (staging / "xberg.h").read_text(encoding="utf-8") == "#pragma once\n"


def test_should_discard_stale_contents_when_the_staging_directory_already_exists(tmp_path):
    """A rerun must not ship a library left over from a previous target."""
    library = tmp_path / "libxberg_ffi.so"
    library.write_bytes(b"\x7fELF")
    header = _write_header(tmp_path)
    staging = tmp_path / "stage"
    staging.mkdir()
    (staging / "libstale.so").write_bytes(b"stale")

    go_mod.stage_artifacts(library, None, None, header, staging)

    assert sorted(p.name for p in staging.iterdir()) == ["libxberg_ffi.so", "xberg.h"]


def test_should_create_an_archive_rooted_at_the_staging_directory_name(tmp_path):
    staging = tmp_path / "xberg_ffi-x86_64-unknown-linux-gnu"
    staging.mkdir()
    (staging / "libxberg_ffi.so").write_bytes(b"\x7fELF")
    (staging / "xberg.h").write_text("#pragma once\n", encoding="utf-8")
    archive = tmp_path / "dist" / "go-ffi" / "bundle.tar.gz"

    go_mod.create_archive(archive, staging)

    with tarfile.open(archive) as tar:
        assert sorted(tar.getnames()) == [
            "xberg_ffi-x86_64-unknown-linux-gnu",
            "xberg_ffi-x86_64-unknown-linux-gnu/libxberg_ffi.so",
            "xberg_ffi-x86_64-unknown-linux-gnu/xberg.h",
        ]


def test_should_exit_one_when_the_target_input_is_missing(isolated_env, recorded_commands, capsys):
    with pytest.raises(SystemExit) as exc_info:
        go_mod.main()

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == "Error: INPUT_TARGET is required\n"
    assert recorded_commands == []


def test_should_skip_the_build_and_emit_an_empty_digest_when_dry_run(
    output_sink, monkeypatch, recorded_commands, capsys
):
    _set_inputs(monkeypatch, target=LINUX_TARGET, dry_run="true")

    go_mod.main()

    assert recorded_commands == []
    expected_archive = (Path("dist/go-ffi") / f"xberg_ffi-{LINUX_TARGET}.tar.gz").resolve()
    assert output_sink.read_text(encoding="utf-8") == f"archive-path={expected_archive}\narchive-sha256=\n"
    out = capsys.readouterr().out
    assert "[build-go-ffi] dry-run: skipping cargo build" in out
    assert "glibc-version" not in out


def test_should_report_the_glibc_floor_in_the_dry_run_plan(output_sink, monkeypatch, recorded_commands, capsys):
    _set_inputs(monkeypatch, target=LINUX_TARGET, dry_run="true", glibc_version="2.28")

    go_mod.main()

    assert "  glibc-version: 2.28" in capsys.readouterr().out


def test_should_not_require_the_header_to_exist_when_dry_run(output_sink, monkeypatch, recorded_commands):
    _set_inputs(monkeypatch, target=LINUX_TARGET, dry_run="true", header_path="nowhere/missing.h")

    go_mod.main()

    assert recorded_commands == []
    assert output_sink.read_text(encoding="utf-8").endswith("archive-sha256=\n")


def test_should_exit_one_before_building_when_the_header_is_missing(
    output_sink, monkeypatch, recorded_commands, capsys
):
    _set_inputs(monkeypatch, target=LINUX_TARGET, header_path="include/absent.h")

    with pytest.raises(SystemExit) as exc_info:
        go_mod.main()

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == "Error: header not found at include/absent.h\n"
    assert recorded_commands == []
    assert output_sink.read_text(encoding="utf-8") == ""


def test_should_exit_one_when_cargo_produced_no_library(isolated_env, output_sink, monkeypatch, capsys):
    _write_header(isolated_env)
    calls: list[list[str]] = []
    _install_runner(monkeypatch, calls)
    _set_inputs(monkeypatch, target=LINUX_TARGET, header_path="include/xberg.h")

    with pytest.raises(SystemExit) as exc_info:
        go_mod.main()

    assert exc_info.value.code == 1
    expected = Path("target") / LINUX_TARGET / "release" / "libxberg_ffi.so"
    assert capsys.readouterr().err.endswith(f"Error: built library not found at {expected}\n")
    assert len(calls) == 1
    assert output_sink.read_text(encoding="utf-8") == ""


def test_should_package_shared_and_static_libraries_and_emit_a_matching_digest(isolated_env, output_sink, monkeypatch):
    _write_header(isolated_env)
    calls: list[list[str]] = []
    _install_runner(
        monkeypatch,
        calls,
        _emit_libraries(isolated_env, LINUX_TARGET, "libxberg_ffi.so", "libxberg_ffi.a"),
    )
    _set_inputs(monkeypatch, target=LINUX_TARGET, header_path="include/xberg.h")

    go_mod.main()

    archive = isolated_env / "dist" / "go-ffi" / f"xberg_ffi-{LINUX_TARGET}.tar.gz"
    digest = go_mod.compute_sha256(archive)
    assert output_sink.read_text(encoding="utf-8") == f"archive-path={archive.resolve()}\narchive-sha256={digest}\n"

    with tarfile.open(archive) as tar:
        assert sorted(tar.getnames()) == [
            f"xberg_ffi-{LINUX_TARGET}",
            f"xberg_ffi-{LINUX_TARGET}/libxberg_ffi.a",
            f"xberg_ffi-{LINUX_TARGET}/libxberg_ffi.so",
            f"xberg_ffi-{LINUX_TARGET}/native-static-libs.txt",
            f"xberg_ffi-{LINUX_TARGET}/xberg.h",
        ]


def test_should_derive_the_library_name_from_the_crate_name_when_lib_name_is_unset(
    isolated_env, output_sink, monkeypatch
):
    _write_header(isolated_env)
    calls: list[list[str]] = []
    _install_runner(monkeypatch, calls, _emit_libraries(isolated_env, LINUX_TARGET, "libcrawlberg_ffi.so"))
    _set_inputs(monkeypatch, target=LINUX_TARGET, crate_name="crawlberg-ffi", header_path="include/xberg.h")

    go_mod.main()

    assert calls == [_cargo_rustc_command("crawlberg-ffi", LINUX_TARGET)]
    assert (isolated_env / "dist" / "go-ffi" / f"crawlberg_ffi-{LINUX_TARGET}.tar.gz").is_file()


def test_should_prefer_an_explicit_lib_name_over_the_crate_name(isolated_env, output_sink, monkeypatch):
    _write_header(isolated_env)
    calls: list[list[str]] = []
    _install_runner(monkeypatch, calls, _emit_libraries(isolated_env, LINUX_TARGET, "libxberg.so"))
    _set_inputs(
        monkeypatch,
        target=LINUX_TARGET,
        crate_name="crawlberg-ffi",
        lib_name="xberg",
        header_path="include/xberg.h",
    )

    go_mod.main()

    assert calls[0][calls[0].index("-p") + 1] == "crawlberg-ffi"
    assert (isolated_env / "dist" / "go-ffi" / f"xberg-{LINUX_TARGET}.tar.gz").is_file()


def test_should_honour_an_explicit_archive_name(isolated_env, output_sink, monkeypatch):
    _write_header(isolated_env)
    calls: list[list[str]] = []
    _install_runner(monkeypatch, calls, _emit_libraries(isolated_env, LINUX_TARGET, "libxberg_ffi.so"))
    _set_inputs(
        monkeypatch,
        target=LINUX_TARGET,
        header_path="include/xberg.h",
        output_dir="artifacts",
        archive_name="go-bundle.tar.gz",
    )

    go_mod.main()

    archive = isolated_env / "artifacts" / "go-bundle.tar.gz"
    assert archive.is_file()
    assert output_sink.read_text(encoding="utf-8").splitlines()[0] == f"archive-path={archive.resolve()}"


def test_should_package_a_dylib_when_the_target_is_apple(isolated_env, output_sink, monkeypatch):
    """The staged filename comes from the target triple, never from the host platform."""
    apple_target = "aarch64-apple-darwin"
    _write_header(isolated_env)
    calls: list[list[str]] = []
    _install_runner(monkeypatch, calls, _emit_libraries(isolated_env, apple_target, "libxberg_ffi.dylib"))
    _set_inputs(monkeypatch, target=apple_target, header_path="include/xberg.h")

    go_mod.main()

    with tarfile.open(isolated_env / "dist" / "go-ffi" / f"xberg_ffi-{apple_target}.tar.gz") as tar:
        assert f"xberg_ffi-{apple_target}/libxberg_ffi.dylib" in tar.getnames()


def test_should_package_a_static_only_musl_archive(isolated_env, output_sink, monkeypatch):
    musl_target = "x86_64-unknown-linux-musl"
    _write_header(isolated_env)
    calls: list[list[str]] = []
    _install_runner(monkeypatch, calls, _emit_libraries(isolated_env, musl_target, None, "libxberg_ffi.a"))
    _set_inputs(monkeypatch, target=musl_target, header_path="include/xberg.h")

    go_mod.main()

    with tarfile.open(isolated_env / "dist" / "go-ffi" / f"xberg_ffi-{musl_target}.tar.gz") as tar:
        names = tar.getnames()
        assert f"xberg_ffi-{musl_target}/libxberg_ffi.a" in names
        assert f"xberg_ffi-{musl_target}/libxberg_ffi.so" not in names
        assert f"xberg_ffi-{musl_target}/native-static-libs.txt" in names


def test_should_use_zigbuild_for_a_glibc_floor_but_read_the_unsuffixed_release_dir(
    isolated_env, output_sink, monkeypatch
):
    """zigbuild takes triple.glibc but still emits into target/<base-triple>/release."""
    _write_header(isolated_env)
    calls: list[list[str]] = []
    _install_runner(monkeypatch, calls, _emit_libraries(isolated_env, LINUX_TARGET, "libxberg_ffi.so"))
    _set_inputs(monkeypatch, target=LINUX_TARGET, header_path="include/xberg.h", glibc_version="2.28")

    go_mod.main()

    assert calls == [
        [
            "cargo",
            "zigbuild",
            "--locked",
            "-p",
            "xberg-ffi",
            "--release",
            "--lib",
            "--target",
            f"{LINUX_TARGET}.2.28",
        ]
    ]
    assert (isolated_env / "dist" / "go-ffi" / f"xberg_ffi-{LINUX_TARGET}.tar.gz").is_file()


def test_should_propagate_the_failure_when_cargo_exits_non_zero(isolated_env, output_sink, monkeypatch):
    _write_header(isolated_env)

    def failing_run(cmd, **_kwargs):
        raise subprocess.CalledProcessError(101, list(cmd))

    monkeypatch.setattr(go_mod.subprocess, "run", failing_run)
    _set_inputs(monkeypatch, target=LINUX_TARGET, header_path="include/xberg.h")

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        go_mod.main()

    assert exc_info.value.returncode == 101
    assert output_sink.read_text(encoding="utf-8") == ""
