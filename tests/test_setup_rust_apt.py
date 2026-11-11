"""Exercise setup-rust shell steps at the external apt/protoc boundary."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_BASH = shutil.which("bash")
_TARGET = "x86_64-unknown-linux-musl"
_INSTALL_FAILURE = 42


def _tool(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def apt_boundary(tmp_path: Path):
    """Keep protoc off PATH until the fake package installation supplies it."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    log.write_text("")
    github_env = tmp_path / "github.env"
    github_env.write_text("")
    github_path = tmp_path / "github.path"
    github_path.write_text("")
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    for name in ("grep", "tr"):
        executable = shutil.which(name)
        assert executable is not None
        (bin_dir / name).symlink_to(executable)
    _tool(bin_dir, "sudo", 'import os, sys\nos.execv(os.path.join(os.environ["PATH"], sys.argv[1]), sys.argv[1:])')
    _tool(bin_dir, "uname", 'import os\nprint(os.environ.get("UNAME_TEST_MACHINE", "x86_64"))')
    _tool(
        bin_dir,
        "curl",
        """import os, sys
from pathlib import Path
with Path(os.environ["APT_TEST_LOG"]).open("a") as log:
    log.write("curl " + sys.argv[-1] + "\\n")
sys.exit(int(os.environ["CURL_TEST_CODE"]))
""",
    )
    _tool(
        bin_dir,
        "unzip",
        """import os, sys
from pathlib import Path
with Path(os.environ["APT_TEST_LOG"]).open("a") as log:
    log.write("unzip\\n")
bin_dir = Path(sys.argv[sys.argv.index("-d") + 1]) / "bin"
bin_dir.mkdir(parents=True)
path = bin_dir / "protoc"
path.write_text("#!" + sys.executable + "\\nimport os\\nfrom pathlib import Path\\n"
                "with Path(os.environ['APT_TEST_LOG']).open('a') as log: log.write('protoc --version\\\\n')\\n"
                "print('libprotoc 29.3')\\n")
path.chmod(0o755)
""",
    )
    _tool(bin_dir, "rustup", f'print("{_TARGET} (installed)")')
    _tool(
        bin_dir,
        "apt-get",
        """import os, sys
from pathlib import Path
with Path(os.environ["APT_TEST_LOG"]).open("a") as log:
    log.write("apt-get " + " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "update":
    sys.exit(int(os.environ["APT_TEST_UPDATE_CODE"]))
code = int(os.environ["APT_TEST_INSTALL_CODE"])
if code == 0 and os.environ["APT_TEST_PROVIDE_PROTOC"] == "1":
    path = Path(os.environ["PATH"]) / "protoc"
    path.write_text("#!" + sys.executable + "\\nimport os\\nfrom pathlib import Path\\n"
                    "with Path(os.environ['APT_TEST_LOG']).open('a') as log: log.write('protoc --version\\\\n')\\n"
                    "print('libprotoc 29.3')\\n")
    path.chmod(0o755)
sys.exit(code)
""",
    )
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "RUNNER_OS": "Linux",
        "GITHUB_ENV": str(github_env),
        "GITHUB_PATH": str(github_path),
        "RUNNER_TEMP": str(runner_temp),
        "CURL_TEST_CODE": "0",
        "APT_TEST_LOG": str(log),
        "APT_TEST_UPDATE_CODE": "100",
        "APT_TEST_INSTALL_CODE": "0",
        "APT_TEST_PROVIDE_PROTOC": "1",
    }
    return env, log, github_env


