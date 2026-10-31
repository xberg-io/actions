"""Exercise the action's managed ARM route and its Cargo subprocess boundary."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "build-node-napi"
ADAPTER = ACTION / "scripts/cargo-gnu17.cjs"


def executable(path, source):
    path.write_text(f"#!{sys.executable}\n" + source)
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def cargo(tmp_path):
    trace = tmp_path / "cargo.json"
    binary = executable(
        tmp_path / "cargo-real",
        "import json,os,sys\nfrom pathlib import Path\n"
        "Path(os.environ['TRACE']).write_text(json.dumps({'args':sys.argv[1:],"
        "'cargo':os.environ.get('CARGO'),'path':os.environ['PATH'],"
        "'rustflags':os.environ.get('RUSTFLAGS'),'encoded':os.environ.get('CARGO_ENCODED_RUSTFLAGS')}))\n"
        "sys.exit(int(os.environ.get('FIXTURE_EXIT','0')))\n",
    )
    return binary, trace


def action_step(
    tmp_path, cargo, *, target="aarch64-unknown-linux-gnu", use_cross="true", cross_compile="false", cargo_command=None
):
    binary, trace = cargo
    executable(
        tmp_path / "pnpm",
        "import json,os,subprocess,sys\nfrom pathlib import Path\n"
        "if 'create-npm-dirs' in sys.argv: sys.exit(0)\n"
        "Path(os.environ['NAPI_TRACE']).write_text(json.dumps(sys.argv[1:]))\n"
        "mode='zigbuild' if '-x' in sys.argv else 'build'\n"
        "sys.exit(subprocess.run([os.environ.get('CARGO','cargo'),mode,'--target',"
        "os.environ['TARGET'],'--release']).returncode)\n",
    )
    for name in ("zig", "cargo-zigbuild"):
        executable(tmp_path / name, "pass\n")
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "CARGO": cargo_command or binary,
        "TRACE": str(trace),
        "NAPI_TRACE": str(tmp_path / "napi.json"),
        "ACTION_PATH": str(ACTION),
        "TARGET": target,
        "USE_NAPI_CROSS": use_cross,
        "CROSS_COMPILE": cross_compile,
        "RELEASE": "true",
        "JS_NAME": "index.js",
        "DTS_NAME": "index.d.ts",
        "NPM_DIR": "npm",
        "COLLECT_ARTIFACTS": "false",
        "RUSTFLAGS": "-D warnings -C link-arg=-zrelro",
    }
    step = next(
        x
        for x in yaml.safe_load((ACTION / "action.yml").read_text())["runs"]["steps"]
        if x["name"] == "Build NAPI-RS bindings (target)"
    )
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=tmp_path, env=environment, capture_output=True, text=True, check=False
    )
    return result, environment


def test_action_uses_modern_arm_linker_without_changing_the_npm_target(tmp_path, cargo):
    result, env = action_step(tmp_path, cargo)
    assert result.returncode == 0, result.stdout + result.stderr
    args = json.loads((tmp_path / "napi.json").read_text())
    assert "-x" in args
    assert "--use-napi-cross" not in args
    assert args[args.index("--target") + 1] == "aarch64-unknown-linux-gnu"
    forwarded = json.loads(cargo[1].read_text())
    assert forwarded["args"] == ["zigbuild", "--target", "aarch64-unknown-linux-gnu.2.17", "--release"]
    assert forwarded["cargo"] == cargo[0]
    assert forwarded["path"] == env["PATH"]
    assert forwarded["rustflags"] == env["RUSTFLAGS"]


@pytest.mark.parametrize(
    "args", [["zigbuild", "--target", "aarch64-unknown-linux-gnu"], ["zigbuild", "--target=aarch64-unknown-linux-gnu"]]
)
def test_adapter_changes_only_the_zigbuild_target(tmp_path, cargo, args):
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": cargo[0], "TRACE": str(cargo[1]), "CARGO": str(ADAPTER)}
    result = subprocess.run(["node", str(ADAPTER), *args], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    forwarded = json.loads(cargo[1].read_text())
    assert "aarch64-unknown-linux-gnu.2.17" in " ".join(forwarded["args"])
    assert forwarded["cargo"] == cargo[0]


@pytest.mark.parametrize(
    "args", [["metadata", "--format-version", "1"], ["build", "--target", "x86_64-unknown-linux-gnu"]]
)
def test_other_cargo_commands_are_forwarded_unchanged(tmp_path, cargo, args):
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": cargo[0], "TRACE": str(cargo[1])}
    result = subprocess.run(["node", str(ADAPTER), *args], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(cargo[1].read_text())["args"] == args


@pytest.mark.parametrize(
    "override",
    [
        {"RUSTFLAGS": "-D warnings -Clinker=old-gcc"},
        {"CARGO_ENCODED_RUSTFLAGS": "-D\x1fwarnings\x1f-C\x1flinker=old-gcc"},
        {"CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER": "old-gcc"},
    ],
)
def test_explicit_linker_overrides_fail_before_cargo(tmp_path, cargo, override):
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": cargo[0], "TRACE": str(cargo[1]), **override}
    result = subprocess.run(
        ["node", str(ADAPTER), "zigbuild", "--target", "aarch64-unknown-linux-gnu"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "explicit linker override" in result.stderr
    assert not cargo[1].exists()


def test_encoded_flags_take_precedence_and_exit_status_is_preserved(tmp_path, cargo):
    env = {
        **os.environ,
        "XBERG_NAPI_REAL_CARGO": cargo[0],
        "TRACE": str(cargo[1]),
        "RUSTFLAGS": "-Clinker=ignored",
        "CARGO_ENCODED_RUSTFLAGS": "-D\x1fwarnings\x1f-C\x1flink-arg=-zrelro",
        "FIXTURE_EXIT": "23",
    }
    result = subprocess.run(
        ["node", str(ADAPTER), "zigbuild", "--target", "aarch64-unknown-linux-gnu"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 23, result.stderr
    assert json.loads(cargo[1].read_text())["encoded"] == env["CARGO_ENCODED_RUSTFLAGS"]


@pytest.mark.parametrize(
    "target,use_cross,cross_compile",
    [
        ("x86_64-unknown-linux-gnu", "true", "false"),
        ("aarch64-unknown-linux-gnu", "false", "false"),
        ("aarch64-unknown-linux-musl", "false", "true"),
    ],
)
def test_other_action_routes_keep_their_original_cargo_environment(tmp_path, cargo, target, use_cross, cross_compile):
    result, env = action_step(tmp_path, cargo, target=target, use_cross=use_cross, cross_compile=cross_compile)
    assert result.returncode == 0, result.stderr
    assert json.loads(cargo[1].read_text())["cargo"] == env["CARGO"]


@pytest.mark.parametrize("config", ["target.aarch64-unknown-linux-gnu.linker=old-gcc", "override.toml"])
def test_cli_config_cannot_override_the_managed_linker(tmp_path, cargo, config):
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": cargo[0], "TRACE": str(cargo[1])}
    result = subprocess.run(
        ["node", str(ADAPTER), "zigbuild", "--target", "aarch64-unknown-linux-gnu", "--config", config],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "explicit linker override" in result.stderr
    assert not cargo[1].exists()


def test_unrelated_config_and_empty_encoded_flags_remain_unchanged(tmp_path, cargo):
    env = {
        **os.environ,
        "XBERG_NAPI_REAL_CARGO": cargo[0],
        "TRACE": str(cargo[1]),
        "RUSTFLAGS": "-Clinker=ignored",
        "CARGO_ENCODED_RUSTFLAGS": "",
    }
    args = ["zigbuild", "--target", "aarch64-unknown-linux-gnu", "--config", 'build.warnings="deny"']
    result = subprocess.run(["node", str(ADAPTER), *args], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    row = json.loads(cargo[1].read_text())
    assert row["args"][-2:] == args[-2:]
    assert row["encoded"] == ""


@pytest.mark.parametrize(
    "args",
    [
        ["zigbuild"],
        ["zigbuild", "--target", "x86_64-unknown-linux-gnu"],
        ["zigbuild", "--target", "aarch64-unknown-linux-gnu", "--target", "aarch64-unknown-linux-gnu"],
    ],
)
def test_ambiguous_or_wrong_private_target_fails_closed(tmp_path, cargo, args):
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": cargo[0], "TRACE": str(cargo[1])}
    result = subprocess.run(["node", str(ADAPTER), *args], env=env, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "target" in result.stderr
    assert not cargo[1].exists()


def test_managed_tool_installation_is_scoped_and_uses_the_callers_mise_pins():
    steps = yaml.safe_load((ACTION / "action.yml").read_text())["runs"]["steps"]
    step = next(x for x in steps if x["name"] == "Install managed GNU ARM cross-link tools")
    assert (
        step["if"]
        == "inputs.use-napi-cross == 'true' && inputs.target == 'aarch64-unknown-linux-gnu' && inputs.cross-compile != 'true'"
    )
    assert step["uses"] == "xberg-io/actions/setup-mise@v1"
    assert step["with"] == {"install-args": "zig github:rust-cross/cargo-zigbuild"}


@pytest.mark.parametrize("key", ["CARGO_BUILD_RUSTFLAGS", "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_RUSTFLAGS"])
def test_fallback_cargo_rustflags_cannot_select_a_different_linker(tmp_path, cargo, key):
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": cargo[0], "TRACE": str(cargo[1]), key: "-Clinker=old-gcc"}
    env.pop("RUSTFLAGS", None)
    env.pop("CARGO_ENCODED_RUSTFLAGS", None)
    result = subprocess.run(
        ["node", str(ADAPTER), "zigbuild", "--target", "aarch64-unknown-linux-gnu"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "explicit linker override" in result.stderr
    assert not cargo[1].exists()


@pytest.mark.parametrize(
    "config",
    [
        'build.target-dir="target/linker-cache"',
        'build.target-dir="target/fuse-ld-cache"',
        '"build"."target-dir"="cache/linker"',
        'build.rustflags=["--cfg","linker_cache"]',
        'target.x86_64-unknown-linux-gnu.linker="unused-other-target"',
    ],
)
def test_unrelated_config_values_can_contain_linker_words(tmp_path, cargo, config):
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": cargo[0], "TRACE": str(cargo[1])}
    args = ["zigbuild", "--target", "aarch64-unknown-linux-gnu", "--config", config]
    result = subprocess.run(["node", str(ADAPTER), *args], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(cargo[1].read_text())["args"][-2:] == args[-2:]


@pytest.mark.parametrize(
    "config",
    [
        'target."aarch64-unknown-linux-gnu".linker="old-gcc"',
        'build.rustflags=["-C","linker=old-gcc"]',
        "build.rustflags='-D warnings -Clinker=old-gcc'",
        'target."aarch64-unknown-linux-gnu".rustflags=["-Clinker=old-gcc"]',
    ],
)
def test_quoted_linker_keys_and_rustflag_values_remain_rejected(tmp_path, cargo, config):
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": cargo[0], "TRACE": str(cargo[1])}
    result = subprocess.run(
        ["node", str(ADAPTER), "zigbuild", "--target", "aarch64-unknown-linux-gnu", "--config=" + config],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "explicit linker override" in result.stderr
    assert not cargo[1].exists()


def test_both_cross_modes_are_rejected_before_any_napi_or_cargo_call(tmp_path, cargo):
    result, _ = action_step(tmp_path, cargo, use_cross="true", cross_compile="true")
    assert result.returncode == 1
    assert "cross-compile and use-napi-cross are mutually exclusive" in result.stdout
    assert not cargo[1].exists()
    assert not (tmp_path / "napi.json").exists()


@pytest.mark.parametrize("signal_number", [signal.SIGUSR1, signal.SIGTERM])
def test_real_child_signals_produce_nonzero_conventional_status_without_self_signalling(tmp_path, signal_number):
    binary = executable(
        tmp_path / "cargo-signalled", "import os,signal\nos.kill(os.getpid(),int(os.environ['FIXTURE_SIGNAL']))\n"
    )
    env = {**os.environ, "XBERG_NAPI_REAL_CARGO": binary, "FIXTURE_SIGNAL": str(signal_number)}
    result = subprocess.run(
        ["node", "--inspect-port=0", str(ADAPTER), "metadata"], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 128 + signal_number, result.stderr
    assert "Debugger listening" not in result.stderr


def test_path_cargo_command_preserves_the_invocation_basename(tmp_path, cargo, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    alias = directory / "cargo"
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    alias.symlink_to(cargo[0])
    result, _ = action_step(tmp_path, cargo, cargo_command="cargo")
    assert result.returncode == 0, result.stderr
    assert json.loads(cargo[1].read_text())["cargo"] == str(alias)
