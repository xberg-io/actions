"""Unit tests for ensure_release.py."""

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    @patch("ensure_release.time.sleep")
    @patch("ensure_release.github_request")
    def test_release_not_exists(self, mock_request, mock_sleep) -> None:
        """Test getting non-existent release returns None."""
        mock_request.return_value = (404, {})

        result = ensure_release.get_release_by_tag("owner", "repo", "v3.0.0", "token")

        assert result is None
        assert mock_sleep.call_count == 19

    @patch("ensure_release.time.sleep")
    @patch("ensure_release.github_request")
    def test_release_propagation_retry_succeeds(self, mock_request, mock_sleep) -> None:
        """Test retrying on 404 (read-replica lag) until release appears."""
        release_data = {"id": 999, "tag_name": "v3.1.0", "draft": True}
        mock_request.side_effect = [
            (404, {}),
            (404, {}),
            (200, release_data),
        ]

        result = ensure_release.get_release_by_tag("owner", "repo", "v3.1.0", "token")

        assert result == release_data
        assert mock_sleep.call_count == 2
        assert mock_request.call_count == 3

    @patch("ensure_release.time.sleep")
    @patch("ensure_release.github_request")
    def test_release_exhausts_retries_returns_none(self, mock_request, mock_sleep) -> None:
        """Test exhausting all 20 retries on 404 returns None (Gap 1 pre-check)."""
        mock_request.return_value = (404, {})

        result = ensure_release.get_release_by_tag("owner", "repo", "v4.0.0", "token")

        assert result is None
        assert mock_sleep.call_count == 19
        assert mock_request.call_count == 20


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


class TestTagExistsOnGit(unittest.TestCase):
    """Test tag_exists_on_git function (Gap 1)."""

    @patch("ensure_release.github_request")
    def test_tag_exists_returns_true(self, mock_request) -> None:
        """Test tag exists on git returns True."""
        mock_request.return_value = (200, {"ref": "refs/tags/v1.0.0"})

        result = ensure_release.tag_exists_on_git("owner", "repo", "v1.0.0", "token")

        assert result is True
        mock_request.assert_called_once_with(
            "GET", "https://api.github.com/repos/owner/repo/git/refs/tags/v1.0.0", "token"
        )

    @patch("ensure_release.github_request")
    def test_tag_not_exists_returns_false(self, mock_request) -> None:
        """Test tag does not exist on git returns False."""
        mock_request.return_value = (404, {})

        result = ensure_release.tag_exists_on_git("owner", "repo", "v2.0.0", "token")

        assert result is False


