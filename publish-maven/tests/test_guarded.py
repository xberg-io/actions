"Final-byte Central publication contract tests; no Maven or registry calls."

import hashlib
import importlib.util
import io
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "guarded.py"
spec = importlib.util.spec_from_file_location("guarded_maven", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def effective(configuration="", version="1.2.3", plugin_version="0.12.0"):
    return f"<project><groupId>io.example</groupId><artifactId>demo</artifactId><version>{version}</version>\n    <build><directory>/tmp/target</directory><plugins><plugin><groupId>org.apache.maven.plugins</groupId>\n    <artifactId>maven-deploy-plugin</artifactId><configuration><skip>true</skip></configuration></plugin>\n    <plugin><groupId>org.sonatype.central</groupId><artifactId>central-publishing-maven-plugin</artifactId>\n    <version>{plugin_version}</version><extensions>true</extensions><configuration><publishingServerId>ossrh</publishingServerId>{configuration}</configuration>\n    </plugin></plugins></build></project>"


def bundle(corrupt=False, missing=False, duplicate=False, notice=b"canonical"):
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("META-INF/THIRD_PARTY_LICENSES", notice)
        archive.writestr("io/example/Demo.class", b"bytecode")
    files = {f"demo-1.2.3{suffix}": jar.getvalue() for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom")}
    files["demo-1.2.3.pom"] = (
        b"<project><groupId>io.example</groupId><artifactId>demo</artifactId><version>1.2.3</version></project>"
    )
    if missing:
        del files["demo-1.2.3-sources.jar"]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, payload in files.items():
            path = f"io/example/demo/1.2.3/{name}"
            archive.writestr(path, payload)
            archive.writestr(path + ".asc", b"signature")
            for algorithm in ("md5", "sha1", "sha256", "sha512"):
                digest = hashlib.new(algorithm, payload).hexdigest()
                archive.writestr(path + "." + algorithm, "bad" if corrupt else digest)
        if duplicate:
            archive.writestr("io/example/demo/1.2.3/./demo-1.2.3.jar", b"other")
    return output.getvalue()


class GuardedTests(unittest.TestCase):
    def test_supported_config_preserves_automatic_and_staged(self):
        automatic = module.parse_config(
            effective("<autoPublish>true</autoPublish><waitUntil>validated</waitUntil>"), "1.2.3", "ossrh"
        )
        staged = module.parse_config(effective(), "1.2.3", "ossrh")
        assert automatic.auto_publish
        assert not staged.auto_publish

    def test_rejects_unsafe_effective_config(self):
        for field in (
            "<skipUpload>false</skipUpload>",
            "<ignorePublishedComponents>true</ignorePublishedComponents>",
            "<outputDirectory>/tmp/elsewhere</outputDirectory>",
            "<skipPublishing>true</skipPublishing>",
        ):
            with (
                self.subTest(field=field),
                pytest.raises(ValueError, match=r"Guarded|Unsupported|Central|missing|Hex|prebuilt"),
            ):
                module.parse_config(effective(field), "1.2.3", "ossrh")
        for version, plugin in (("1.2.3-SNAPSHOT", "0.12.0"), ("1.2.3", "0.11.0")):
            with (
                self.subTest(version=version, plugin=plugin),
                pytest.raises(ValueError, match=r"Guarded|Unsupported|Central|missing|Hex|prebuilt"),
            ):
                module.parse_config(effective(version=version, plugin_version=plugin), version, "ossrh")

    def test_arguments_cannot_override_upload_or_inject_goals(self):
        assert module.safe_extra_args("-DskipTests -Dmaven.test.skip=true") == ["-DskipTests", "-Dmaven.test.skip=true"]
        for args in (
            "deploy",
            "-f other.xml",
            "-DskipUpload=false",
            "-DaltDeploymentRepository=x",
            "-Dclassifier=other",
        ):
            with (
                self.subTest(args=args),
                pytest.raises(ValueError, match=r"Guarded|Unsupported|Central|missing|Hex|prebuilt"),
            ):
                module.safe_extra_args(args)

    def test_exact_bundle_checks_all_artifacts_but_not_javadoc_notices(self):
        notices = Mock()
        signature = Mock()
        payload = bundle()
        config = module.parse_config(effective(), "1.2.3", "ossrh")
        module.verify_bundle(payload, config, {"THIRD_PARTY_LICENSES": b"canonical"}, notices, signature)
        assert notices.call_count == 2
        assert signature.call_count == 4
        assert len(zipfile.ZipFile(io.BytesIO(payload)).namelist()) == 24

    def test_invalid_bundle_prevents_upload(self):
        config = module.parse_config(effective(), "1.2.3", "ossrh")
        for payload, verifier in (
            (bundle(corrupt=True), Mock()),
            (bundle(missing=True), Mock()),
            (bundle(duplicate=True), Mock()),
            (b"", Mock()),
            (bundle(), Mock(side_effect=ValueError("missing notices"))),
        ):
            transport = Mock()
            with (
                self.subTest(size=len(payload)),
                pytest.raises(ValueError, match=r"Guarded|Unsupported|Central|missing|Hex|prebuilt"),
            ):
                module.publish_verified(
                    payload,
                    config,
                    {"LICENSE": b"canonical"},
                    "user",
                    "password",
                    verifier=verifier,
                    signature_verifier=Mock(),
                    transport=transport,
                )
            transport.assert_not_called()

    def test_upload_body_contains_exact_verified_bytes_once(self):
        payload = bundle()
        config = module.parse_config(
            effective("<waitUntil>uploaded</waitUntil><autoPublish>true</autoPublish>"), "1.2.3", "ossrh"
        )
        transport = Mock(return_value=b"deployment-id")
        module.publish_verified(
            payload, config, {}, "user", "password", verifier=Mock(), signature_verifier=Mock(), transport=transport
        )
        assert transport.call_count == 1
        request = transport.call_args.args[0]
        assert payload in request.data
        assert "publishingType=AUTOMATIC" in request.full_url
        assert request.get_header("Authorization") == "Bearer dXNlcjpwYXNzd29yZA=="

    def test_missing_credentials_and_dry_run_do_not_upload(self):
        config = module.parse_config(effective(), "1.2.3", "ossrh")
        transport = Mock()
        with pytest.raises(ValueError, match=r"Guarded|Unsupported|Central|missing|Hex|prebuilt"):
            module.publish_verified(
                bundle(), config, {}, "", "", verifier=Mock(), signature_verifier=Mock(), transport=transport
            )
        module.publish_verified(
            bundle(), config, {}, "", "", dry_run=True, verifier=Mock(), signature_verifier=Mock(), transport=transport
        )
        transport.assert_not_called()

    def test_waits_for_validation_without_publishing_manual_deployment(self):
        config = module.parse_config(effective("<waitUntil>validated</waitUntil>"), "1.2.3", "ossrh")
        transport = Mock(side_effect=[b"deployment-id", b'{"deploymentState":"VALIDATED"}'])
        module.publish_verified(
            bundle(), config, {}, "user", "password", verifier=Mock(), signature_verifier=Mock(), transport=transport
        )
        assert transport.call_count == 2
        assert "publishingType=USER_MANAGED" in transport.call_args_list[0].args[0].full_url
        assert "/status?id=deployment-id" in transport.call_args_list[1].args[0].full_url


def test_preflight_rejects_provider_and_execution_overrides():
    base = effective()
    for altered in (
        base.replace("<skip>true</skip>", "<skip>false</skip>"),
        base.replace("0.12.0", "0.11.0"),
        base.replace("<extensions>true</extensions>", "<extensions>false</extensions>"),
        base.replace(
            "</configuration>\n    </plugin>",
            "</configuration><executions><execution><configuration><skipUpload>false</skipUpload></configuration></execution></executions></plugin>",
        ),
        base.replace(
            "<plugins>",
            "<plugins><plugin><groupId>org.sonatype.plugins</groupId><artifactId>nexus-staging-maven-plugin</artifactId></plugin>",
        ),
    ):
        with pytest.raises(ValueError, match=r"Central|effective|Unsupported|Execution"):
            module.parse_config(altered, "1.2.3", "ossrh")


def test_effective_preflight_never_executes_deploy_for_bad_config(tmp_path, monkeypatch):
    pom = tmp_path / "pom.xml"
    pom.write_text("<project/>")
    commands = []

    def fake_maven(command, **kwargs):
        commands.append(command)
        assert "MAVEN_USERNAME" not in kwargs["env"]
        assert "MAVEN_PASSWORD" not in kwargs["env"]
        assert command.count("-DskipUpload=true") == 1
        assert command[command.index("-s") + 1] == command[command.index("-gs") + 1]
        output = next(part.removeprefix("-Doutput=") for part in command if part.startswith("-Doutput="))
        Path(output).write_text(effective("<skipUpload>false</skipUpload>"))

    monkeypatch.setenv("MAVEN_USERNAME", "not-forwarded")
    monkeypatch.setenv("MAVEN_PASSWORD", "not-forwarded")
    monkeypatch.setattr(module.subprocess, "run", fake_maven)
    with pytest.raises(ValueError, match="skipUpload=true"):
        module.build_bundle(str(pom), "publish", [], "no-credentials.xml", "1.2.3", server_id="ossrh", timeout=10)
    assert len(commands) == 1
    assert "deploy" not in commands[0]


def test_build_reads_bundle_once_after_non_uploading_deploy(tmp_path, monkeypatch):
    pom = tmp_path / "pom.xml"
    pom.write_text("<project/>")
    payload = bundle()
    commands = []

    def fake_maven(command, **kwargs):
        commands.append(command)
        if "deploy" in command:
            output = tmp_path / "target" / "central-publishing" / "central-bundle.zip"
            output.parent.mkdir(parents=True)
            output.write_bytes(payload)
        else:
            output = next(part.removeprefix("-Doutput=") for part in command if part.startswith("-Doutput="))
            Path(output).write_text(effective().replace("/tmp/target", str(tmp_path / "target")))

    monkeypatch.setattr(module.subprocess, "run", fake_maven)
    actual, _ = module.build_bundle(
        str(pom), "publish", [], "no-credentials.xml", "1.2.3", server_id="ossrh", timeout=10
    )
    assert actual == payload
    assert len(commands) == 2
    assert commands[1][-2:] == ["clean", "deploy"]
    assert "-DskipUpload=true" in commands[1]


def test_bad_signature_prevents_upload():
    transport = Mock()
    with pytest.raises(ValueError, match="bad signature"):
        module.publish_verified(
            bundle(),
            module.parse_config(effective(), "1.2.3", "ossrh"),
            {},
            "user",
            "password",
            verifier=Mock(),
            signature_verifier=Mock(side_effect=ValueError("bad signature")),
            transport=transport,
        )
    transport.assert_not_called()


def test_validation_failure_is_not_an_idempotent_success():
    transport = Mock(side_effect=[b"deployment-id", b'{"deploymentState":"FAILED"}'])
    with pytest.raises(ValueError, match="validation failed"):
        module.publish_verified(
            bundle(),
            module.parse_config(effective(), "1.2.3", "ossrh"),
            {},
            "user",
            "password",
            verifier=Mock(),
            signature_verifier=Mock(),
            transport=transport,
        )
    assert transport.call_count == 2


def test_real_shared_verifier_gates_nested_code_jars():
    helper_spec = importlib.util.spec_from_file_location(
        "central_notices", SCRIPT.parents[2] / "verify-package-contents/scripts/notices.py"
    )
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    config = module.parse_config(effective("<waitUntil>uploaded</waitUntil>"), "1.2.3", "ossrh")
    for notice in (b"canonical", b"stale"):
        transport = Mock(return_value=b"deployment-id")
        if notice == b"canonical":
            module.publish_verified(
                bundle(notice=notice),
                config,
                {"THIRD_PARTY_LICENSES": b"canonical"},
                "user",
                "password",
                verifier=helper.verify_archive_bytes,
                signature_verifier=Mock(),
                transport=transport,
            )
            assert transport.call_count == 1
        else:
            with pytest.raises(ValueError, match="differs from canonical THIRD_PARTY_LICENSES"):
                module.publish_verified(
                    bundle(notice=notice),
                    config,
                    {"THIRD_PARTY_LICENSES": b"canonical"},
                    "user",
                    "password",
                    verifier=helper.verify_archive_bytes,
                    signature_verifier=Mock(),
                    transport=transport,
                )
            transport.assert_not_called()


@pytest.mark.parametrize(
    "required,content,extra,expected",
    [
        (" \n", b"canonical", "", "1.2.3"),
        ("MISSING", b"canonical", "", "1.2.3"),
        ("THIRD_PARTY_LICENSES", b"", "", "1.2.3"),
        ("THIRD_PARTY_LICENSES", b"canonical", "deploy", "1.2.3"),
        ("THIRD_PARTY_LICENSES", b"canonical", "", ""),
    ],
)
def test_guarded_entrypoint_invalid_inputs_never_run_maven(
    tmp_path, monkeypatch, *, required, content, extra, expected
):
    deploy_spec = importlib.util.spec_from_file_location("notice_deploy", SCRIPT.parent / "deploy.py")
    deploy = importlib.util.module_from_spec(deploy_spec)
    deploy_spec.loader.exec_module(deploy)
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    pom = tmp_path / "pom.xml"
    pom.write_text("<project/>")
    (tmp_path / "THIRD_PARTY_LICENSES").write_bytes(content)
    for key, value in {
        "INPUT_POM_FILE": str(pom),
        "INPUT_CANONICAL_ROOT": str(tmp_path),
        "INPUT_REQUIRED_NOTICE_FILES": required,
        "INPUT_EXTRA_ARGS": extra,
        "INPUT_EXPECTED_VERSION": expected,
    }.items():
        monkeypatch.setenv(key, value)
    runner = Mock()
    monkeypatch.setattr(deploy.subprocess, "run", runner)
    with pytest.raises(SystemExit) as error:
        deploy.main()
    assert error.value.code == 1
    runner.assert_not_called()


@pytest.mark.parametrize(
    "artifact,goal", [("maven-gpg-plugin", "sign-and-deploy-file"), ("maven-site-plugin", "deploy")]
)
def test_known_plugins_cannot_bind_additional_upload_goals(artifact, goal):
    publishing_plugin = (
        f"<plugin><groupId>org.apache.maven.plugins</groupId><artifactId>{artifact}</artifactId>"
        f"<executions><execution><phase>deploy</phase><goals><goal>{goal}</goal></goals></execution></executions></plugin>"
    )
    pom = effective().replace("<plugins>", "<plugins>" + publishing_plugin)
    with pytest.raises(ValueError, match="upload goal"):
        module.parse_config(pom, "1.2.3", "ossrh")


def test_signature_verifier_checks_exact_artifact_bytes(tmp_path, monkeypatch):
    seen = []

    def fake_gpg(command, **kwargs):
        assert command[:3] == ["gpg", "--batch", "--verify"]
        seen.append((Path(command[4]).read_bytes(), Path(command[3]).read_bytes()))
        return Mock(returncode=1)

    monkeypatch.setattr(module.subprocess, "run", fake_gpg)
    with pytest.raises(ValueError, match="signature verification failed"):
        module.verify_signature(b"outgoing artifact", b"invalid detached signature")
    assert seen == [(b"outgoing artifact", b"invalid detached signature")]


@pytest.mark.parametrize(
    "name,value",
    [
        ("autoPublish", "true"),
        ("waitUntil", "published"),
        ("waitMaxTime", "3600"),
        ("waitPollingInterval", "10"),
        ("publishCompletionPollInterval", "2000"),
        ("waitForPublishCompletion", "true"),
        ("ignorePublishedComponents", "true"),
        ("skipUpload", "false"),
        ("skipPublishing", "true"),
        ("failOnBuildFailure", "false"),
        ("outputDirectory", "/tmp/elsewhere"),
        ("outputFilename", "other.zip"),
        ("stagingDirectory", "/tmp/staging"),
        ("deferredDirectory", "/tmp/deferred"),
        ("deploymentName", "other"),
        ("publishingServerId", "other"),
        ("checksums", "none"),
        ("centralBaseUrl", "https://example.invalid"),
        ("centralSnapshotsUrl", "https://example.invalid"),
        ("excludeArtifacts", "demo"),
    ],
)
def test_rejects_provider_parameter_properties(name, value):
    pom = effective().replace("<build>", f"<properties><{name}>{value}</{name}></properties><build>")
    with pytest.raises(ValueError, match=f"Central parameter properties.*{name}"):
        module.parse_config(pom, "1.2.3", "ossrh")


def test_unrelated_project_properties_preserve_explicit_publication_configuration():
    pom = effective("<autoPublish>true</autoPublish><waitUntil>published</waitUntil>").replace(
        "<build>", "<properties><maven.compiler.release>21</maven.compiler.release></properties><build>"
    )
    config = module.parse_config(pom, "1.2.3", "ossrh")
    assert config.auto_publish
    assert config.wait_until == "published"


@pytest.mark.parametrize(
    "name,value", [("autoPublish", "true"), ("waitUntil", "published"), ("ignorePublishedComponents", "true")]
)
def test_provider_properties_stop_before_deploy(tmp_path, monkeypatch, name, value):
    pom = tmp_path / "pom.xml"
    pom.write_text("<project/>")
    commands = []

    def fake_maven(command, **kwargs):
        commands.append(command)
        output = next(part.removeprefix("-Doutput=") for part in command if part.startswith("-Doutput="))
        Path(output).write_text(
            effective().replace("<build>", f"<properties><{name}>{value}</{name}></properties><build>")
        )

    monkeypatch.setattr(module.subprocess, "run", fake_maven)
    with pytest.raises(ValueError, match=f"Central parameter properties.*{name}"):
        module.build_bundle(str(pom), "publish", [], "no-credentials.xml", "1.2.3", server_id="ossrh", timeout=10)
    assert len(commands) == 1
    assert "deploy" not in commands[0]
