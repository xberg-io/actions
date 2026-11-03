"""Require a real hosted GNU ARM acceptance lane for the managed cross linker."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/test-build-node-napi.yml"


def test_gnu_arm_lane_builds_and_loads_the_canonical_target_without_ignoring_failures():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert "test" in workflow["jobs"]
    assert "gnu-arm" in workflow["jobs"], "missing GNU ARM build/ELF/Node acceptance job"
    job = workflow["jobs"]["gnu-arm"]
    assert job["runs-on"] == "ubuntu-24.04-arm"
    assert job.get("continue-on-error", False) is False
    assert job.get("if", True) is True
    assert job["env"]["RUSTFLAGS"] == "-D warnings"
    steps = job["steps"]
    rust = next(s for s in steps if s.get("uses") == "dtolnay/rust-toolchain@v1")
    assert rust["with"]["toolchain"] == "1.99.1"
    build = next(s for s in steps if s.get("uses") == "./build-node-napi")
    assert build["with"]["target"] == "aarch64-unknown-linux-gnu"
    assert build["with"]["use-napi-cross"] == "true"
    assert build.get("continue-on-error", False) is False
    verify = next(s for s in steps if s.get("name") == "Verify ARM ELF, glibc floor and actual Node API")
    assert verify.get("continue-on-error", False) is False
    assert verify.get("if", True) is True
    assert "verify-gnu-arm.py" in verify["run"]
    assert "linux-arm64-gnu/fixture-arm.linux-arm64-gnu.node" in verify["run"]


def load_verifier():
    import importlib.util

    path = ROOT / "build-node-napi/scripts/verify-gnu-arm.py"
    spec = importlib.util.spec_from_file_location("gnu_arm_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_elf_gate_reads_architecture_and_object_kind_from_actual_bytes(tmp_path):
    import struct

    import pytest

    verifier = load_verifier()
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", header, 16, 3, 183)
    artifact = tmp_path / "fixture.node"
    artifact.write_bytes(header)
    verifier.verify_header(artifact)
    struct.pack_into("<HH", header, 16, 3, 62)
    artifact.write_bytes(header)
    with pytest.raises(ValueError, match="AArch64 ELF shared object"):
        verifier.verify_header(artifact)


def test_glibc_gate_rejects_zero_work_newer_versions_and_private_requirements():
    import pytest

    verifier = load_verifier()
    assert verifier.verify_versions("Name: GLIBC_2.17 Name: GLIBC_2.2.5") == ["GLIBC_2.17", "GLIBC_2.2.5"]
    for report, reason in [
        ("No version information found", "no GLIBC version-symbol"),
        ("Name: GLIBC_2.18", "exceeds 2.17"),
        ("Name: GLIBC_2.9 Name: GLIBC_2.34", "exceeds 2.17"),
        ("Name: GLIBC_PRIVATE", "unsupported GLIBC"),
    ]:
        with pytest.raises(ValueError, match=reason):
            verifier.verify_versions(report)


def test_api_gate_calls_real_node_and_rejects_wrong_results_or_missing_exports(tmp_path):
    import subprocess

    import pytest

    verifier = load_verifier()
    module = tmp_path / "addon.cjs"
    module.write_text("exports.add = (a,b) => a+b;\n")
    verifier.verify_api(module)
    for source in ["exports.add = () => 41;", "exports.other = () => 42;"]:
        module.write_text(source)
        with pytest.raises(subprocess.CalledProcessError):
            verifier.verify_api(module)


def test_command_line_verifier_requires_both_binary_checks_and_the_loader(tmp_path, monkeypatch):
    import struct
    import subprocess
    import sys

    import pytest

    verifier = load_verifier()
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", header, 16, 3, 183)
    artifact = tmp_path / "fixture.node"
    artifact.write_bytes(header)
    monkeypatch.setattr(sys, "argv", ["verify-gnu-arm.py", str(artifact)])
    calls = []
    fixture = {"report": "Name: GLIBC_2.17"}

    def run(argv, **kwargs):
        assert kwargs["check"] is True
        calls.append(argv)
        if argv[0] == "readelf":
            return subprocess.CompletedProcess(argv, 0, stdout=fixture["report"])
        assert argv[:2] == ["node", "--eval"]
        assert "addon.add(20, 22), 42" in argv[2]
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(verifier.subprocess, "run", run)
    verifier.main()
    assert [argv[0] for argv in calls] == ["readelf", "node"]
    for report in ["No version information", "Name: GLIBC_2.34"]:
        fixture["report"] = report
        calls.clear()
        with pytest.raises(ValueError, match="GLIBC"):
            verifier.main()
        assert [argv[0] for argv in calls] == ["readelf"]


def assert_cross_tool_locks(config, lock):
    assert config["tools"]["zig"] == "0.17.0"
    assert config["tools"]["github:rust-cross/cargo-zigbuild"] == "0.24.0"
    for tool in ["zig", "github:rust-cross/cargo-zigbuild"]:
        rows = lock["tools"][tool]
        assert len(rows) == 1
        assert rows[0]["version"] == config["tools"][tool]
        for platform in config["settings"]["lockfile_platforms"]:
            record = rows[0][f"platforms.{platform}"]
            assert record["url"].startswith("https://")
            assert record["checksum"].startswith("sha256:")
            assert len(record["checksum"].removeprefix("sha256:")) == 64


def test_both_managed_cross_tools_have_real_platform_locks_without_an_env_only_pin():
    import copy
    import tomllib

    import pytest

    config = tomllib.loads((ROOT / "mise.toml").read_text())
    lock = tomllib.loads((ROOT / "mise.lock").read_text())
    assert_cross_tool_locks(config, lock)
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["gnu-arm"]
    assert "MISE_ZIG_VERSION" not in job["env"]
    setup = next(s for s in job["steps"] if s.get("name") == "Install managed ARM acceptance tools")
    assert set(setup["with"]["install-args"].split()) == {
        "node",
        "pnpm",
        "python",
        "zig",
        "github:rust-cross/cargo-zigbuild",
    }
    missing = copy.deepcopy(lock)
    del missing["tools"]["zig"]
    with pytest.raises(KeyError, match="zig"):
        assert_cross_tool_locks(config, missing)
    missing_arm = copy.deepcopy(lock)
    del missing_arm["tools"]["zig"][0]["platforms.linux-arm64"]
    with pytest.raises(KeyError, match="linux-arm64"):
        assert_cross_tool_locks(config, missing_arm)
