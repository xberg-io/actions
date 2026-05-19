"""Unit tests for ensure_release.py."""

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import ensure_release  # type: ignore[import-not-found]
import pytest


class TestGitHubRequest(unittest.TestCase):
    """Test github_request function."""

    @patch("ensure_release.urllib.request.urlopen")
    def test_get_success_200(self, mock_urlopen) -> None:
        """Test successful GET request returning 200 with JSON."""
        response_data = {"id": 123, "tag_name": "v1.0.0"}
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        mock_urlopen.return_value = mock_response

        status, data = ensure_release.github_request("GET", "http://api.github.com/test", "token123")

        assert status == 200
        assert data == response_data

    @patch("ensure_release.urllib.request.urlopen")
    def test_get_not_found_404(self, mock_urlopen) -> None:
        """Test GET request returning 404 (treated as graceful not-found)."""
        from io import BytesIO

        mock_error = ensure_release.urllib.error.HTTPError(
            "http://api.github.com/test", 404, "Not Found", {}, BytesIO(b"")
        )
        mock_urlopen.side_effect = mock_error

        status, data = ensure_release.github_request("GET", "http://api.github.com/test", "token123")

        assert status == 404
        assert data == {}

    @patch("ensure_release.urllib.request.urlopen")
    def test_post_error_500(self, mock_urlopen) -> None:
        """Test POST request returning 500 exits with error."""
        from io import BytesIO

        error_response = BytesIO(b'{"message": "Server error"}')
        mock_error = ensure_release.urllib.error.HTTPError(
            "http://api.github.com/test", 500, "Server Error", {}, error_response
        )
        mock_urlopen.side_effect = mock_error

        with pytest.raises(SystemExit) as ctx:
            ensure_release.github_request("POST", "http://api.github.com/test", "token123", {"foo": "bar"})

        assert ctx.value.code == 1


class TestGetReleaseByTag(unittest.TestCase):
    """Test get_release_by_tag function."""

    @patch("ensure_release.github_request")
    def test_release_exists(self, mock_request) -> None:
        """Test getting existing release returns data."""
        release_data = {"id": 456, "tag_name": "v2.0.0", "draft": False}
        mock_request.return_value = (200, release_data)

        result = ensure_release.get_release_by_tag("owner", "repo", "v2.0.0", "token")

        assert result == release_data
        mock_request.assert_called_once_with(
            "GET", "https://api.github.com/repos/owner/repo/releases/tags/v2.0.0", "token"
        )

    @patch("ensure_release.github_request")
    def test_release_not_exists(self, mock_request) -> None:
        """Test getting non-existent release returns None."""
        mock_request.return_value = (404, {})

        result = ensure_release.get_release_by_tag("owner", "repo", "v3.0.0", "token")

        assert result is None


class TestCreateRelease(unittest.TestCase):
    """Test create_release function."""

    @patch("ensure_release.github_request")
    def test_create_with_notes(self, mock_request) -> None:
        """Test creating release with literal notes."""
        release_data = {"id": 789, "tag_name": "v1.0.0"}
        mock_request.return_value = (201, release_data)

        result = ensure_release.create_release(
            "owner",
            "repo",
            "v1.0.0",
            "Release 1.0.0",
            generate_notes=True,
            draft=False,
            prerelease=False,
            notes="Manual notes here",
            token="token",
        )

        assert result == release_data

        # Verify notes took precedence over generate_notes
        call_args = mock_request.call_args
        body = call_args[0][3]
        assert body["body"] == "Manual notes here"
        assert "generate_release_notes" not in body

    @patch("ensure_release.github_request")
    def test_create_with_generate_notes(self, mock_request) -> None:
        """Test creating release with auto-generated notes."""
        release_data = {"id": 789, "tag_name": "v1.0.0"}
        mock_request.return_value = (201, release_data)

        result = ensure_release.create_release(
            "owner",
            "repo",
            "v1.0.0",
            "Release 1.0.0",
            generate_notes=True,
            draft=False,
            prerelease=False,
            notes="",
            token="token",
        )

        assert result == release_data

        # Verify generate_release_notes is set
        call_args = mock_request.call_args
        body = call_args[0][3]
        assert body.get("generate_release_notes")
        assert "body" not in body

    @patch("ensure_release.github_request")
    def test_create_with_target(self, mock_request) -> None:
        """Test creating release with target commitish."""
        release_data = {"id": 789, "tag_name": "v1.0.0"}
        mock_request.return_value = (201, release_data)

        ensure_release.create_release(
            "owner",
            "repo",
            "v1.0.0",
            "Release 1.0.0",
            generate_notes=False,
            draft=False,
            prerelease=False,
            target="main",
            token="token",
        )

        call_args = mock_request.call_args
        body = call_args[0][3]
        assert body["target_commitish"] == "main"


