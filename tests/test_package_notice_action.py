"""Exercise the composite action entrypoint with real archives and isolated inputs."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_package_notice_bytes import CONTENT, NOTICE, package_bytes

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "verify-package-contents/scripts/verify.py"


@pytest.fixture
def inputs(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / NOTICE).write_bytes(CONTENT)
    artifact = tmp_path / "package.jar"
    artifact.write_bytes(package_bytes("jar"))
    return {
        "INPUT_LANGUAGE": "java",
        "INPUT_ARTIFACT_PATH": str(artifact),
        "INPUT_REQUIRED_NOTICE_FILES": NOTICE,
        "INPUT_CANONICAL_ROOT": str(canonical),
        "INPUT_ARTIFACT_FORMAT": "jar",
        "INPUT_EXPECTED_ARTIFACT_COUNT": "1",
        "INPUT_STRICT": "false",
    }


def invoke(inputs):
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("INPUT_") and name != "GITHUB_OUTPUT"
    }
    environment.update(inputs)
    return subprocess.run([sys.executable, str(SCRIPT)], env=environment, text=True, capture_output=True, check=False)


def test_should_verify_notice_bytes_while_retaining_non_strict_legacy_checks(inputs):
    result = invoke(inputs)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Notice archives verified: 1" in result.stdout


@pytest.mark.parametrize("content", [b"corrupt", b""])
def test_should_fail_notice_corruption_even_when_strict_is_false(inputs, content):
    Path(inputs["INPUT_ARTIFACT_PATH"]).write_bytes(package_bytes("jar", content))
    result = invoke(inputs)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "differs from canonical" in result.stdout


@pytest.mark.parametrize("value", [" ", "\n\t"])
def test_should_reject_explicit_whitespace_notice_sets(inputs, value):
    inputs["INPUT_REQUIRED_NOTICE_FILES"] = value
    result = invoke(inputs)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "required-notice-files" in result.stdout


@pytest.mark.parametrize("value", ["0", "-1", " ", "word"])
def test_should_reject_nonpositive_or_invalid_expected_counts(inputs, value):
    inputs["INPUT_EXPECTED_ARTIFACT_COUNT"] = value
    result = invoke(inputs)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "expected-artifact-count" in result.stdout


def test_should_reject_an_exact_artifact_count_mismatch(inputs):
    inputs["INPUT_EXPECTED_ARTIFACT_COUNT"] = "2"
    result = invoke(inputs)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "expected 2 notice artifacts, found 1" in result.stdout


def test_should_verify_exactly_two_actual_archives(inputs, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for name in ("first.jar", "second.jar"):
        (artifacts / name).write_bytes(package_bytes("jar"))
    inputs.update(INPUT_ARTIFACT_PATH=str(artifacts), INPUT_EXPECTED_ARTIFACT_COUNT="2")
    result = invoke(inputs)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Notice archives verified: 2" in result.stdout


def test_should_reject_an_empty_artifact_sweep(inputs, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    inputs["INPUT_ARTIFACT_PATH"] = str(empty)
    result = invoke(inputs)
    assert result.returncode != 0
    assert "No archive files" in result.stdout


def test_should_filter_explicit_artifact_formats_without_counting_unrelated_archives(inputs, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "fixture.whl").write_bytes(package_bytes("wheel"))
    (artifacts / "other.jar").write_bytes(b"not a wheel")
    inputs.update(INPUT_ARTIFACT_PATH=str(artifacts), INPUT_ARTIFACT_FORMAT="wheel", INPUT_LANGUAGE="python")
    result = invoke(inputs)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Notice archives verified: 1" in result.stdout


def test_should_infer_mixed_wheel_and_sdist_formats_for_a_python_publish_directory(inputs, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "fixture.whl").write_bytes(package_bytes("wheel"))
    (artifacts / "fixture.tar.gz").write_bytes(package_bytes("sdist"))
    inputs.update(
        INPUT_ARTIFACT_PATH=str(artifacts),
        INPUT_ARTIFACT_FORMAT="auto",
        INPUT_EXPECTED_ARTIFACT_COUNT="2",
        INPUT_LANGUAGE="python",
    )
    result = invoke(inputs)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Notice archives verified: 2" in result.stdout


def test_should_keep_legacy_behavior_when_notice_inputs_are_absent(inputs):
    inputs = {
        name: value
        for name, value in inputs.items()
        if name
        not in {
            "INPUT_REQUIRED_NOTICE_FILES",
            "INPUT_CANONICAL_ROOT",
            "INPUT_ARTIFACT_FORMAT",
            "INPUT_EXPECTED_ARTIFACT_COUNT",
        }
    }
    Path(inputs["INPUT_ARTIFACT_PATH"]).write_bytes(package_bytes("jar", b"bad notice ignored in legacy mode"))
    result = invoke(inputs)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Notice archives verified:" not in result.stdout


def test_should_reject_notice_options_without_a_required_notice_set(inputs):
    inputs["INPUT_REQUIRED_NOTICE_FILES"] = ""
    result = invoke(inputs)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "required-notice-files" in result.stdout


def test_should_wire_each_opt_in_action_input_to_the_script_environment():
    action = yaml.safe_load((ROOT / "verify-package-contents/action.yml").read_text())
    steps = [step for step in action["runs"]["steps"] if step.get("id") == "verify"]
    assert len(steps) == 1
    environment = steps[0]["env"]
    names = ("required-notice-files", "canonical-root", "artifact-format", "expected-artifact-count")
    assert len(names) == 4
    for name in names:
        assert name in action["inputs"]
        assert environment[f"INPUT_{name.upper().replace('-', '_')}"] == "${{ inputs." + name + " }}"


def test_should_reject_symlinked_artifacts_in_the_counted_inventory(inputs, tmp_path):
    alias = tmp_path / "alias.jar"
    alias.symlink_to(inputs["INPUT_ARTIFACT_PATH"])
    inputs["INPUT_ARTIFACT_PATH"] = str(alias)
    result = invoke(inputs)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "regular files" in result.stdout


def test_should_reject_a_zero_match_explicit_format_filter(inputs, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "other.whl").write_bytes(package_bytes("wheel"))
    inputs["INPUT_ARTIFACT_PATH"] = str(artifacts)
    result = invoke(inputs)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "No archive files for notice verification" in result.stdout


@pytest.mark.parametrize("value", [" ", ""])
def test_should_reject_empty_canonical_roots_when_opted_in(inputs, value):
    inputs["INPUT_CANONICAL_ROOT"] = value
    result = invoke(inputs)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "canonical-root" in result.stdout


def test_should_provision_the_callers_mise_python_only_for_opted_in_notice_checks():
    action = yaml.safe_load((ROOT / "verify-package-contents/action.yml").read_text())
    steps = action["runs"]["steps"]
    assert not [step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python@")]
    python_steps = [step for step in steps if "install-tools.sh" in str(step.get("run", ""))]
    assert len(python_steps) == 1
    setup = python_steps[0]
    assert setup["if"] == "inputs.required-notice-files != ''"
    assert setup["run"].endswith('install-tools.sh" . python')
    assert steps.index(setup) < next(index for index, step in enumerate(steps) if step.get("id") == "verify")
