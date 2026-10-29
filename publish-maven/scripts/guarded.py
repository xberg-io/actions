"""Opt-in final-byte publication for the audited Central 0.12.0 bundle provider."""

import base64
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CENTRAL_API = "https://central.sonatype.com/api/v1/publisher"
DIGESTS = ("md5", "sha1", "sha256", "sha512")
SAFE_PROPERTIES = {"skipTests", "maven.test.skip"}
SAFE_MAVEN_PLUGINS = {
    "clean",
    "compiler",
    "resources",
    "surefire",
    "jar",
    "source",
    "javadoc",
    "enforcer",
    "checkstyle",
    "install",
    "site",
    "deploy",
    "gpg",
}


@dataclass(frozen=True)
class CentralConfig:
    group: str
    artifact: str
    version: str
    build_directory: Path
    auto_publish: bool = False
    wait_until: str = "validated"
    wait_max_time: int = 1800
    wait_polling_interval: int = 5


def xml_root(text: str) -> ET.Element:
    root = ET.fromstring(text)  # noqa: S314 — caller-controlled POM, no external entity expansion
    for element in root.iter():
        element.tag = element.tag.rpartition("}")[2]
    return root


def text_at(element: ET.Element, path: str, default: str = "") -> str:
    return (element.findtext(path) or default).strip()


def safe_extra_args(extra_args: str) -> list[str]:
    arguments = shlex.split(extra_args)
    for argument in arguments:
        match = re.fullmatch(r"-D([\w.]+)(?:=(true|false))?", argument)
        if not match or match.group(1) not in SAFE_PROPERTIES:
            raise ValueError("Guarded Maven publication accepts only skipTests and maven.test.skip properties")
    return arguments


def checked_configuration(plugin: ET.Element, server_id: str) -> dict[str, str]:
    configuration = plugin.find("configuration")
    values = {} if configuration is None else {child.tag: (child.text or "").strip() for child in configuration}
    accepted = {
        "skipUpload",
        "ignorePublishedComponents",
        "skipPublishing",
        "autoPublish",
        "waitUntil",
        "waitMaxTime",
        "waitPollingInterval",
        "publishingServerId",
        "checksums",
    }
    for name in ("skipUpload", "ignorePublishedComponents", "skipPublishing", "autoPublish", "waitUntil", "checksums"):
        if name in values:
            values[name] = values[name].lower()
    if set(values) - accepted or any("${" in value for value in values.values()):
        raise ValueError("Unsupported or unresolved Central configuration in guarded mode")
    for name, expected in (
        ("skipUpload", "true"),
        ("ignorePublishedComponents", "false"),
        ("skipPublishing", "false"),
        ("checksums", "all"),
    ):
        if name in values and values[name] != expected:
            raise ValueError(f"Guarded Maven publication requires {name}={expected}")
    if values.get("publishingServerId", "central") != server_id:
        raise ValueError("server-id must match the effective publishingServerId")
    if values.get("autoPublish", "false") not in {"true", "false"}:
        raise ValueError("autoPublish must resolve to true or false")
    if plugin.findall("executions/execution/configuration"):
        raise ValueError("Execution-specific Central configuration is unsupported in guarded mode")
    return values


def check_providers(root: ET.Element) -> ET.Element:
    plugins = root.findall("build/plugins/plugin")
    central = [
        plugin
        for plugin in plugins
        if text_at(plugin, "groupId") == "org.sonatype.central"
        and text_at(plugin, "artifactId") == "central-publishing-maven-plugin"
    ]
    if len(central) != 1 or text_at(central[0], "version") != "0.12.0" or text_at(central[0], "extensions") != "true":
        raise ValueError("Guarded publication requires Central publishing extension exactly 0.12.0")
    if root.findall("build/extensions/extension"):
        raise ValueError("Additional Maven build extensions are unsupported in guarded mode")
    deploy = []
    for plugin in plugins:
        if plugin is central[0]:
            continue
        group, artifact = text_at(plugin, "groupId", "org.apache.maven.plugins"), text_at(plugin, "artifactId")
        standard = group == "org.apache.maven.plugins" and artifact in {
            f"maven-{name}-plugin" for name in SAFE_MAVEN_PLUGINS
        }
        known = (group, artifact) in {
            ("org.jacoco", "jacoco-maven-plugin"),
            ("org.codehaus.mojo", "versions-maven-plugin"),
        }
        if not (standard or known) or text_at(plugin, "extensions", "false") != "false":
            raise ValueError(f"Unsupported Maven provider/plugin: {group}:{artifact}")
        for goal in plugin.findall("executions/execution/goals/goal"):
            name = (goal.text or "").strip()
            if "deploy" in name and (artifact != "maven-deploy-plugin" or name != "deploy"):
                raise ValueError(f"Unsupported additional upload goal: {artifact}:{name}")
        if artifact == "maven-deploy-plugin":
            deploy.append(plugin)
    if len(deploy) != 1 or text_at(deploy[0], "configuration/skip") != "true":
        raise ValueError("The effective maven-deploy-plugin must have skip=true")
    for configuration in deploy[0].findall("executions/execution/configuration"):
        if text_at(configuration, "skip", "true") != "true":
            raise ValueError("A deploy execution overrides skip=true")
    return central[0]