class TestUpdateRelease(unittest.TestCase):
    """Test update_release function."""

    @patch("ensure_release.github_request")
    def test_update_draft_to_false(self, mock_request) -> None:
        """Test updating draft release to published."""
        updated_data = {"id": 456, "tag_name": "v2.0.0", "draft": False}
        mock_request.return_value = (200, updated_data)

        result = ensure_release.update_release("owner", "repo", 456, draft=False, token="token")

        assert result == updated_data

        call_args = mock_request.call_args
        body = call_args[0][3]
        assert not body["draft"]


class TestMain(unittest.TestCase):
    """Test main function."""

    @patch("ensure_release.update_release")
    @patch("ensure_release.get_release_by_tag")
    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_TITLE": "Release 1.0.0",
            "INPUT_GENERATE_NOTES": "false",
            "INPUT_DRAFT": "false",
            "INPUT_PRERELEASE": "false",
            "INPUT_NOTES": "",
            "INPUT_TARGET": "",
            "INPUT_DRY_RUN": "false",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_release_not_exists_creates_new(self, mock_get, mock_update) -> None:
        """Test creating release when it doesn't exist."""
        mock_get.return_value = None

        with patch("ensure_release.create_release") as mock_create:
            mock_create.return_value = {"id": 123}

            with patch("sys.stdout", new=StringIO()) as mock_stdout:
                ensure_release.main()
                output = mock_stdout.getvalue()
                assert "Creating release v1.0.0" in output
                assert "Release v1.0.0 ready" in output

    @patch("ensure_release.update_release")
    @patch("ensure_release.get_release_by_tag")
    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_TITLE": "Release 1.0.0",
            "INPUT_GENERATE_NOTES": "false",
            "INPUT_DRAFT": "false",
            "INPUT_PRERELEASE": "false",
            "INPUT_NOTES": "",
            "INPUT_TARGET": "",
            "INPUT_DRY_RUN": "false",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_release_exists_not_draft(self, mock_get, mock_update) -> None:
        """Test when release exists and is not draft."""
        mock_get.return_value = {"id": 123, "tag_name": "v1.0.0", "draft": False}

        with patch("sys.stdout", new=StringIO()) as mock_stdout:
            ensure_release.main()
            output = mock_stdout.getvalue()
            assert "Release v1.0.0 already exists" in output
            assert "Release v1.0.0 ready" in output
            mock_update.assert_not_called()

    @patch("ensure_release.update_release")
    @patch("ensure_release.get_release_by_tag")
    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_TITLE": "Release 1.0.0",
            "INPUT_GENERATE_NOTES": "false",
            "INPUT_DRAFT": "false",
            "INPUT_PRERELEASE": "false",
            "INPUT_NOTES": "",
            "INPUT_TARGET": "",
            "INPUT_DRY_RUN": "false",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_release_exists_as_draft_publish(self, mock_get, mock_update) -> None:
        """Test publishing draft release when INPUT_DRAFT=false."""
        mock_get.return_value = {"id": 456, "tag_name": "v1.0.0", "draft": True}
        mock_update.return_value = {"id": 456, "draft": False}

        with patch("sys.stdout", new=StringIO()) as mock_stdout:
            ensure_release.main()
            output = mock_stdout.getvalue()
            assert "Publishing draft release v1.0.0" in output
            mock_update.assert_called_once_with("owner", "repo", 456, False, "token123")

    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_TITLE": "Release 1.0.0",
            "INPUT_GENERATE_NOTES": "true",
            "INPUT_DRAFT": "false",
            "INPUT_PRERELEASE": "false",
            "INPUT_NOTES": "",
            "INPUT_TARGET": "",
            "INPUT_DRY_RUN": "true",
            "GH_TOKEN": "token123",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_dry_run_no_network_calls(self, *args) -> None:
        """Test dry-run mode prints only, makes no network calls."""
        with patch("ensure_release.get_release_by_tag") as mock_get:
            with patch("sys.stdout", new=StringIO()) as mock_stdout:
                with pytest.raises(SystemExit) as ctx:
                    ensure_release.main()
                assert ctx.value.code == 0
                output = mock_stdout.getvalue()
                assert "[dry-run]" in output
                assert "Would create/ensure release" in output
                mock_get.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    def test_main_missing_tag_exits(self) -> None:
        """Test missing INPUT_TAG causes exit."""
        with pytest.raises(SystemExit) as ctx:
            ensure_release.main()
        assert ctx.value.code == 1

    @patch.dict(
        "os.environ",
        {
            "INPUT_TAG": "v1.0.0",
            "INPUT_TITLE": "",
            "INPUT_GENERATE_NOTES": "false",
            "INPUT_DRAFT": "false",
            "INPUT_PRERELEASE": "false",
            "INPUT_NOTES": "",
            "INPUT_TARGET": "",
            "INPUT_DRY_RUN": "false",
            "GH_TOKEN": "",
            "GITHUB_REPOSITORY": "owner/repo",
        },
    )
    def test_main_missing_token_exits(self) -> None:
        """Test missing GH_TOKEN causes exit."""
        with pytest.raises(SystemExit) as ctx:
            ensure_release.main()
        assert ctx.value.code == 1


if __name__ == "__main__":
    unittest.main()
