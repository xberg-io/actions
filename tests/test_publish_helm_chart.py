import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-helm-chart" / "scripts" / "publish.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helm_mod = _import_script("publish_helm_chart", _SCRIPT_PATH)


def test_validate_version_accepts_basic_semver():
    helm_mod.validate_version("0.1.0")
    helm_mod.validate_version("1.2.3")
    helm_mod.validate_version("10.20.30")


def test_validate_version_accepts_prerelease():
    helm_mod.validate_version("0.1.0-rc.1")
    helm_mod.validate_version("1.0.0-alpha")
    helm_mod.validate_version("2.0.0-beta.7")


def test_validate_version_accepts_build_metadata():
    helm_mod.validate_version("0.1.0+build.42")
    helm_mod.validate_version("1.0.0-rc.1+sha.deadbeef")


def test_validate_version_rejects_v_prefix():
    with pytest.raises(SystemExit) as exc_info:
        helm_mod.validate_version("v0.1.0")
    assert exc_info.value.code == 1


def test_validate_version_rejects_empty():
    with pytest.raises(SystemExit) as exc_info:
        helm_mod.validate_version("")
    assert exc_info.value.code == 1


def test_validate_version_rejects_non_semver():
    for bad in ["0.1", "0.1.0.0", "latest", "1", "abc", "0.1.0-"]:
        with pytest.raises(SystemExit) as exc_info:
            helm_mod.validate_version(bad)
        assert exc_info.value.code == 1, f"expected {bad!r} to be rejected"


def test_extract_registry_host_ghcr():
    assert helm_mod.extract_registry_host("oci://ghcr.io/xberg-io/charts") == "ghcr.io"


def test_extract_registry_host_gcp():
    assert (
        helm_mod.extract_registry_host("oci://us-central1-docker.pkg.dev/some-project/helm-charts")
        == "us-central1-docker.pkg.dev"
    )


def test_extract_registry_host_strips_subpaths():
    assert helm_mod.extract_registry_host("oci://ghcr.io/org/charts/sub") == "ghcr.io"


def test_extract_registry_host_rejects_https():
    with pytest.raises(SystemExit) as exc_info:
        helm_mod.extract_registry_host("https://ghcr.io/org/charts")
    assert exc_info.value.code == 1


def test_extract_registry_host_rejects_empty():
    with pytest.raises(SystemExit) as exc_info:
        helm_mod.extract_registry_host("")
    assert exc_info.value.code == 1


def test_is_already_published_already_exists():
    assert helm_mod.is_already_published("Error: chart already exists in registry") is True


def test_is_already_published_conflict():
    assert helm_mod.is_already_published("HTTP 409 Conflict on push") is True


def test_is_already_published_case_insensitive():
    assert helm_mod.is_already_published("ALREADY EXISTS") is True


def test_is_already_published_unrelated():
    assert helm_mod.is_already_published("network error: connection reset") is False


def test_is_already_published_empty():
    assert helm_mod.is_already_published("") is False


def test_stamp_chart_yaml_rewrites_version_and_app_version(tmp_path: Path):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text(
        "apiVersion: v2\n"
        "name: my-chart\n"
        "version: 0.0.0\n"
        'appVersion: "0.0.0"\n'
        "dependencies:\n"
        "  - name: postgres\n"
        "    version: 18.3.0\n"
    )

    helm_mod.stamp_chart_yaml(chart_yaml, "1.2.3", "1.2.3")

    text = chart_yaml.read_text()
    assert "version: 1.2.3" in text
    assert 'appVersion: "1.2.3"' in text
    assert "version: 18.3.0" in text


def test_stamp_chart_yaml_handles_unquoted_app_version(tmp_path: Path):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("apiVersion: v2\nname: my-chart\nversion: 0.0.0\nappVersion: 0.0.0\n")

    helm_mod.stamp_chart_yaml(chart_yaml, "2.0.0", "2.0.0")

    text = chart_yaml.read_text()
    assert "version: 2.0.0" in text
    assert 'appVersion: "2.0.0"' in text


def test_stamp_chart_yaml_missing_file(tmp_path: Path):
    with pytest.raises(SystemExit) as exc_info:
        helm_mod.stamp_chart_yaml(tmp_path / "nope.yaml", "0.1.0", "0.1.0")
    assert exc_info.value.code == 1


def test_write_outputs_appends_to_github_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output_file = tmp_path / "github_output.txt"
    output_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    helm_mod.write_outputs(published="true", skipped="false")

    content = output_file.read_text()
    assert "published=true\n" in content
    assert "skipped=false\n" in content


def test_write_outputs_handles_missing_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    helm_mod.write_outputs(published="true")

    captured = capsys.readouterr()
    assert "::set-output name=published::true" in captured.out