def parse_config(effective_pom: str, expected_version: str, server_id: str) -> CentralConfig:
    root = xml_root(effective_pom)
    if root.tag != "project" or root.findall("modules/module"):
        raise ValueError("Guarded Maven publication supports one project, not a reactor")
    group, artifact, version = (text_at(root, name) for name in ("groupId", "artifactId", "version"))
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in (group, artifact, version)):
        raise ValueError("Effective Maven coordinates are missing or unresolved")
    if not expected_version or version != expected_version or "SNAPSHOT" in version.upper():
        raise ValueError("Guarded publication requires the exact expected release version, excluding snapshots")
    values = checked_configuration(check_providers(root), server_id)
    auto_publish = values.get("autoPublish", "false") == "true"
    wait_until = values.get("waitUntil", "validated")
    if wait_until not in {"uploaded", "validated", "published"}:
        raise ValueError("Unsupported Central waitUntil")
    if wait_until == "published" and not auto_publish:
        wait_until = "validated"
    directory = text_at(root, "build/directory")
    if not directory or "${" in directory:
        raise ValueError("Effective Maven build directory must resolve")
    maximum, interval = int(values.get("waitMaxTime", "1800")), int(values.get("waitPollingInterval", "5"))
    if maximum < 1800 or interval < 5:
        raise ValueError("Central wait settings must meet the provider minimums (1800s, 5s)")
    return CentralConfig(group, artifact, version, Path(directory), auto_publish, wait_until, maximum, interval)


