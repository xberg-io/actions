"""Exercise the actual manylinux provisioning shell without running native builds."""

import os
import shutil
import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_BASH = shutil.which("bash")
assert _BASH is not None, "the native provisioning contract requires Bash"


def _native_script() -> str:
    data = yaml.safe_load((_ROOT / "build-python-wheels/action.yml").read_text())
    steps = [step for step in data["runs"]["steps"] if step.get("name") == "Build wheels"]
    assert len(steps) == 1
    shell = steps[0]["env"]["CIBW_BEFORE_ALL_LINUX"]
    start = shell.index('if [ "$BUILD_LIBHEIF" = "true" ]')
    return shell[start:]


def test_corrupt_native_source_is_rejected_before_extraction(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "dnf": "exit 0",
        "curl": 'while [ "$1" != -o ]; do shift; done; printf corrupt >"$2"',
        "tar": 'touch "$COMMAND_LOG"; exit 99',
        "cmake": "exit 99",
    }
    for name, body in commands.items():
        executable = bin_dir / name
        executable.write_text(f"#!/bin/sh\n{body}\n")
        executable.chmod(0o755)
    marker = tmp_path / "extract-called"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "BUILD_LIBHEIF": "true"}
    env.update(TMPDIR=str(tmp_path), COMMAND_LOG=str(marker), CMAKE_BUILD_PARALLEL_LEVEL="1")
    # ~keep The historical inline script used container-global /tmp paths; isolate its negative control too.
    script = _native_script().replace("/tmp/", f"{tmp_path}/")
    result = subprocess.run([_BASH, "-c", script], env=env, text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "FAILED" in result.stdout + result.stderr
    assert not marker.exists(), "corrupt native source reached tar before its checksum was rejected"


def test_disabled_native_stack_does_not_install_or_build(tmp_path: Path) -> None:
    result = subprocess.run(
        [_BASH, "-c", _native_script()],
        env={**os.environ, "BUILD_LIBHEIF": "false", "PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_verified_native_stack_builds_three_packages_with_one_job_each(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "cmake.log"
    digest_log = tmp_path / "digests.log"
    commands = {
        "dnf": "exit 0",
        "curl": 'while [ "$1" != -o ]; do shift; done; printf archive >"$2"',
        "sha256sum": 'cat >>"$DIGEST_LOG"',
        "tar": "exit 0",
        "cmake": 'printf "%s\\n" "$*" >>"$COMMAND_LOG"',
        "ldconfig": "exit 0",
        "pkg-config": (
            'case "$2" in libheif) echo 1.23.7 ;; libde265) echo 1.1.3 ;; aom) echo 3.15.2 ;; *) exit 2 ;; esac'
        ),
    }
    for name, body in commands.items():
        executable = bin_dir / name
        executable.write_text(f"#!/bin/sh\n{body}\n")
        executable.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "BUILD_LIBHEIF": "true"}
    env.update(TMPDIR=str(tmp_path), COMMAND_LOG=str(log), DIGEST_LOG=str(digest_log), CMAKE_BUILD_PARALLEL_LEVEL="1")
    result = subprocess.run([_BASH, "-c", _native_script()], env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert len(calls) == 9
    builds = [line for line in calls if line.startswith("--build ")]
    assert len(builds) == 3
    assert all(line.endswith(" -j1") for line in builds)
    assert {Path(line.split()[1]).name for line in builds} == {"libde265-build", "libaom-build", "libheif-build"}
    digests = digest_log.read_text().splitlines()
    assert len(digests) == 3
    assert {line.split()[0] for line in digests} == {
        "554228bd17788c99a7e63b37ab5634722190e6e2bf60c1dcb01cef328e133905",
        "67bb54b245f33ed98600e08269e6139986e48114e14042474ddd8885801dfddc",
        "f7483e818503ea6224c8863e4a56ac02c7089021a98472c811c12aa19faf2475",
    }


def test_native_runtime_ci_qualifies_both_runtime_versions_on_main_only() -> None:
    workflow = yaml.safe_load((_ROOT / ".github/workflows/test-native-runtime.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert "pull_request" not in triggers
    assert triggers["push"]["branches"] == ["main"]
    jobs = workflow["jobs"]
    assert set(jobs) == {"runtime", "windows-tools", "macos-ocr"}
    job = jobs["runtime"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["strategy"]["matrix"]["version"] == ["1.19.8", "1.23.7"]
    provision = [step for step in job["steps"] if step.get("uses") == "./install-system-deps"]
    assert len(provision) == 1
    assert provision[0]["with"]["libheif-version"] == "${{ matrix.version }}"


def test_real_linux_wheel_build_exercises_source_codecs_and_decoding() -> None:
    workflow = yaml.safe_load((_ROOT / ".github/workflows/test-build-python-wheels.yml").read_text())
    job = workflow["jobs"]["test"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    builds = [step for step in job["steps"] if step.get("uses") == "./build-python-wheels"]
    assert len(builds) == 1
    options = builds[0]["with"]
    assert options["build-libheif"] == "${{ runner.os == 'Linux' && 'true' || 'false' }}"
    command = options["cibw-before-build-linux"]
    assert "verify_heif_runtime.py" in command
    assert "--library /usr/local/lib/libheif.so.1" in command
    assert "--version 1.23.7 --require-codec-prefix /usr/local/lib" in command


def test_real_runtime_fixture_gate_rejects_corrupt_upstream_archive(tmp_path: Path, monkeypatch) -> None:
    import io

    from tests.native import verify_heif_runtime

    monkeypatch.setattr(verify_heif_runtime.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(b"corrupt"))
    try:
        verify_heif_runtime.materialize_examples(tmp_path)
    except RuntimeError as error:
        assert str(error) == "source archive checksum mismatch"
    else:
        raise AssertionError("corrupt archive was accepted")
    assert list(tmp_path.iterdir()) == []
