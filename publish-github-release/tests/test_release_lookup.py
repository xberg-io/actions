"""Tests for release_lookup.py."""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import release_lookup  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_DRAFT = {"id": 321, "tag_name": "v1.0.0", "draft": True, "upload_url": "https://uploads/{?name,label}"}
_PUBLISHED = {"id": 123, "tag_name": "v0.9.0", "draft": False}


def _responses(mocker: MockerFixture, *payloads: Any) -> Any:
    """Patch urlopen so each successive call returns the next payload.

    An `Exception` instance in `payloads` is raised for that call instead.
    """

    def make(payload: Any) -> Any:
        if isinstance(payload, Exception):
            return payload
        response = mocker.MagicMock()
        response.read.return_value = json.dumps(payload).encode()
        response.__enter__.return_value = response
        return response

    return mocker.patch.object(
        release_lookup.urllib.request,
        "urlopen",
        side_effect=[make(payload) for payload in payloads],
    )


def _not_found() -> Exception:
    return release_lookup.urllib.error.HTTPError(
        "https://api.github.com/test", 404, "Not Found", {}, BytesIO(b'{"message":"Not Found"}')
    )


def test_find_release_by_tag_finds_a_draft_in_the_listing(mocker: MockerFixture) -> None:
    """The whole point: a draft is invisible to /releases/tags/{tag} but present in the listing."""
    _responses(mocker, [_PUBLISHED, _DRAFT])

    assert release_lookup.find_release_by_tag("owner", "repo", "v1.0.0", "token") == _DRAFT


def test_find_release_by_tag_uses_the_listing_endpoint_first(mocker: MockerFixture) -> None:
    urlopen = _responses(mocker, [_DRAFT])

    release_lookup.find_release_by_tag("owner", "repo", "v1.0.0", "token")

    requested = urlopen.call_args_list[0].args[0].full_url
    assert "/releases?per_page=100&page=1" in requested
    assert "/releases/tags/" not in requested


def test_find_release_by_tag_falls_back_to_the_by_tag_endpoint(mocker: MockerFixture) -> None:
    """A token that cannot list drafts still resolves a published release."""
    _responses(mocker, _not_found(), _PUBLISHED)

    assert release_lookup.find_release_by_tag("owner", "repo", "v0.9.0", "token") == _PUBLISHED


def test_find_release_by_tag_returns_none_when_the_release_does_not_exist(mocker: MockerFixture) -> None:
    _responses(mocker, [], _not_found())

    assert release_lookup.find_release_by_tag("owner", "repo", "v9.9.9", "token") is None


def test_find_release_in_listing_pages_until_it_finds_the_tag(mocker: MockerFixture) -> None:
    first_page = [{"id": index, "tag_name": f"v0.{index}.0"} for index in range(release_lookup.RELEASES_PER_PAGE)]
    urlopen = _responses(mocker, first_page, [_DRAFT])

    assert release_lookup.find_release_in_listing("owner", "repo", "v1.0.0", "token") == _DRAFT
    assert urlopen.call_count == 2
    assert "page=2" in urlopen.call_args_list[1].args[0].full_url


def test_find_release_in_listing_stops_on_a_short_page(mocker: MockerFixture) -> None:
    """A page shorter than per_page is the last one; paging on would burn API calls."""
    urlopen = _responses(mocker, [_PUBLISHED])

    assert release_lookup.find_release_in_listing("owner", "repo", "v1.0.0", "token") is None
    assert urlopen.call_count == 1


def test_find_release_in_listing_gives_up_at_the_page_cap(mocker: MockerFixture) -> None:
    full_page = [{"id": index, "tag_name": f"v0.{index}.0"} for index in range(release_lookup.RELEASES_PER_PAGE)]
    urlopen = _responses(mocker, *[full_page] * release_lookup.MAX_RELEASE_PAGES)

    assert release_lookup.find_release_in_listing("owner", "repo", "v1.0.0", "token") is None
    assert urlopen.call_count == release_lookup.MAX_RELEASE_PAGES