def bundle_members(payload: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = {}
            for item in archive.infolist():
                path = item.filename
                parts = path.rstrip("/").split("/")
                if any(part in {"", ".", ".."} for part in parts) or "\\" in path or path.startswith("/"):
                    raise ValueError("Unsafe or aliased Central bundle entry")
                if item.is_dir():
                    continue
                if path in members or (item.external_attr >> 16) & 0o170000 not in {0, 0o100000}:
                    raise ValueError("Duplicate or nonregular Central bundle entry")
                members[path] = archive.read(item)
            return members
    except (zipfile.BadZipFile, RuntimeError) as error:
        raise ValueError("Central bundle is not a readable ZIP") from error


def verify_signature(payload: bytes, signature: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="central-signature-") as temporary:
        artifact = Path(temporary) / "artifact"
        detached = Path(temporary) / "artifact.asc"
        artifact.write_bytes(payload)
        detached.write_bytes(signature)
        result = subprocess.run(
            ["gpg", "--batch", "--verify", str(detached), str(artifact)], capture_output=True, check=False, timeout=60
        )
        if result.returncode:
            raise ValueError("Central artifact signature verification failed")


def verify_bundle(
    payload: bytes,
    config: CentralConfig,
    notices: Mapping[str, bytes],
    verifier: Callable[[bytes, str, Mapping[str, bytes]], None],
    signature_verifier: Callable[[bytes, bytes], None],
) -> None:
    members = bundle_members(payload)
    prefix = f"{config.group.replace('.', '/')}/{config.artifact}/{config.version}/{config.artifact}-{config.version}"
    artifacts = [prefix + suffix for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom")]
    expected = {name + suffix for name in artifacts for suffix in ("", ".asc", *("." + digest for digest in DIGESTS))}
    if set(members) != expected:
        raise ValueError(
            f"Central bundle must contain exactly one component and {len(expected)} files; found {len(members)}"
        )
    for name in artifacts:
        content = members[name]
        for algorithm in DIGESTS:
            digest = hashlib.new(algorithm, content, usedforsecurity=False).hexdigest()
            if members[name + "." + algorithm].decode("ascii").strip().lower() != digest:
                raise ValueError(f"Central bundle checksum mismatch: {name}.{algorithm}")
        signature_verifier(content, members[name + ".asc"])
    pom = xml_root(members[prefix + ".pom"].decode("utf-8"))
    if tuple(text_at(pom, name) for name in ("groupId", "artifactId", "version")) != (
        config.group,
        config.artifact,
        config.version,
    ):
        raise ValueError("Bundled POM coordinates differ from the verified effective POM")
    for suffix in (".jar", "-sources.jar"):
        verifier(members[prefix + suffix], "jar", notices)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:  # noqa: ARG002, PLR0917 — stdlib override signature
        return None


def send(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
            expected_status = 201 if "/upload?" in request.full_url else 200
            if response.status != expected_status:
                raise ValueError("Central did not confirm the requested operation")
            return response.read()
    except urllib.error.HTTPError as error:
        raise ValueError(f"Central request failed with HTTP {error.code}; publication was not confirmed") from None


def wait_for_deployment(
    deployment: str, config: CentralConfig, authorization: str, transport: Callable[[urllib.request.Request], bytes]
) -> None:
    deadline = time.monotonic() + config.wait_max_time
    accepted = {"PUBLISHED"} if config.wait_until == "published" else {"VALIDATED", "PUBLISHING", "PUBLISHED"}
    while time.monotonic() < deadline:
        url = CENTRAL_API + "/status?" + urllib.parse.urlencode({"id": deployment})
        request = urllib.request.Request(  # noqa: S310 — fixed HTTPS Central endpoint
            url, data=b"", headers={"Authorization": authorization}, method="POST"
        )
        state = json.loads(transport(request)).get("deploymentState")
        if state in accepted:
            return
        if state == "FAILED":
            raise ValueError("Central deployment validation failed")
        time.sleep(config.wait_polling_interval)
    raise TimeoutError("Central deployment did not reach the requested state before waitMaxTime")


def publish_verified(
    payload: bytes,
    config: CentralConfig,
    notices: Mapping[str, bytes],
    username: str,
    password: str,
    *,
    verifier: Callable[[bytes, str, Mapping[str, bytes]], None],
    signature_verifier: Callable[[bytes, bytes], None] = verify_signature,
    transport: Callable[[urllib.request.Request], bytes] = send,
    dry_run: bool = False,
) -> None:
    verify_bundle(payload, config, notices, verifier, signature_verifier)
    if dry_run:
        print("Verified the final Central bundle; dry run uploads nothing")
        return
    if not username or not password:
        raise ValueError("Guarded publication requires MAVEN_USERNAME and MAVEN_PASSWORD")
    authorization = "Bearer " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    boundary = "central-" + uuid.uuid4().hex
    header = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="bundle"; filename="central-bundle.zip"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body = header + payload + f"\r\n--{boundary}--\r\n".encode()
    query = urllib.parse.urlencode({"publishingType": "AUTOMATIC" if config.auto_publish else "USER_MANAGED"})
    request = urllib.request.Request(  # noqa: S310 — fixed HTTPS Central endpoint
        CENTRAL_API + "/upload?" + query,
        data=body,
        headers={"Authorization": authorization, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    deployment = transport(request).decode("utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", deployment):
        raise ValueError("Central did not return a deployment identifier")
    if config.wait_until != "uploaded":
        wait_for_deployment(deployment, config, authorization, transport)
    print("Verified Central bundle uploaded successfully")


def build_bundle(
    pom_file: str, profile: str, arguments: list[str], settings: str, expected: str, *, server_id: str, timeout: int
) -> tuple[bytes, CentralConfig]:
    arguments = safe_extra_args(shlex.join(arguments))
    pom = Path(pom_file).resolve()
    for directory in (pom.parent, *pom.parents):
        if any((directory / ".mvn" / name).exists() for name in ("maven.config", "extensions.xml", "jvm.config")):
            raise ValueError("Guarded publication does not support implicit .mvn configuration")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "MAVEN_USERNAME",
            "MAVEN_PASSWORD",
            "MAVEN_GPG_PRIVATE_KEY",
            "MAVEN_ARGS",
            "MAVEN_OPTS",
            "JAVA_TOOL_OPTIONS",
            "JDK_JAVA_OPTIONS",
        }
    }
    base = [
        "mvn",
        "-f",
        str(pom),
        "-P",
        profile,
        "-B",
        "--no-transfer-progress",
        "-s",
        settings,
        "-gs",
        settings,
        *arguments,
        "-DskipUpload=true",
    ]
    with tempfile.TemporaryDirectory(prefix="central-effective-") as directory:
        effective = Path(directory) / "effective.xml"
        subprocess.run(
            [*base, "org.apache.maven.plugins:maven-help-plugin:3.5.1:effective-pom", f"-Doutput={effective}"],
            check=True,
            timeout=timeout,
            env=environment,
        )
        config = parse_config(effective.read_text(), expected, server_id)
    subprocess.run([*base, "clean", "deploy"], check=True, timeout=timeout, env=environment)
    bundle = config.build_directory / "central-publishing" / "central-bundle.zip"
    if not bundle.is_file():
        raise ValueError("Central provider did not produce the expected bundle")
    return bundle.read_bytes(), config
