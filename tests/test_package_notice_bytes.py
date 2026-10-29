"""Notice checks inspect real archive entries, including nested package containers."""

import importlib.util
import io
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-package-contents/scripts/notices.py"
spec = importlib.util.spec_from_file_location("package_notices", SCRIPT)
notices = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = notices
spec.loader.exec_module(notices)
NOTICE = "THIRD_PARTY_LICENSES.md"
CONTENT = b"Canonical third-party notice\r\nCopyright fixture\n"


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content, kind in entries:
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (kind | 0o644) << 16
            archive.writestr(entry, content)
    return output.getvalue()


def tar_bytes(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content, kind in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(content) if kind == tarfile.REGTYPE else 0
            entry.linkname = "elsewhere" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
            archive.addfile(entry, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
    return output.getvalue()


def package_bytes(artifact_format, content=CONTENT, extra=()):
    if artifact_format == "wheel":
        entries = [("fixture-1.0.dist-info/METADATA", b"Name: fixture\nVersion: 1.0\n", stat.S_IFREG)]
        return zip_bytes([*entries, (f"fixture-1.0.dist-info/licenses/{NOTICE}", content, stat.S_IFREG), *extra])
    if artifact_format in ("jar", "nuget"):
        name = f"META-INF/{NOTICE}" if artifact_format == "jar" else NOTICE
        return zip_bytes([(name, content, stat.S_IFREG), *extra])
    if artifact_format == "sdist":
        project = b'[project]\nname="fixture"\nversion="1.0"\nlicense-files=["THIRD_PARTY_LICENSES.md"]\n'
        return tar_bytes(
            [
                ("fixture-1.0/pyproject.toml", project, tarfile.REGTYPE),
                ("fixture-1.0/PKG-INFO", b"Name: fixture\nVersion: 1.0\n", tarfile.REGTYPE),
                (f"fixture-1.0/{NOTICE}", content, tarfile.REGTYPE),
                *extra,
            ]
        )
    inner = tar_bytes([(NOTICE, content, tarfile.REGTYPE), *extra])
    member = "data.tar.gz" if artifact_format == "gem" else "contents.tar.gz"
    return tar_bytes([(member, inner, tarfile.REGTYPE)])


@pytest.mark.parametrize("artifact_format", ["wheel", "sdist", "gem", "jar", "nuget", "hex"])
def test_should_compare_complete_canonical_bytes_in_every_supported_format(artifact_format):
    assert notices.verify_archive_bytes(package_bytes(artifact_format), artifact_format, {NOTICE: CONTENT}) is None


@pytest.mark.parametrize("artifact_format", ["wheel", "sdist", "gem", "jar", "nuget", "hex"])
def test_should_reject_corruption_in_every_supported_format(artifact_format):
    with pytest.raises(notices.NoticeVerificationError, match="differs from canonical"):
        notices.verify_archive_bytes(
            package_bytes(artifact_format, CONTENT + b"corrupt"), artifact_format, {NOTICE: CONTENT}
        )


@pytest.mark.parametrize("artifact_format", ["wheel", "sdist", "gem", "jar", "nuget", "hex"])
def test_should_reject_empty_archive_instead_of_reporting_zero_work(artifact_format):
    payload = zip_bytes([]) if artifact_format in ("wheel", "jar", "nuget") else tar_bytes([])
    with pytest.raises(notices.NoticeVerificationError):
        notices.verify_archive_bytes(payload, artifact_format, {NOTICE: CONTENT})


@pytest.mark.parametrize("alias", [f"./META-INF/{NOTICE}", f"META-INF//{NOTICE}", f"META-INF/{NOTICE.lower()}"])
def test_should_reject_effective_notice_aliases(alias):
    with pytest.raises(notices.NoticeVerificationError, match=r"duplicate|alias"):
        notices.verify_archive_bytes(
            package_bytes("jar", extra=[(alias, CONTENT, stat.S_IFREG)]), "jar", {NOTICE: CONTENT}
        )


def test_should_preserve_case_sensitive_java_class_names():
    payload = package_bytes(
        "jar", extra=[("org/Foo.class", b"upper", stat.S_IFREG), ("org/foo.class", b"lower", stat.S_IFREG)]
    )
    assert notices.verify_archive_bytes(payload, "jar", {NOTICE: CONTENT}) is None


@pytest.mark.parametrize("kind", [stat.S_IFLNK, stat.S_IFDIR])
def test_should_reject_nonregular_zip_notice(kind):
    payload = zip_bytes([(f"META-INF/{NOTICE}", CONTENT, kind)])
    with pytest.raises(notices.NoticeVerificationError, match="regular"):
        notices.verify_archive_bytes(payload, "jar", {NOTICE: CONTENT})


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE])
def test_should_reject_nonregular_nested_notice(kind):
    inner = tar_bytes([(NOTICE, CONTENT, kind)])
    payload = tar_bytes([("contents.tar.gz", inner, tarfile.REGTYPE)])
    with pytest.raises(notices.NoticeVerificationError, match="regular"):
        notices.verify_archive_bytes(payload, "hex", {NOTICE: CONTENT})


