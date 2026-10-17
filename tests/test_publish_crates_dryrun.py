import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-crates" / "scripts" / "publish.py"
_DIAGNOSTIC = "DRYRUN_REJECTED_SENTINEL: package verification rejected"

_SPEC = importlib.util.spec_from_file_location("publish_crates_dryrun", _SCRIPT_PATH)
_PUBLISH_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PUBLISH_MODULE)


@pytest.fixture
def dry_run(tmp_path):
    if os.name == "nt":
        pytest.skip("The cargo executable fixture uses a POSIX shebang")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    manifests = {}
    for name in ("crate-a", "crate-b"):
        manifest = tmp_path / name / "Cargo.toml"
        manifest.parent.mkdir()
        manifest.write_text(f'[package]\nname = "{name}"\nversion = "1.2.3"\n')
        manifests[name] = str(manifest)
    cargo = fake_bin / "cargo"
    cargo.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        'with open(os.environ["CARGO_LEDGER"], "a") as ledger:\n'
        '    ledger.write(json.dumps(args) + "\\n")\n'
        'if args == ["metadata", "--format-version", "1", "--no-deps"]:\n'
        '    print(json.dumps({"packages": [{"name": n, "version": "1.2.3", "manifest_path": p} '
        'for n, p in json.loads(os.environ["FIXTURE_MANIFESTS"]).items()]}))\n'
        'elif args[:1] == ["publish"] and "--dry-run" in args:\n'
        '    crate = args[args.index("-p") + 1]\n'
        '    if crate == os.environ.get("FAIL_CRATE"):\n'
        f"        print({_DIAGNOSTIC!r}, file=sys.stderr)\n"
        "        raise SystemExit(37)\n"
        '    print("DRYRUN_SUCCESS_SENTINEL: " + crate)\n'
        "else:\n"
        '    raise SystemExit("UNEXPECTED_CARGO_COMMAND: " + repr(args))\n'
    )
    cargo.chmod(0o755)

    def invoke(fail_crate="", crates="crate-a"):
        ledger = tmp_path / "ledger.jsonl"
        env = {
            "PATH": str(fake_bin),
            "INPUT_DRY_RUN": "true",
            "INPUT_CRATES": crates,
            "INPUT_VERSION": "1.2.3",
            "CARGO_LEDGER": str(ledger),
            "FIXTURE_MANIFESTS": json.dumps(manifests),
            "FAIL_CRATE": fail_crate,
        }
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        calls = [json.loads(line) for line in ledger.read_text().splitlines()]
        assert calls[0] == ["metadata", "--format-version", "1", "--no-deps"]
        return result, calls[1:]

    return invoke


def test_dry_run_accepts_successful_package(dry_run):
    result, calls = dry_run()
    assert result.returncode == 0
    assert "DRYRUN_SUCCESS_SENTINEL: crate-a\n" in result.stdout
    assert calls == [["publish", "-p", "crate-a", "--dry-run"]]


def test_dry_run_returns_failure_when_package_verification_fails(dry_run):
    result, calls = dry_run(fail_crate="crate-a")
    assert calls == [["publish", "-p", "crate-a", "--dry-run"]]
    assert result.returncode == 37


def test_dry_run_reports_cargo_failure_diagnostic(dry_run):
    result, calls = dry_run(fail_crate="crate-a")
    assert calls == [["publish", "-p", "crate-a", "--dry-run"]]
    assert _DIAGNOSTIC in result.stdout + result.stderr


def test_dry_run_stops_before_next_crate_after_failure(dry_run):
    result, calls = dry_run(fail_crate="crate-a", crates="crate-a crate-b")
    assert calls == [["publish", "-p", "crate-a", "--dry-run"]]
    assert result.returncode == 37


@pytest.fixture
def publish_module(monkeypatch, tmp_path):
    module = _PUBLISH_MODULE
    packages = []
    for name in ("crate-a", "crate-b"):
        manifest = tmp_path / name / "Cargo.toml"
        manifest.parent.mkdir()
        manifest.write_text(f'[package]\nname = "{name}"\nversion = "1.2.3"\n')
        packages.append({"name": name, "version": "1.2.3", "manifest_path": str(manifest)})
    first_manifest = Path(packages[0]["manifest_path"])
    first_manifest.write_text(first_manifest.read_text() + '\n[dependencies]\ncrate-b = { path = "../crate-b" }\n')
    original = first_manifest.read_bytes()

    def metadata(command, **kwargs):
        assert command == ["cargo", "metadata", "--format-version", "1", "--no-deps"]
        assert kwargs == {"capture_output": True, "text": True, "check": False}
        return subprocess.CompletedProcess(command, 0, json.dumps({"packages": packages}), "")

    monkeypatch.setattr(module.subprocess, "run", metadata)
    monkeypatch.setenv("INPUT_CRATES", "crate-a crate-b")
    monkeypatch.setenv("INPUT_VERSION", "1.2.3")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    monkeypatch.setenv("INPUT_MANIFEST_PATH", "")
    return module, first_manifest, original


def test_main_dry_run_retains_success_output_and_restores_manifest(publish_module, monkeypatch, capsys):
    module, manifest, original = publish_module
    calls = []

    def publish(command):
        calls.append(command)
        if len(calls) == 1:
            assert 'version = "1.2.3"' in manifest.read_text().split("[dependencies]")[1]
        return 0, "DRYRUN_SUCCESS_SENTINEL\n"

    monkeypatch.setattr(module, "_run", publish)
    module.main()
    captured = capsys.readouterr()
    assert calls == [
        ["cargo", "publish", "-p", "crate-a", "--dry-run", "--allow-dirty"],
        ["cargo", "publish", "-p", "crate-b", "--dry-run"],
    ]
    assert captured.out.count("DRYRUN_SUCCESS_SENTINEL\n") == 2
    assert captured.err == ""
    assert manifest.read_bytes() == original


def test_main_dry_run_reports_failure_stops_and_restores_manifest(publish_module, monkeypatch, capsys):
    module, manifest, original = publish_module
    calls = []

    def publish(command):
        calls.append(command)
        if len(calls) == 1:
            assert 'version = "1.2.3"' in manifest.read_text().split("[dependencies]")[1]
        return 37, _DIAGNOSTIC + "\n"

    monkeypatch.setattr(module, "_run", publish)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    captured = capsys.readouterr()
    assert exc_info.value.code == 37
    assert calls == [["cargo", "publish", "-p", "crate-a", "--dry-run", "--allow-dirty"]]
    assert captured.err == _DIAGNOSTIC + "\n"
    assert "All crates published successfully" not in captured.out
    assert manifest.read_bytes() == original
