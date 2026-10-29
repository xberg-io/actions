"Prebuilt Hex publication tests with recording transports only."

import hashlib
import importlib.util
import io
import tarfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prebuilt.py"
spec = importlib.util.spec_from_file_location("prebuilt_hex", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def tarball(corrupt=False, extra=False, notice=b"canonical"):
    metadata = b'{<<"name">>,<<"demo">>}.\n{<<"version">>,<<"1.2.3">>}.\n'
    contents_buffer = io.BytesIO()
    with tarfile.open(fileobj=contents_buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("THIRD_PARTY_LICENSES")
        info.size = len(notice)
        archive.addfile(info, io.BytesIO(notice))
    contents = contents_buffer.getvalue()
    checksum = hashlib.sha256(b"3" + metadata + contents).hexdigest().upper().encode()
    files = {
        "VERSION": b"3",
        "metadata.config": metadata,
        "contents.tar.gz": contents,
        "CHECKSUM": b"bad" if corrupt else checksum,
    }
    if extra:
        files["./contents.tar.gz"] = b"another payload"
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, payload in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


class PrebuiltTests(unittest.TestCase):
    def test_sends_exact_verified_bytes_without_rebuilding(self):
        payload = tarball()
        transport = Mock(return_value=b'{"version":"1.2.3"}')
        metadata = Mock(return_value=("demo", "1.2.3"))
        verifier = Mock()
        module.publish_verified(
            payload,
            "demo",
            "1.2.3",
            {"LICENSE": b"canonical"},
            "key",
            replace=True,
            verifier=verifier,
            metadata_reader=metadata,
            transport=transport,
        )
        request = transport.call_args.args[0]
        assert request.data is payload
        assert request.full_url == "https://hex.pm/api/packages/demo/releases?replace=true"
        assert request.get_header("Authorization") == "key"
        verifier.assert_called_once_with(payload, "hex", {"LICENSE": b"canonical"})
        assert metadata.call_args.args[0] == b'{<<"name">>,<<"demo">>}.\n{<<"version">>,<<"1.2.3">>}.\n'

    def test_invalid_envelope_or_identity_never_uploads(self):
        for payload, identity in (
            (b"", ("demo", "1.2.3")),
            (tarball(corrupt=True), ("demo", "1.2.3")),
            (tarball(extra=True), ("demo", "1.2.3")),
            (tarball(), ("old", "1.2.3")),
            (tarball(), ("demo", "1.2.2")),
        ):
            transport = Mock()
            with (
                self.subTest(identity=identity, size=len(payload)),
                pytest.raises(ValueError, match=r"Guarded|Unsupported|Central|missing|Hex|HEX_API_KEY|prebuilt"),
            ):
                module.publish_verified(
                    payload,
                    "demo",
                    "1.2.3",
                    {},
                    "key",
                    replace=False,
                    verifier=Mock(),
                    metadata_reader=Mock(return_value=identity),
                    transport=transport,
                )
            transport.assert_not_called()

    def test_missing_notice_and_missing_credentials_never_upload(self):
        for verifier, key in ((Mock(side_effect=ValueError("missing notice")), "key"), (Mock(), "")):
            transport = Mock()
            with pytest.raises(ValueError, match=r"Guarded|Unsupported|Central|missing|Hex|HEX_API_KEY|prebuilt"):
                module.publish_verified(
                    tarball(),
                    "demo",
                    "1.2.3",
                    {},
                    key,
                    replace=False,
                    verifier=verifier,
                    metadata_reader=Mock(return_value=("demo", "1.2.3")),
                    transport=transport,
                )
            transport.assert_not_called()

    def test_dry_run_verifies_without_authentication_or_upload(self):
        transport = Mock()
        verifier = Mock()
        module.publish_verified(
            tarball(),
            "demo",
            "1.2.3",
            {},
            "",
            dry_run=True,
            replace=False,
            verifier=verifier,
            metadata_reader=Mock(return_value=("demo", "1.2.3")),
            transport=transport,
        )
        verifier.assert_called_once()
        transport.assert_not_called()

    def test_missing_expected_identity_fails_closed(self):
        transport = Mock()
        for name, version in (("", "1.2.3"), ("demo", ""), ("../demo", "1.2.3")):
            with (
                self.subTest(name=name, version=version),
                pytest.raises(ValueError, match=r"Guarded|Unsupported|Central|missing|Hex|HEX_API_KEY|prebuilt"),
            ):
                module.publish_verified(
                    tarball(),
                    name,
                    version,
                    {},
                    "key",
                    replace=False,
                    verifier=Mock(),
                    metadata_reader=Mock(),
                    transport=transport,
                )
        transport.assert_not_called()


def test_erlang_consult_parses_metadata_as_data():
    assert module.read_metadata(b'{<<"name">>,<<"demo">>}.\n{<<"version">>,<<"1.2.3">>}.\n') == ("demo", "1.2.3")


@pytest.mark.parametrize(
    "metadata",
    [
        b'{<<"name">>,<<"demo">>}.',
        b'{<<"name">>,<<"demo">>}.\n{<<"name">>,<<"other">>}.\n{<<"version">>,<<"1.2.3">>}.',
        b'System.cmd("touch", ["SHOULD_NOT_EXIST"])',
    ],
)
def test_erlang_consult_rejects_missing_duplicate_and_executable_metadata(metadata):
    with pytest.raises(ValueError, match="one binary name and version"):
        module.read_metadata(metadata)


def test_real_metadata_and_nested_notice_verifier_gate_final_bytes():
    helper_spec = importlib.util.spec_from_file_location(
        "hex_notices", SCRIPT.parents[2] / "verify-package-contents/scripts/notices.py"
    )
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    for notice in (b"canonical", b"stale"):
        transport = Mock(return_value=b'{"version":"1.2.3"}')
        payload = tarball(notice=notice)
        if notice == b"canonical":
            module.publish_verified(
                payload,
                "demo",
                "1.2.3",
                {"THIRD_PARTY_LICENSES": b"canonical"},
                "key",
                replace=False,
                verifier=helper.verify_archive_bytes,
                transport=transport,
            )
            assert transport.call_count == 1
            assert transport.call_args.args[0].data is payload
        else:
            with pytest.raises(ValueError, match="differs from canonical THIRD_PARTY_LICENSES"):
                module.publish_verified(
                    payload,
                    "demo",
                    "1.2.3",
                    {"THIRD_PARTY_LICENSES": b"canonical"},
                    "key",
                    replace=False,
                    verifier=helper.verify_archive_bytes,
                    transport=transport,
                )
            transport.assert_not_called()


def test_api_key_header_failure_does_not_expose_the_key():
    transport = Mock()
    key = "private-value\ninvalid"
    with pytest.raises(ValueError, match="invalid HTTP header characters") as error:
        module.publish_verified(
            tarball(),
            "demo",
            "1.2.3",
            {},
            key,
            replace=False,
            verifier=Mock(),
            metadata_reader=Mock(return_value=("demo", "1.2.3")),
            transport=transport,
        )
    assert key not in str(error.value)
    transport.assert_not_called()