def test_should_reject_sdist_dependency_notice_when_distribution_notice_is_missing():
    project = b'[project]\nname="fixture"\nversion="1.0"\nlicense-files=["THIRD_PARTY_LICENSES.md"]\n'
    payload = tar_bytes(
        [
            ("fixture-1.0/pyproject.toml", project, tarfile.REGTYPE),
            ("fixture-1.0/PKG-INFO", b"Name: fixture\n", tarfile.REGTYPE),
            (f"fixture-1.0/crates/dependency/{NOTICE}", CONTENT, tarfile.REGTYPE),
        ]
    )
    with pytest.raises(notices.NoticeVerificationError, match=r"missing.*THIRD_PARTY"):
        notices.verify_archive_bytes(payload, "sdist", {NOTICE: CONTENT})


def test_should_require_sdist_notice_in_actual_pyproject_license_declaration():
    payload = tar_bytes(
        [
            ("fixture-1.0/pyproject.toml", b'[project]\nlicense-files=["LICENSE"]\n', tarfile.REGTYPE),
            ("fixture-1.0/PKG-INFO", b"Name: fixture\n", tarfile.REGTYPE),
            (f"fixture-1.0/{NOTICE}", CONTENT, tarfile.REGTYPE),
        ]
    )
    with pytest.raises(notices.NoticeVerificationError, match="license-files"):
        notices.verify_archive_bytes(payload, "sdist", {NOTICE: CONTENT})


@pytest.mark.parametrize("names", [[], [" "], [NOTICE, NOTICE], ["../notice"], ["/notice"], ["notice\\alias"]])
def test_should_reject_empty_or_ambiguous_required_source_inventory(tmp_path, names):
    with pytest.raises(notices.NoticeVerificationError):
        notices.load_notices(tmp_path, names)


def test_should_load_exact_nonempty_source_bytes(tmp_path):
    (tmp_path / NOTICE).write_bytes(CONTENT)
    assert notices.load_notices(tmp_path, [NOTICE]) == {NOTICE: CONTENT}


def test_should_reject_missing_and_empty_canonical_sources(tmp_path):
    with pytest.raises(notices.NoticeVerificationError):
        notices.load_notices(tmp_path, [NOTICE])
    (tmp_path / NOTICE).write_bytes(b"")
    with pytest.raises(notices.NoticeVerificationError, match="empty"):
        notices.load_notices(tmp_path, [NOTICE])


def test_should_reject_empty_notice_mapping_at_shared_helper_boundary():
    with pytest.raises(notices.NoticeVerificationError, match="empty"):
        notices.verify_archive_bytes(package_bytes("jar"), "jar", {})


@pytest.mark.parametrize("artifact_format,member", [("gem", "data.tar.gz"), ("hex", "contents.tar.gz")])
def test_should_reject_missing_nested_notice_in_an_existing_payload(artifact_format, member):
    inner = tar_bytes([("lib/fixture", b"payload", tarfile.REGTYPE)])
    payload = tar_bytes([(member, inner, tarfile.REGTYPE)])
    with pytest.raises(notices.NoticeVerificationError, match="missing packaged notice"):
        notices.verify_archive_bytes(payload, artifact_format, {NOTICE: CONTENT})


