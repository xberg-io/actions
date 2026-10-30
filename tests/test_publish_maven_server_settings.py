import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-maven" / "scripts" / "server_settings.py"
_NAMESPACE = {"m": "http://maven.apache.org/SETTINGS/1.0.0"}


def _import_script():
    spec = importlib.util.spec_from_file_location("server_settings", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


settings_mod = _import_script()


def test_should_write_the_server_entry_setup_java_wrote_with_env_references(tmp_path: Path):
    path = settings_mod.write_settings("central", tmp_path)

    assert path == tmp_path / ".m2" / "settings.xml"
    server = ET.parse(path).getroot().find("m:servers/m:server", _NAMESPACE)
    assert server.findtext("m:id", namespaces=_NAMESPACE) == "central"
    assert server.findtext("m:username", namespaces=_NAMESPACE) == "${env.MAVEN_USERNAME}"
    assert server.findtext("m:password", namespaces=_NAMESPACE) == "${env.MAVEN_PASSWORD}"


def test_should_overwrite_existing_settings_like_setup_java(tmp_path: Path):
    existing = tmp_path / ".m2" / "settings.xml"
    existing.parent.mkdir()
    existing.write_text("<settings><servers/></settings>", encoding="utf-8")

    settings_mod.write_settings("ossrh", tmp_path)

    assert "<id>ossrh</id>" in existing.read_text(encoding="utf-8")


def test_should_never_write_credential_values_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAVEN_USERNAME", "token-user")
    monkeypatch.setenv("MAVEN_PASSWORD", "token-secret")

    content = settings_mod.write_settings("ossrh", tmp_path).read_text(encoding="utf-8")

    assert "token-user" not in content
    assert "token-secret" not in content


@pytest.mark.parametrize("server_id", ["", "a b", "x</id><id>y", "-flag"])
def test_should_reject_a_server_id_that_would_need_escaping(server_id: str, tmp_path: Path):
    with pytest.raises(ValueError, match="server-id"):
        settings_mod.write_settings(server_id, tmp_path)
    assert not (tmp_path / ".m2" / "settings.xml").exists()


def test_main_should_fail_without_a_traceback_on_an_invalid_server_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("INPUT_SERVER_ID", "bad id")
    monkeypatch.setenv("HOME", str(tmp_path))

    with pytest.raises(SystemExit) as exit_info:
        settings_mod.main()

    assert exit_info.value.code == 1
    assert "::error::server-id" in capsys.readouterr().err
