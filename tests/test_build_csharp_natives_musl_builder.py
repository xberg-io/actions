"""Tests for build-csharp-natives/scripts/musl_builder.py.

Every cargo/docker invocation is recorded by an in-process double instead of being executed,
so nothing here depends on the host having docker, zig, cargo-zigbuild or any Rust target
installed. Split from test_build_csharp_natives.py only to stay under the file-length gate.
"""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "build-csharp-natives" / "scripts"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


musl_mod = _load_script("csharp_musl_builder_under_test", _SCRIPTS_DIR / "musl_builder.py")


class _Recorder:
    """A subprocess.run double that records argv and kwargs and always reports success."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.kwargs: list[dict] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        self.kwargs.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    """Record every subprocess the builder launches, from an empty working directory."""
    monkeypatch.chdir(tmp_path)
    recorded = _Recorder()
    monkeypatch.setattr(musl_mod.subprocess, "run", recorded)
    return recorded


def _docker_env_pairs(cmd: list[str]) -> list[str]:
    return [cmd[index + 1] for index, token in enumerate(cmd[:-1]) if token == "-e"]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("x86_64-unknown-linux-musl", True),
        ("aarch64-unknown-linux-musl", True),
        ("x86_64-unknown-linux-gnu", False),
        ("aarch64-unknown-linux-gnu", False),
        ("aarch64-apple-darwin", False),
        ("x86_64-pc-windows-msvc", False),
    ],
)
def test_should_classify_target_as_musl_when_triple_contains_linux_musl(target, expected):
    assert musl_mod.is_musl_target(target) is expected


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("aarch64-unknown-linux-musl", "aarch64"),
        ("arm64-unknown-linux-musl", "aarch64"),
        ("x86_64-unknown-linux-musl", "x86_64"),
    ],
)
def test_should_map_alpine_arch_when_musl_target_is_supported(target, expected):
    assert musl_mod.get_alpine_arch(target) == expected


@pytest.mark.parametrize("target", ["i686-unknown-linux-musl", "armv7-unknown-linux-musleabihf"])
def test_should_raise_value_error_when_musl_target_arch_is_unsupported(target):
    with pytest.raises(ValueError, match=target):
        musl_mod.get_alpine_arch(target)


def test_should_refuse_docker_build_and_run_nothing_when_target_is_not_musl(recorder):
    with pytest.raises(ValueError, match="x86_64-unknown-linux-gnu"):
        musl_mod.build_in_docker("xberg-ffi", "x86_64-unknown-linux-gnu")

    assert recorder.calls == []


def test_should_mount_cwd_and_pin_the_alpine_image_when_building_in_docker(recorder, tmp_path):
    musl_mod.build_in_docker("xberg-ffi", "x86_64-unknown-linux-musl")

    cmd = recorder.calls[0]
    assert cmd[:10] == [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/x86_64",
        "-v",
        f"{tmp_path.resolve()}:/src",
        "-w",
        "/src",
        "-e",
    ]
    assert "rust:1.100.0-alpine3.24" in cmd
    assert cmd[-3:-1] == ["sh", "-c"]
    assert recorder.kwargs[0] == {"check": True}


@pytest.mark.parametrize(
    ("target", "expected_platform"),
    [
        ("aarch64-unknown-linux-musl", "linux/aarch64"),
        ("arm64-unknown-linux-musl", "linux/aarch64"),
        ("x86_64-unknown-linux-musl", "linux/x86_64"),
    ],
)
def test_should_pin_the_image_platform_to_the_requested_target_when_building_in_docker(
    recorder, target, expected_platform
):
    """Without --platform docker pulls the host-arch image, so a cross build links with host gcc."""
    musl_mod.build_in_docker("xberg-ffi", target)

    cmd = recorder.calls[0]
    assert cmd[cmd.index("--platform") + 1] == expected_platform


def test_should_disable_crt_static_by_default_when_building_in_docker(recorder):
    musl_mod.build_in_docker("xberg-ffi", "x86_64-unknown-linux-musl")

    assert _docker_env_pairs(recorder.calls[0]) == ["RUSTFLAGS=-C target-feature=-crt-static"]


def test_should_let_the_caller_override_rustflags_when_building_in_docker(recorder):
    musl_mod.build_in_docker(
        "xberg-ffi",
        "x86_64-unknown-linux-musl",
        {"RUSTFLAGS": "-C opt-level=3", "ORT_LIB_LOCATION": "/opt/ort"},
    )

    assert _docker_env_pairs(recorder.calls[0]) == ["RUSTFLAGS=-C opt-level=3", "ORT_LIB_LOCATION=/opt/ort"]


def test_should_set_a_target_specific_linker_when_building_in_docker(recorder):
    musl_mod.build_in_docker("xberg-ffi", "aarch64-unknown-linux-musl")

    assert "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=gcc" in recorder.calls[0][-1]


def test_should_build_a_locked_release_of_the_named_crate_when_building_in_docker(recorder):
    musl_mod.build_in_docker("my-ffi", "x86_64-unknown-linux-musl")

    script = recorder.calls[0][-1]
    assert "cargo build --locked -p my-ffi --release --target x86_64-unknown-linux-musl" in script
    assert "rustup target add x86_64-unknown-linux-musl" in script


def test_should_route_to_docker_and_skip_cargo_when_target_is_musl(monkeypatch, recorder):
    docker_calls = []
    monkeypatch.setattr(musl_mod, "build_in_docker", lambda *args: docker_calls.append(args))

    musl_mod.build_or_fallback("xberg-ffi", "aarch64-unknown-linux-musl", env_vars={"K": "V"})

    assert docker_calls == [("xberg-ffi", "aarch64-unknown-linux-musl", {"K": "V"})]
    assert recorder.calls == []


def test_should_zigbuild_a_glibc_suffixed_target_when_gnu_target_has_a_glibc_version(recorder):
    musl_mod.build_or_fallback("xberg-ffi", "x86_64-unknown-linux-gnu", glibc_version="2.28")

    assert recorder.calls == [
        ["cargo", "zigbuild", "--locked", "-p", "xberg-ffi", "--release", "--target", "x86_64-unknown-linux-gnu.2.28"]
    ]


def test_should_use_plain_cargo_build_when_gnu_target_has_no_glibc_version(recorder):
    musl_mod.build_or_fallback("xberg-ffi", "x86_64-unknown-linux-gnu")

    assert recorder.calls == [
        ["cargo", "build", "--locked", "-p", "xberg-ffi", "--release", "--target", "x86_64-unknown-linux-gnu"]
    ]


@pytest.mark.parametrize("target", ["aarch64-apple-darwin", "x86_64-pc-windows-msvc"])
def test_should_not_suffix_or_zigbuild_when_target_is_not_gnu_despite_a_glibc_version(recorder, target):
    """A glibc floor is meaningless off glibc — suffixing would produce an unknown triple."""
    musl_mod.build_or_fallback("xberg-ffi", target, glibc_version="2.28")

    assert recorder.calls == [["cargo", "build", "--locked", "-p", "xberg-ffi", "--release", "--target", target]]


def test_should_append_the_manifest_path_when_building_natively(recorder):
    musl_mod.build_or_fallback(
        "xberg-ffi",
        "x86_64-unknown-linux-gnu",
        manifest_path=Path("crates/xberg-ffi/Cargo.toml"),
    )

    assert recorder.calls[0][-2:] == ["--manifest-path", "crates/xberg-ffi/Cargo.toml"]


def test_should_merge_caller_env_over_process_env_when_building_natively(monkeypatch, recorder):
    monkeypatch.setenv("BASELINE_MARKER", "from-process")
    monkeypatch.setenv("ORT_LIB_LOCATION", "/from/process")

    musl_mod.build_or_fallback("xberg-ffi", "x86_64-unknown-linux-gnu", env_vars={"ORT_LIB_LOCATION": "/from/caller"})

    env = recorder.kwargs[0]["env"]
    assert env["BASELINE_MARKER"] == "from-process"
    assert env["ORT_LIB_LOCATION"] == "/from/caller"


def test_should_propagate_the_failure_when_native_cargo_build_exits_non_zero(monkeypatch):
    def failing_run(cmd, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(101, cmd)
        return SimpleNamespace(returncode=101, stdout="", stderr="")

    monkeypatch.setattr(musl_mod.subprocess, "run", failing_run)

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        musl_mod.build_or_fallback("xberg-ffi", "x86_64-unknown-linux-gnu")

    assert exc_info.value.returncode == 101