@pytest.mark.parametrize("member", ["contents.tar.gz", "./contents.tar.gz", "contents.tar.gz/"])
def test_should_reject_duplicate_nested_container_aliases(member):
    inner = tar_bytes([(NOTICE, CONTENT, tarfile.REGTYPE)])
    payload = tar_bytes([("contents.tar.gz", inner, tarfile.REGTYPE), (member, inner, tarfile.REGTYPE)])
    with pytest.raises(notices.NoticeVerificationError, match="duplicate"):
        notices.verify_archive_bytes(payload, "hex", {NOTICE: CONTENT})


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE])
def test_should_reject_nonregular_nested_container(kind):
    payload = tar_bytes([("contents.tar.gz", b"", kind)])
    with pytest.raises(notices.NoticeVerificationError, match="regular"):
        notices.verify_archive_bytes(payload, "hex", {NOTICE: CONTENT})


@pytest.mark.parametrize("name", [f"META-INF\\{NOTICE}", f"META-INF/../META-INF/{NOTICE}", f"/META-INF/{NOTICE}"])
def test_should_reject_unsafe_notice_paths_even_without_another_entry(name):
    payload = zip_bytes([(name, CONTENT, stat.S_IFREG)])
    with pytest.raises(notices.NoticeVerificationError, match="unsafe"):
        notices.verify_archive_bytes(payload, "jar", {NOTICE: CONTENT})


def test_should_reject_a_canonical_source_symlink(tmp_path):
    (tmp_path / "other").write_bytes(CONTENT)
    (tmp_path / NOTICE).symlink_to(tmp_path / "other")
    with pytest.raises(notices.NoticeVerificationError, match="regular"):
        notices.load_notices(tmp_path, [NOTICE])


def test_should_reject_a_dos_directory_masquerading_as_a_zip_notice():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        entry = zipfile.ZipInfo(NOTICE)
        entry.external_attr = 0x10
        archive.writestr(entry, CONTENT)
    with pytest.raises(notices.NoticeVerificationError, match="regular"):
        notices.verify_archive_bytes(stream.getvalue(), "nuget", {NOTICE: CONTENT})


@pytest.mark.parametrize("artifact_format", ["wheel", "sdist", "gem", "jar", "nuget", "hex"])
def test_should_wrap_invalid_archive_payload_as_a_notice_error(artifact_format):
    with pytest.raises(notices.NoticeVerificationError):
        notices.verify_archive_bytes(b"invalid archive", artifact_format, {NOTICE: CONTENT})


def test_should_follow_sdist_declared_license_globs_instead_of_dependency_metadata():
    project = b'[project]\nname="fixture"\nversion="1.0"\nlicense-files=["**/*LICENSES.md"]\n'
    payload = tar_bytes(
        [
            ("fixture-1.0/pyproject.toml", project, tarfile.REGTYPE),
            ("fixture-1.0/PKG-INFO", b"Name: fixture\n", tarfile.REGTYPE),
            ("fixture-1.0/crates/fixture/Cargo.toml", b'[package]\nname="fixture"\n', tarfile.REGTYPE),
            (f"fixture-1.0/{NOTICE}", CONTENT, tarfile.REGTYPE),
        ]
    )
    assert notices.verify_archive_bytes(payload, "sdist", {NOTICE: CONTENT}) is None


@pytest.mark.parametrize("alias", [f"META-INF/{NOTICE}.", f"META-INF/{NOTICE} ", f"META-INF /{NOTICE}"])
def test_should_reject_notice_paths_aliased_by_windows_extraction(alias):
    payload = package_bytes("jar", extra=[(alias, CONTENT, stat.S_IFREG)])
    with pytest.raises(notices.NoticeVerificationError, match="alias"):
        notices.verify_archive_bytes(payload, "jar", {NOTICE: CONTENT})


@pytest.mark.parametrize("kind", [stat.S_IFREG, stat.S_IFLNK])
def test_should_reject_a_notice_below_a_non_directory_ancestor(kind):
    payload = package_bytes("jar", extra=[("META-INF", b"other", kind)])
    with pytest.raises(notices.NoticeVerificationError, match="ancestor"):
        notices.verify_archive_bytes(payload, "jar", {NOTICE: CONTENT})


def test_should_report_missing_stdlib_toml_support_only_for_sdist(monkeypatch):
    def missing_tomllib(name):
        assert name == "tomllib"
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(notices.importlib, "import_module", missing_tomllib)
    assert notices.verify_archive_bytes(package_bytes("jar"), "jar", {NOTICE: CONTENT}) is None
    with pytest.raises(notices.NoticeVerificationError, match="Python 3.11"):
        notices.verify_archive_bytes(package_bytes("sdist"), "sdist", {NOTICE: CONTENT})