class TestListReleases(unittest.TestCase):
    """Test list_releases function (Gap 3)."""

    @patch("ensure_release.github_request")
    def test_list_releases_success(self, mock_request) -> None:
        """Test listing releases returns list."""
        releases = [
            {"id": 1, "tag_name": "v1.0.0", "name": "v1.0.0"},
            {"id": 2, "tag_name": "untagged-xyz", "name": "v1.1.0"},
        ]
        mock_request.return_value = (200, releases)

        result = ensure_release.list_releases("owner", "repo", "token")

        assert result == releases

    @patch("ensure_release.github_request")
    def test_list_releases_empty(self, mock_request) -> None:
        """Test listing releases when empty returns empty list."""
        mock_request.return_value = (200, [])

        result = ensure_release.list_releases("owner", "repo", "token")

        assert result == []

    @patch("ensure_release.github_request")
    def test_list_releases_error_returns_empty(self, mock_request) -> None:
        """Test listing releases on error returns empty list."""
        mock_request.return_value = (500, {"message": "error"})

        result = ensure_release.list_releases("owner", "repo", "token")

        assert result == []


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

    @patch("ensure_release.github_request")
    def test_update_tag_name(self, mock_request) -> None:
        """Test updating tag_name (Gap 2)."""
        updated_data = {"id": 456, "tag_name": "v2.0.0", "draft": False}
        mock_request.return_value = (200, updated_data)

        result = ensure_release.update_release("owner", "repo", 456, tag_name="v2.0.0", token="token")

        assert result == updated_data

        call_args = mock_request.call_args
        body = call_args[0][3]
        assert body["tag_name"] == "v2.0.0"

    @patch("ensure_release.github_request")
    def test_update_both_draft_and_tag_name(self, mock_request) -> None:
        """Test updating both draft and tag_name."""
        updated_data = {"id": 456, "tag_name": "v2.0.0", "draft": False}
        mock_request.return_value = (200, updated_data)

        result = ensure_release.update_release("owner", "repo", 456, draft=False, tag_name="v2.0.0", token="token")

        assert result == updated_data

        call_args = mock_request.call_args
        body = call_args[0][3]
        assert body["draft"] is False
        assert body["tag_name"] == "v2.0.0"


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

        with (
            patch("ensure_release.create_release") as mock_create,
            patch("ensure_release.tag_exists_on_git") as mock_tag_exists,
            patch("ensure_release.list_releases") as mock_list,
        ):
            mock_create.return_value = {"id": 123, "tag_name": "v1.0.0"}
            mock_tag_exists.return_value = True
            mock_list.return_value = []

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
    def test_main_release_exists_with_broken_tag_repairs(self, mock_get, mock_update) -> None:
        """Test Gap 2: existing release with broken tag_name is repaired."""
        mock_get.return_value = {"id": 456, "tag_name": "untagged-broken", "draft": False}
        mock_update.return_value = {"id": 456, "tag_name": "v1.0.0", "draft": False}

        with patch("sys.stdout", new=StringIO()) as mock_stdout:
            with patch("sys.stderr", new=StringIO()) as mock_stderr:
                ensure_release.main()
                output = mock_stdout.getvalue()
                stderr = mock_stderr.getvalue()
                assert "Repaired tag_name to v1.0.0" in output
                assert "Warning: release has tag_name=untagged-broken" in stderr

        mock_update.assert_called_once_with("owner", "repo", 456, tag_name="v1.0.0", token="token123")

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
    def test_main_release_exists_broken_tag_patch_fails_exits_1(self, mock_get, mock_update) -> None:
        """Test Gap 2: if PATCH to fix existing release tag_name fails, exit 1."""
        mock_get.return_value = {"id": 456, "tag_name": "untagged-broken", "draft": False}
        mock_update.return_value = {"id": 456, "tag_name": "untagged-still-broken", "draft": False}

        with pytest.raises(SystemExit) as ctx:
            ensure_release.main()

        assert ctx.value.code == 1

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
            mock_update.assert_called_once_with("owner", "repo", 456, draft=False, token="token123")

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

    @patch("ensure_release.time.sleep")
    @patch("ensure_release.list_releases")
    @patch("ensure_release.tag_exists_on_git")
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
    def test_main_retries_exhausted_tag_missing_exits_gap1(
        self, mock_get, mock_tag_exists, mock_list, mock_sleep
    ) -> None:
        """Test Gap 1: pre-creation polling exhausted, tag missing on git refs → exit 1."""
        mock_get.return_value = None
        mock_tag_exists.return_value = False

        with pytest.raises(SystemExit) as ctx:
            ensure_release.main()

        assert ctx.value.code == 1
        assert mock_tag_exists.call_count == 12

    @patch("ensure_release.update_release")
    @patch("ensure_release.create_release")
    @patch("ensure_release.list_releases")
    @patch("ensure_release.tag_exists_on_git")
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
    def test_main_create_release_wrong_tag_name_repairs_gap2(
        self, mock_get, mock_tag_exists, mock_list, mock_create, mock_update
    ) -> None:
        """Test Gap 2: create_release returns untagged-..., script PATCHes it."""
        mock_get.return_value = None
        mock_tag_exists.return_value = True
        mock_list.return_value = []
        mock_create.return_value = {"id": 123, "tag_name": "untagged-xyz", "draft": False}
        mock_update.return_value = {"id": 123, "tag_name": "v1.0.0", "draft": False}

        with patch("sys.stdout", new=StringIO()) as mock_stdout:
            ensure_release.main()
            output = mock_stdout.getvalue()
            assert "Repaired tag_name to v1.0.0" in output

        mock_update.assert_called()
        call_kwargs = [call[1] for call in mock_update.call_args_list if "tag_name" in call[1]]
        assert any(call.get("tag_name") == "v1.0.0" for call in call_kwargs)

    @patch("ensure_release.update_release")
    @patch("ensure_release.create_release")
    @patch("ensure_release.list_releases")
    @patch("ensure_release.tag_exists_on_git")
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
    def test_main_preexisting_broken_draft_repaired_gap3(
        self, mock_get, mock_tag_exists, mock_list, mock_create, mock_update
    ) -> None:
        """Test Gap 3: pre-existing broken draft found and PATCHead in-place."""
        mock_get.return_value = None
        mock_tag_exists.return_value = True
        mock_list.return_value = [{"id": 999, "tag_name": "untagged-broken", "name": "v1.0.0", "draft": True}]
        mock_update.return_value = {"id": 999, "tag_name": "v1.0.0", "draft": True}

        with patch("sys.stdout", new=StringIO()) as mock_stdout:
            ensure_release.main()
            output = mock_stdout.getvalue()
            assert "Found pre-existing broken draft" in output
            assert "Repaired broken draft" in output

        mock_create.assert_not_called()
        mock_update.assert_called_once()

    @patch("ensure_release.update_release")
    @patch("ensure_release.create_release")
    @patch("ensure_release.list_releases")
    @patch("ensure_release.tag_exists_on_git")
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
    def test_main_create_release_patch_fails_exits(
        self, mock_get, mock_tag_exists, mock_list, mock_create, mock_update
    ) -> None:
        """Test Gap 2: if PATCH to fix tag_name fails, exit 1."""
        mock_get.return_value = None
        mock_tag_exists.return_value = True
        mock_list.return_value = []
        mock_create.return_value = {"id": 123, "tag_name": "untagged-xyz", "draft": False}
        mock_update.return_value = {"id": 123, "tag_name": "untagged-xyz", "draft": False}

        with pytest.raises(SystemExit) as ctx:
            ensure_release.main()

        assert ctx.value.code == 1

    @patch("ensure_release.time.sleep")
    @patch("ensure_release.create_release")
    @patch("ensure_release.list_releases")
    @patch("ensure_release.tag_exists_on_git")
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
    def test_main_pre_creation_tag_polling_succeeds(
        self, mock_get, mock_tag_exists, mock_list, mock_create, mock_sleep
    ) -> None:
        """Test pre-creation tag-existence polling: tag appears on retry, create succeeds."""
        mock_get.return_value = None
        mock_tag_exists.side_effect = [False, True]
        mock_list.return_value = []
        mock_create.return_value = {"id": 123, "tag_name": "v1.0.0", "draft": False}

        with patch("sys.stdout", new=StringIO()) as mock_stdout:
            ensure_release.main()
            output = mock_stdout.getvalue()
            assert "Creating release v1.0.0" in output
            assert "Release v1.0.0 ready" in output

        assert mock_tag_exists.call_count == 2
        mock_sleep.assert_called_once()

    @patch("ensure_release.time.sleep")
    @patch("ensure_release.create_release")
    @patch("ensure_release.list_releases")
    @patch("ensure_release.tag_exists_on_git")
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
    def test_main_pre_creation_tag_polling_timeout_exits(
        self, mock_get, mock_tag_exists, mock_list, mock_create, mock_sleep
    ) -> None:
        """Test pre-creation tag-existence polling: tag never appears, exit 1."""
        mock_get.return_value = None
        mock_tag_exists.return_value = False
        mock_list.return_value = []

        with pytest.raises(SystemExit) as ctx:
            ensure_release.main()

        assert ctx.value.code == 1
        assert mock_tag_exists.call_count == 12
        assert mock_sleep.call_count == 11


if __name__ == "__main__":
    unittest.main()
