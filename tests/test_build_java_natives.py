"""Tests for build-java-natives/scripts/build.py and its musl_builder helper.

build.py is loaded with `musl_builder` pre-seeded into sys.modules rather than by putting its
scripts dir on sys.path. Three actions ship a file named `musl_builder.py`: this one and
build-csharp-natives are byte-identical, but build-elixir-natives' copy takes a fourth parameter
-- `build_in_docker(crate_name, target, manifest_path, env_vars)` against this copy's
`(crate_name, target, env_vars)` -- and calls it positionally. They all compete for the single
`sys.modules["musl_builder"]` slot, so whichever test module imports first owns it; were the
elixir copy to win, a positional call here would bind `env_vars` to `manifest_path` and the test
would stay green while exercising the wrong helper. ~keep
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "build-java-natives" / "scripts"

_INPUT_ENV_VARS = (
    "INPUT_TARGET",
    "INPUT_CRATE_NAME",
    "INPUT_LIB_NAME",
    "INPUT_CLASSIFIER",
    "INPUT_OUTPUT_DIR",
    "INPUT_DRY_RUN",
    "INPUT_GLIBC_VERSION",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_build_module(musl_module):
    spec = importlib.util.spec_from_file_location("build_java_natives", _SCRIPTS_DIR / "build.py")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("musl_builder")
    sys.modules["musl_builder"] = musl_module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("musl_builder", None)
        else:
            sys.modules["musl_builder"] = previous
    return module


musl_mod = _load_module("build_java_natives_musl_builder", _SCRIPTS_DIR / "musl_builder.py")
build_mod = _load_build_module(musl_mod)


@pytest.fixture
def clean_inputs(monkeypatch):
    for name in _INPUT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _read_outputs(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        entries[key] = value
    return entries


def _record_builder(monkeypatch) -> list[tuple]:
    recorded: list[tuple] = []
    monkeypatch.setattr(build_mod, "run_cargo_build", lambda *args: recorded.append(args))
    return recorded


def _record_subprocess(monkeypatch) -> list[tuple[list[str], dict]]:
    recorded: list[tuple[list[str], dict]] = []

    def fake_run(cmd, **kwargs):
        recorded.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(musl_mod.subprocess, "run", fake_run)
    return recorded


def _env_flag_values(docker_cmd: list[str], key: str) -> list[str]:
    prefix = f"{key}="
    return [
        docker_cmd[index + 1]
        for index, token in enumerate(docker_cmd[:-1])
        if token == "-e" and docker_cmd[index + 1].startswith(prefix)
    ]


def test_library_filename_should_use_bare_dll_when_target_is_windows():
    assert build_mod.library_filename("xberg_ffi", "x86_64-pc-windows-msvc") == "xberg_ffi.dll"


def test_library_filename_should_use_lib_prefixed_dylib_when_target_is_apple():
    assert build_mod.library_filename("xberg_ffi", "aarch64-apple-darwin") == "libxberg_ffi.dylib"


def test_library_filename_should_use_lib_prefixed_so_when_target_is_linux_gnu():
    assert build_mod.library_filename("xberg_ffi", "x86_64-unknown-linux-gnu") == "libxberg_ffi.so"


def test_library_filename_should_use_lib_prefixed_so_when_target_is_linux_musl():
    assert build_mod.library_filename("xberg_ffi", "aarch64-unknown-linux-musl") == "libxberg_ffi.so"


def test_cargo_release_dir_should_nest_release_under_the_target_triple():
    assert build_mod.cargo_release_dir("x86_64-unknown-linux-gnu") == Path("target/x86_64-unknown-linux-gnu/release")


def test_write_github_output_should_append_without_truncating_existing_entries(tmp_path, monkeypatch):
    sink = tmp_path / "github_output.txt"
    sink.write_text("existing=1\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(sink))

    build_mod.write_github_output("library-path", "/staged/libxberg_ffi.so")

    assert sink.read_text(encoding="utf-8") == "existing=1\nlibrary-path=/staged/libxberg_ffi.so\n"


def test_write_github_output_should_fall_back_to_stdout_when_env_var_is_unset(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    build_mod.write_github_output("staging-dir", "/staged")

    assert capsys.readouterr().out == "staging-dir=/staged\n"


def test_ensure_input_should_return_the_value_when_it_is_non_empty():
    assert build_mod.ensure_input("INPUT_TARGET", "x86_64-unknown-linux-gnu") == "x86_64-unknown-linux-gnu"


def test_ensure_input_should_exit_with_code_1_when_the_value_is_empty(capsys):
    with pytest.raises(SystemExit) as excinfo:
        build_mod.ensure_input("INPUT_TARGET", "")

    assert excinfo.value.code == 1
    assert capsys.readouterr().err == "Error: INPUT_TARGET is required\n"


def test_main_should_exit_with_code_1_when_target_input_is_missing(clean_inputs, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")

    with pytest.raises(SystemExit) as excinfo:
        build_mod.main()

    assert excinfo.value.code == 1


def test_main_should_exit_with_code_1_when_classifier_input_is_missing(clean_inputs, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")

    with pytest.raises(SystemExit) as excinfo:
        build_mod.main()

    assert excinfo.value.code == 1


def test_main_should_stage_a_marked_placeholder_and_emit_both_outputs_when_dry_run(
    clean_inputs, monkeypatch, tmp_path, github_output
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")

    build_mod.main()

    staged = tmp_path / "dist" / "java-natives" / "native" / "linux-x86_64" / "libxberg_ffi.so"
    assert staged.read_bytes() == build_mod.DRY_RUN_PLACEHOLDER
    assert b"dry-run" in build_mod.DRY_RUN_PLACEHOLDER
    assert _read_outputs(github_output) == {
        "library-path": str(staged.resolve()),
        "staging-dir": str(staged.parent.resolve()),
    }


def test_the_dry_run_placeholder_should_be_rejected_by_the_java_staging_gate(
    clean_inputs, monkeypatch, tmp_path, github_output, capsys
):
    """A zero-byte dry-run artifact used to clear every downstream check and could ship in a JAR."""
    stage_mod = _load_module(
        "stage_java_natives_from_build_test",
        Path(__file__).resolve().parents[1] / "stage-java-natives" / "scripts" / "stage.py",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    build_mod.main()

    artifacts_dir = tmp_path / "dist" / "java-natives"
    resources_dir = tmp_path / "resources"
    staged = stage_mod.stage_libs(stage_mod.discover_libs(artifacts_dir), resources_dir)

    with pytest.raises(SystemExit) as excinfo:
        stage_mod.verify_required(staged, resources_dir, ["linux-x86_64"], "xberg_ffi")

    assert excinfo.value.code == 1
    assert "carries no ELF/Mach-O/PE magic" in capsys.readouterr().err


def test_main_should_not_invoke_the_builder_when_dry_run(clean_inputs, monkeypatch, tmp_path, github_output):
    monkeypatch.chdir(tmp_path)
    recorded = _record_builder(monkeypatch)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")
    monkeypatch.setenv("INPUT_DRY_RUN", "TRUE")

    build_mod.main()

    assert recorded == []


def test_main_should_treat_a_non_true_dry_run_value_as_a_real_build(clean_inputs, monkeypatch, tmp_path, github_output):
    monkeypatch.chdir(tmp_path)
    release_dir = tmp_path / "target" / "x86_64-unknown-linux-gnu" / "release"
    release_dir.mkdir(parents=True)
    (release_dir / "libxberg_ffi.so").write_bytes(b"ELF")
    recorded = _record_builder(monkeypatch)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")
    monkeypatch.setenv("INPUT_DRY_RUN", "yes")

    build_mod.main()

    assert recorded == [("xberg-ffi", "x86_64-unknown-linux-gnu", "")]


def test_main_should_copy_the_built_library_into_the_classifier_staging_dir(
    clean_inputs, monkeypatch, tmp_path, github_output
):
    monkeypatch.chdir(tmp_path)
    release_dir = tmp_path / "target" / "aarch64-apple-darwin" / "release"
    release_dir.mkdir(parents=True)
    (release_dir / "libxberg_ffi.dylib").write_bytes(b"MACHO-PAYLOAD")
    recorded = _record_builder(monkeypatch)
    monkeypatch.setenv("INPUT_TARGET", "aarch64-apple-darwin")
    monkeypatch.setenv("INPUT_CLASSIFIER", "darwin-aarch64")
    monkeypatch.setenv("INPUT_OUTPUT_DIR", "out")

    build_mod.main()

    staged = tmp_path / "out" / "native" / "darwin-aarch64" / "libxberg_ffi.dylib"
    assert staged.read_bytes() == b"MACHO-PAYLOAD"
    assert recorded == [("xberg-ffi", "aarch64-apple-darwin", "")]
    assert _read_outputs(github_output) == {
        "library-path": str(staged.resolve()),
        "staging-dir": str(staged.parent.resolve()),
    }


def test_main_should_derive_the_lib_name_from_the_crate_name_when_lib_name_is_empty(
    clean_inputs, monkeypatch, tmp_path, github_output
):
    monkeypatch.chdir(tmp_path)
    release_dir = tmp_path / "target" / "x86_64-unknown-linux-gnu" / "release"
    release_dir.mkdir(parents=True)
    (release_dir / "libmy_own_ffi.so").write_bytes(b"ELF")
    _record_builder(monkeypatch)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")
    monkeypatch.setenv("INPUT_CRATE_NAME", "my-own-ffi")
    monkeypatch.setenv("INPUT_OUTPUT_DIR", "out")

    build_mod.main()

    assert (tmp_path / "out" / "native" / "linux-x86_64" / "libmy_own_ffi.so").read_bytes() == b"ELF"


def test_main_should_prefer_an_explicit_lib_name_over_the_crate_name(
    clean_inputs, monkeypatch, tmp_path, github_output
):
    monkeypatch.chdir(tmp_path)
    release_dir = tmp_path / "target" / "x86_64-unknown-linux-gnu" / "release"
    release_dir.mkdir(parents=True)
    (release_dir / "libexplicit_name.so").write_bytes(b"ELF")
    recorded = _record_builder(monkeypatch)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")
    monkeypatch.setenv("INPUT_CRATE_NAME", "my-own-ffi")
    monkeypatch.setenv("INPUT_LIB_NAME", "explicit_name")
    monkeypatch.setenv("INPUT_OUTPUT_DIR", "out")

    build_mod.main()

    assert (tmp_path / "out" / "native" / "linux-x86_64" / "libexplicit_name.so").is_file()
    assert recorded == [("my-own-ffi", "x86_64-unknown-linux-gnu", "")]


def test_main_should_forward_the_glibc_version_to_the_builder(clean_inputs, monkeypatch, tmp_path, github_output):
    monkeypatch.chdir(tmp_path)
    release_dir = tmp_path / "target" / "x86_64-unknown-linux-gnu" / "release"
    release_dir.mkdir(parents=True)
    (release_dir / "libxberg_ffi.so").write_bytes(b"ELF")
    recorded = _record_builder(monkeypatch)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")
    monkeypatch.setenv("INPUT_GLIBC_VERSION", "2.28")
    monkeypatch.setenv("INPUT_OUTPUT_DIR", "out")

    build_mod.main()

    assert recorded == [("xberg-ffi", "x86_64-unknown-linux-gnu", "2.28")]


def test_main_should_exit_with_code_1_when_the_builder_produced_no_library(
    clean_inputs, monkeypatch, tmp_path, github_output, capsys
):
    monkeypatch.chdir(tmp_path)
    _record_builder(monkeypatch)
    monkeypatch.setenv("INPUT_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("INPUT_CLASSIFIER", "linux-x86_64")
    monkeypatch.setenv("INPUT_OUTPUT_DIR", "out")

    with pytest.raises(SystemExit) as excinfo:
        build_mod.main()

    assert excinfo.value.code == 1
    assert "target/x86_64-unknown-linux-gnu/release/libxberg_ffi.so" in capsys.readouterr().err
    assert github_output.read_text(encoding="utf-8") == ""


def test_is_musl_target_should_be_true_for_a_linux_musl_triple():
    assert musl_mod.is_musl_target("aarch64-unknown-linux-musl") is True


def test_is_musl_target_should_be_false_for_a_linux_gnu_triple():
    assert musl_mod.is_musl_target("x86_64-unknown-linux-gnu") is False


def test_is_musl_target_should_be_false_for_a_windows_triple():
    assert musl_mod.is_musl_target("x86_64-pc-windows-msvc") is False


def test_get_alpine_arch_should_map_aarch64_triples_to_aarch64():
    assert musl_mod.get_alpine_arch("aarch64-unknown-linux-musl") == "aarch64"


def test_get_alpine_arch_should_map_arm64_triples_to_aarch64():
    assert musl_mod.get_alpine_arch("arm64-unknown-linux-musl") == "aarch64"


def test_get_alpine_arch_should_map_x86_64_triples_to_x86_64():
    assert musl_mod.get_alpine_arch("x86_64-unknown-linux-musl") == "x86_64"


def test_get_alpine_arch_should_raise_value_error_for_an_arch_alpine_does_not_ship():
    with pytest.raises(ValueError, match="Unsupported musl target for Alpine: riscv64gc-unknown-linux-musl"):
        musl_mod.get_alpine_arch("riscv64gc-unknown-linux-musl")


def test_build_in_docker_should_raise_value_error_when_the_target_is_not_musl(monkeypatch):
    recorded = _record_subprocess(monkeypatch)

    with pytest.raises(ValueError, match="Docker build is only for musl targets, got x86_64-unknown-linux-gnu"):
        musl_mod.build_in_docker("xberg-ffi", "x86_64-unknown-linux-gnu")

    assert recorded == []


def test_build_in_docker_should_raise_value_error_before_running_docker_for_an_unsupported_arch(monkeypatch):
    recorded = _record_subprocess(monkeypatch)

    with pytest.raises(ValueError, match="Unsupported musl target for Alpine"):
        musl_mod.build_in_docker("xberg-ffi", "riscv64gc-unknown-linux-musl")

    assert recorded == []


def test_build_in_docker_should_mount_the_cwd_and_run_cargo_in_the_alpine_image(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_in_docker("xberg-ffi", "aarch64-unknown-linux-musl")

    (docker_cmd, kwargs) = recorded[0]
    assert len(recorded) == 1
    assert docker_cmd[:3] == ["docker", "run", "--rm"]
    assert docker_cmd[3:5] == ["--platform", "linux/aarch64"]
    assert docker_cmd[5:7] == ["-v", f"{tmp_path.resolve()}:/src"]
    assert docker_cmd[7:9] == ["-w", "/src"]
    assert docker_cmd[-4:-1] == ["rust:1.100.0-alpine3.24", "sh", "-c"]
    assert kwargs == {"check": True}


@pytest.mark.parametrize(
    ("target", "expected_platform"),
    [
        ("aarch64-unknown-linux-musl", "linux/aarch64"),
        ("x86_64-unknown-linux-musl", "linux/x86_64"),
    ],
)
def test_build_in_docker_should_pin_the_image_platform_to_the_target_arch(
    monkeypatch, tmp_path, target, expected_platform
):
    """The image must match the requested target, not the runner: else the host gcc links it."""
    monkeypatch.chdir(tmp_path)
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_in_docker("xberg-ffi", target)

    docker_cmd = recorded[0][0]
    assert docker_cmd[docker_cmd.index("--platform") + 1] == expected_platform


def test_build_in_docker_should_install_the_target_and_pin_gcc_as_the_linker_in_the_container_script(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_in_docker("xberg-ffi", "aarch64-unknown-linux-musl")

    script = recorded[0][0][-1]
    assert "rustup target add aarch64-unknown-linux-musl" in script
    assert (
        "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=gcc "
        "cargo build --locked -p xberg-ffi --release --target aarch64-unknown-linux-musl" in script
    )


def test_build_in_docker_should_disable_crt_static_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_in_docker("xberg-ffi", "x86_64-unknown-linux-musl")

    assert _env_flag_values(recorded[0][0], "RUSTFLAGS") == ["RUSTFLAGS=-C target-feature=-crt-static"]


def test_build_in_docker_should_let_a_caller_supplied_rustflags_replace_the_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_in_docker("xberg-ffi", "x86_64-unknown-linux-musl", {"RUSTFLAGS": "-C opt-level=z"})

    assert _env_flag_values(recorded[0][0], "RUSTFLAGS") == ["RUSTFLAGS=-C opt-level=z"]


def test_build_in_docker_should_forward_extra_env_vars_to_the_container(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_in_docker("xberg-ffi", "x86_64-unknown-linux-musl", {"PKG_CONFIG_ALLOW_CROSS": "1"})

    assert _env_flag_values(recorded[0][0], "PKG_CONFIG_ALLOW_CROSS") == ["PKG_CONFIG_ALLOW_CROSS=1"]


def test_build_in_docker_should_propagate_the_failure_when_the_container_build_exits_non_zero(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def failing_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(2, cmd)

    monkeypatch.setattr(musl_mod.subprocess, "run", failing_run)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        musl_mod.build_in_docker("xberg-ffi", "x86_64-unknown-linux-musl")

    assert excinfo.value.returncode == 2


def test_build_or_fallback_should_delegate_musl_targets_to_the_docker_builder(monkeypatch):
    recorded: list[tuple] = []
    monkeypatch.setattr(musl_mod, "build_in_docker", lambda *args: recorded.append(args))
    subprocess_calls = _record_subprocess(monkeypatch)

    musl_mod.build_or_fallback("xberg-ffi", "x86_64-unknown-linux-musl", env_vars={"CUSTOM": "1"})

    assert recorded == [("xberg-ffi", "x86_64-unknown-linux-musl", {"CUSTOM": "1"})]
    assert subprocess_calls == []


def test_build_or_fallback_should_use_zigbuild_with_a_glibc_suffixed_target_for_gnu_with_a_floor(monkeypatch):
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_or_fallback("xberg-ffi", "x86_64-unknown-linux-gnu", glibc_version="2.28")

    assert recorded[0][0] == [
        "cargo",
        "zigbuild",
        "--locked",
        "-p",
        "xberg-ffi",
        "--release",
        "--target",
        "x86_64-unknown-linux-gnu.2.28",
    ]


def test_build_or_fallback_should_use_plain_cargo_build_for_gnu_without_a_glibc_floor(monkeypatch):
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_or_fallback("xberg-ffi", "x86_64-unknown-linux-gnu")

    assert recorded[0][0] == [
        "cargo",
        "build",
        "--locked",
        "-p",
        "xberg-ffi",
        "--release",
        "--target",
        "x86_64-unknown-linux-gnu",
    ]


def test_build_or_fallback_should_ignore_the_glibc_floor_for_a_non_gnu_target(monkeypatch):
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_or_fallback("xberg-ffi", "aarch64-apple-darwin", glibc_version="2.28")

    assert recorded[0][0] == [
        "cargo",
        "build",
        "--locked",
        "-p",
        "xberg-ffi",
        "--release",
        "--target",
        "aarch64-apple-darwin",
    ]


def test_build_or_fallback_should_append_the_manifest_path_when_one_is_given(monkeypatch):
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_or_fallback("xberg-ffi", "aarch64-apple-darwin", manifest_path=Path("crates/ffi/Cargo.toml"))

    assert recorded[0][0][-2:] == ["--manifest-path", "crates/ffi/Cargo.toml"]


def test_build_or_fallback_should_layer_env_vars_on_top_of_the_inherited_environment(monkeypatch):
    monkeypatch.setenv("A_PREEXISTING_MARKER", "inherited")
    recorded = _record_subprocess(monkeypatch)

    musl_mod.build_or_fallback("xberg-ffi", "aarch64-apple-darwin", env_vars={"CARGO_TERM_COLOR": "never"})

    env = recorded[0][1]["env"]
    assert env["CARGO_TERM_COLOR"] == "never"
    assert env["A_PREEXISTING_MARKER"] == "inherited"
    assert env["PATH"] == os.environ["PATH"]