def _run_protoc(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    assert _BASH is not None
    action = yaml.safe_load((_ROOT / "setup-rust" / "action.yml").read_text())
    script = next(step["run"] for step in action["runs"]["steps"] if step.get("name") == "Install protoc")
    return subprocess.run(
        [_BASH, "-e", "-o", "pipefail", "-c", script], env=env, capture_output=True, text=True, check=False
    )


def _run_musl(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    assert _BASH is not None
    return subprocess.run(
        [_BASH, str(_ROOT / "setup-rust" / "scripts" / "add-target.sh"), _TARGET],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_protoc_installs_and_verifies_after_unrelated_index_failure(apt_boundary):
    env, log, _ = apt_boundary
    result = _run_protoc(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines() == [
        "apt-get update -y",
        "apt-get install -y --no-install-recommends protobuf-compiler libprotobuf-dev",
        "protoc --version",
    ]
    assert "libprotoc 29.3" in result.stdout


_APT_INSTALL = "apt-get install -y --no-install-recommends protobuf-compiler libprotobuf-dev"
_RELEASE = "https://github.com/protocolbuffers/protobuf/releases/download/v29.3/protoc-29.3-{}.zip"


@pytest.mark.parametrize("update_code", ["0", "100"])
def test_protoc_falls_back_to_the_release_zip_when_apt_fails(apt_boundary, update_code):
    env, log, _ = apt_boundary
    env.update(APT_TEST_UPDATE_CODE=update_code, APT_TEST_INSTALL_CODE=str(_INSTALL_FAILURE))
    result = _run_protoc(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines() == [
        "apt-get update -y",
        _APT_INSTALL,
        "curl " + _RELEASE.format("linux-x86_64"),
        "unzip",
        "protoc --version",
    ]
    assert Path(env["GITHUB_PATH"]).read_text().splitlines() == [str(Path(env["RUNNER_TEMP"]) / "protoc" / "bin")]


@pytest.mark.parametrize("machine", ["aarch64", "arm64"])
def test_protoc_release_zip_matches_the_runner_architecture(apt_boundary, machine):
    env, log, _ = apt_boundary
    env.update(APT_TEST_INSTALL_CODE=str(_INSTALL_FAILURE), UNAME_TEST_MACHINE=machine)
    result = _run_protoc(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "curl " + _RELEASE.format("linux-aarch_64") in log.read_text().splitlines()


def test_protoc_falls_back_to_the_release_zip_when_apt_leaves_it_off_path(apt_boundary):
    env, log, _ = apt_boundary
    env.update(APT_TEST_UPDATE_CODE="0", APT_TEST_PROVIDE_PROTOC="0")
    result = _run_protoc(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines()[-3:] == ["curl " + _RELEASE.format("linux-x86_64"), "unzip", "protoc --version"]


def test_protoc_release_zip_failure_after_apt_failure_remains_fatal(apt_boundary):
    env, log, _ = apt_boundary
    env.update(APT_TEST_INSTALL_CODE=str(_INSTALL_FAILURE), CURL_TEST_CODE="22")
    result = _run_protoc(env)
    assert result.returncode == 22, result.stdout + result.stderr
    assert log.read_text().splitlines() == [
        "apt-get update -y",
        _APT_INSTALL,
        "curl " + _RELEASE.format("linux-x86_64"),
    ]
    assert Path(env["GITHUB_PATH"]).read_text() == ""


def test_musl_installs_after_unrelated_index_failure_before_exporting_compiler(apt_boundary):
    env, log, github_env = apt_boundary
    result = _run_musl(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines() == ["apt-get update", "apt-get install -y musl-tools"]
    assert github_env.read_text().splitlines() == [
        "CC_x86_64_unknown_linux_musl=musl-gcc",
        "AR_x86_64_unknown_linux_musl=ar",
        "CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc",
    ]


@pytest.mark.parametrize("update_code", ["0", "100"])
def test_musl_install_failure_does_not_export_unusable_compiler(apt_boundary, update_code):
    env, log, github_env = apt_boundary
    env.update(APT_TEST_UPDATE_CODE=update_code, APT_TEST_INSTALL_CODE=str(_INSTALL_FAILURE))
    result = _run_musl(env)
    assert result.returncode == _INSTALL_FAILURE, result.stdout + result.stderr
    assert log.read_text().splitlines() == ["apt-get update", "apt-get install -y musl-tools"]
    assert github_env.read_text() == ""
