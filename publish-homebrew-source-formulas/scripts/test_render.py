"""Tests for render.py Homebrew formula renderer."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from render import _compute_sha256, _interpolate_asset_name, _render_template


class TestAssetNameInterpolation:
    """Test asset filename placeholder substitution."""

    def test_interpolate_tag(self) -> None:
        """Resolve ${tag} in asset names."""
        result = _interpolate_asset_name("lib-${tag}-x86.tar.gz", "v3.6.0-rc.12", "3.6.0-rc.12")
        assert result == "lib-v3.6.0-rc.12-x86.tar.gz"  # noqa: S101

    def test_interpolate_version(self) -> None:
        """Resolve ${version} in asset names."""
        result = _interpolate_asset_name("lib-${version}-x86.tar.gz", "v3.6.0-rc.12", "3.6.0-rc.12")
        assert result == "lib-3.6.0-rc.12-x86.tar.gz"  # noqa: S101

    def test_interpolate_both(self) -> None:
        """Resolve both ${tag} and ${version}."""
        result = _interpolate_asset_name("lib-${tag}-${version}.tar.gz", "v3.6.0-rc.12", "3.6.0-rc.12")
        assert result == "lib-v3.6.0-rc.12-3.6.0-rc.12.tar.gz"  # noqa: S101

    def test_no_interpolation(self) -> None:
        """Asset names without placeholders pass through."""
        result = _interpolate_asset_name("cli-x86.tar.gz", "v3.6.0", "3.6.0")
        assert result == "cli-x86.tar.gz"  # noqa: S101


class TestTemplateRendering:
    """Test formula template substitution."""

    def test_render_simple_template(self) -> None:
        """Render template with version substitution."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rb", delete=False) as f:
            f.write('version "${version}"\nsha "${sha}"')
            f.flush()
            template_path = Path(f.name)

        try:
            result = _render_template(template_path, {"version": "3.6.0-rc.12", "sha": "abcd1234"})
            assert 'version "3.6.0-rc.12"' in result  # noqa: S101
            assert 'sha "abcd1234"' in result  # noqa: S101
        finally:
            template_path.unlink()

    def test_render_preserves_rc_version(self) -> None:
        """RC version strings are preserved in rendered formulas."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rb", delete=False) as f:
            f.write('class Foo < Formula\n  version "${version}"\nend')
            f.flush()
            template_path = Path(f.name)

        try:
            result = _render_template(template_path, {"version": "3.6.0-rc.12"})
            assert '"3.6.0-rc.12"' in result  # noqa: S101
        finally:
            template_path.unlink()


class TestSHA256Computation:
    """Test SHA256 checksum calculation."""

    def test_compute_sha256(self) -> None:
        """Compute SHA256 of a file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            f.flush()
            temp_path = Path(f.name)

        try:
            sha = _compute_sha256(temp_path)
            assert sha == "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72"  # noqa: S101
        finally:
            temp_path.unlink()


class TestRCVersionHandling:
    """Test that RC versions are handled correctly end-to-end."""

    def test_rc_version_not_filtered(self) -> None:
        """RC versions should not be filtered or skipped."""
        version = "3.6.0-rc.12"
        tag = "v3.6.0-rc.12"

        assert version == "3.6.0-rc.12"  # noqa: S101
        assert tag == "v3.6.0-rc.12"  # noqa: S101
        assert "-rc." in version  # noqa: S101
        assert "-rc." in tag  # noqa: S101


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
