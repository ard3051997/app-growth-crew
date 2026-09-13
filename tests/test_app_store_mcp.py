"""Tests for app_store_mcp server and client."""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app_store_mcp.client import AppStoreClient, AppStoreClientError
from app_store_mcp.server import (
    get_app_details,
    get_keyword_rank,
    get_reviews,
    mcp,
    reply_to_review,
    update_listing,
)


def _completed_process(
    *, stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["asc"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _mock_context(client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock(spec=AppStoreClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


class TestAppStoreClient:
    @patch("app_store_mcp.client.httpx.get")
    def test_resolve_app_id_by_suffix(self, mock_get: MagicMock) -> None:
        client = AppStoreClient()
        app_id = client._resolve_app_id("clone-armies-battle-game-id1291919749")
        assert app_id == "1291919749"
        mock_get.assert_not_called()

    @patch("app_store_mcp.client.httpx.get")
    def test_resolve_app_id_numeric(self, mock_get: MagicMock) -> None:
        client = AppStoreClient()
        app_id = client._resolve_app_id("1515003825")
        assert app_id == "1515003825"
        mock_get.assert_not_called()

    @patch("app_store_mcp.client.httpx.get")
    def test_resolve_app_id_via_lookup(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [{"trackId": 9999}]}
        mock_get.return_value = mock_resp

        client = AppStoreClient()
        app_id = client._resolve_app_id("com.example.iosapp")
        assert app_id == "9999"
        mock_get.assert_called_once_with(
            "https://itunes.apple.com/lookup?bundleId=com.example.iosapp", timeout=10.0
        )


class TestGetKeywordRank:
    @patch("app_store_mcp.client.httpx.get")
    def test_finds_the_apps_rank_in_results(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "results": [
                {"bundleId": "com.other.app"},
                {"bundleId": "com.example.app"},
                {"bundleId": "com.third.app"},
            ]
        }
        mock_get.return_value = mock_resp

        client = AppStoreClient()
        result = client.get_keyword_rank("com.example.app", "pomodoro")

        assert result == {
            "keyword": "pomodoro",
            "rank": 2,
            "total_results": 3,
            "country": "us",
        }
        mock_get.assert_called_once_with(
            "https://itunes.apple.com/search",
            params={"term": "pomodoro", "country": "us", "entity": "software", "limit": 200},
            timeout=15.0,
        )

    @patch("app_store_mcp.client.httpx.get")
    def test_returns_none_rank_when_app_is_not_in_results(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"results": [{"bundleId": "com.other.app"}]}
        mock_get.return_value = mock_resp

        client = AppStoreClient()
        result = client.get_keyword_rank("com.example.app", "pomodoro")

        assert result["rank"] is None
        assert result["total_results"] == 1


class TestAscBackedUpdateListing:
    """update_listing must shell out to the real asc CLI, never fabricate success."""

    @patch("app_store_mcp.client.subprocess.run")
    def test_updates_app_info_fields_via_asc(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(
            stdout=json.dumps({"data": {"id": "loc-1", "attributes": {"name": "New Title"}}})
        )
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value="123456789")  # type: ignore[method-assign]

        result = client.update_listing(
            bundle_id="com.example.app", title="New Title", short_description="New subtitle"
        )

        assert result["status"] == "success"
        assert result["app_id"] == "123456789"
        assert result["updated_fields"] == {
            "title": "New Title",
            "short_description": "New subtitle",
        }
        called_args = mock_run.call_args.args[0]
        assert called_args[0] == "asc"
        assert "--type" in called_args and "app-info" in called_args
        assert "--name" in called_args and "New Title" in called_args
        assert "--subtitle" in called_args and "New subtitle" in called_args

    @patch("app_store_mcp.client.subprocess.run")
    def test_updating_description_resolves_current_version_first(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed_process(stdout=json.dumps({"data": [{"id": "version-1"}]})),
            _completed_process(stdout=json.dumps({"data": {"id": "loc-2"}})),
        ]
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value="123456789")  # type: ignore[method-assign]

        result = client.update_listing(
            bundle_id="com.example.app", full_description="New description"
        )

        assert result["updated_fields"] == {"full_description": "New description"}
        version_call_args = mock_run.call_args_list[1].args[0]
        assert "--version" in version_call_args and "version-1" in version_call_args
        assert "--description" in version_call_args and "New description" in version_call_args

    @patch("app_store_mcp.client.subprocess.run")
    def test_asc_failure_raises_instead_of_faking_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(
            returncode=1, stderr="Error: cannot edit a released version"
        )
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value="123456789")  # type: ignore[method-assign]

        with pytest.raises(AppStoreClientError, match="cannot edit a released version"):
            client.update_listing(bundle_id="com.example.app", title="New Title")

    def test_requires_at_least_one_field(self) -> None:
        client = AppStoreClient()
        with pytest.raises(AppStoreClientError, match="At least one"):
            client.update_listing(bundle_id="com.example.app")

    def test_raises_if_bundle_id_cannot_be_resolved(self) -> None:
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value=None)  # type: ignore[method-assign]
        with pytest.raises(AppStoreClientError, match="Could not resolve"):
            client.update_listing(bundle_id="com.unknown.app", title="New Title")

    @patch("app_store_mcp.client.subprocess.run", side_effect=FileNotFoundError())
    def test_missing_asc_cli_raises_clear_error(self, _mock_run: MagicMock) -> None:
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value="123456789")  # type: ignore[method-assign]
        with pytest.raises(AppStoreClientError, match=r"asc.*not installed"):
            client.update_listing(bundle_id="com.example.app", title="New Title")


class TestEnsureEditableVersion:
    """A real App Store error ("field can not be modified") happens when there is
    no editable draft version -- Apple locks metadata edits to a
    PREPARE_FOR_SUBMISSION/REJECTED version. _ensure_editable_version must create
    one rather than leaving the caller permanently stuck."""

    @patch("app_store_mcp.client.subprocess.run")
    def test_no_op_when_a_draft_version_already_exists(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(
            stdout=json.dumps(
                {
                    "data": [
                        {
                            "attributes": {
                                "appStoreState": "PREPARE_FOR_SUBMISSION",
                                "versionString": "1.2",
                            }
                        }
                    ]
                }
            )
        )
        client = AppStoreClient()

        client._ensure_editable_version("123456789")

        mock_run.assert_called_once()
        called_args = mock_run.call_args.args[0]
        assert "list" in called_args

    @patch("app_store_mcp.client.subprocess.run")
    def test_creates_a_new_patch_version_when_none_are_editable(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "data": [
                            {
                                "attributes": {
                                    "appStoreState": "READY_FOR_SALE",
                                    "versionString": "1.2.3",
                                }
                            }
                        ]
                    }
                )
            ),
            _completed_process(stdout=json.dumps({"data": {"id": "version-new"}})),
        ]
        client = AppStoreClient()

        client._ensure_editable_version("123456789")

        assert mock_run.call_count == 2
        create_args = mock_run.call_args_list[1].args[0]
        assert "create" in create_args
        assert "--version" in create_args and "1.2.4" in create_args

    @patch("app_store_mcp.client.subprocess.run")
    def test_two_part_version_gets_a_patch_component_appended(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "data": [
                            {
                                "attributes": {
                                    "appStoreState": "READY_FOR_SALE",
                                    "versionString": "1.0",
                                }
                            }
                        ]
                    }
                )
            ),
            _completed_process(stdout=json.dumps({"data": {"id": "version-new"}})),
        ]
        client = AppStoreClient()

        client._ensure_editable_version("123456789")

        create_args = mock_run.call_args_list[1].args[0]
        assert "1.0.1" in create_args

    @patch("app_store_mcp.client.subprocess.run", side_effect=RuntimeError("network error"))
    def test_failures_are_logged_not_raised(self, _mock_run: MagicMock) -> None:
        client = AppStoreClient()
        client._ensure_editable_version("123456789")  # must not raise


class TestUpdateListingRetriesOnLockedVersion:
    """update_listing must auto-create a draft version and retry exactly once
    when Apple rejects a metadata edit because no version is editable -- and
    must never retry for any other kind of failure."""

    @patch("app_store_mcp.client.subprocess.run")
    def test_app_info_retries_after_creating_a_draft_version(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed_process(
                returncode=1,
                stderr="Error: localizations update: The field 'name' can not be modified in the current state.",
            ),
            _completed_process(
                stdout=json.dumps(
                    {
                        "data": [
                            {
                                "attributes": {
                                    "appStoreState": "READY_FOR_SALE",
                                    "versionString": "1.0",
                                }
                            }
                        ]
                    }
                )
            ),
            _completed_process(stdout=json.dumps({"data": {"id": "version-new"}})),
            _completed_process(
                stdout=json.dumps({"data": {"id": "loc-1", "attributes": {"name": "New Title"}}})
            ),
        ]
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value="123456789")  # type: ignore[method-assign]

        result = client.update_listing(bundle_id="com.example.app", title="New Title")

        assert result["status"] == "success"
        assert mock_run.call_count == 4

    @patch("app_store_mcp.client.subprocess.run")
    def test_other_asc_errors_are_not_retried(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(returncode=1, stderr="Error: unauthorized")
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value="123456789")  # type: ignore[method-assign]

        with pytest.raises(AppStoreClientError, match="unauthorized"):
            client.update_listing(bundle_id="com.example.app", title="New Title")

        mock_run.assert_called_once()

    @patch("app_store_mcp.client.subprocess.run")
    def test_version_description_retries_after_creating_a_draft_version(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps({"data": [{"id": "version-old"}]})
            ),  # current version
            _completed_process(
                returncode=1,
                stderr="Error: localizations update: The field 'description' can not be modified in the current state.",
            ),
            _completed_process(
                stdout=json.dumps(
                    {
                        "data": [
                            {
                                "attributes": {
                                    "appStoreState": "READY_FOR_SALE",
                                    "versionString": "1.0",
                                }
                            }
                        ]
                    }
                )
            ),
            _completed_process(stdout=json.dumps({"data": {"id": "version-created"}})),
            _completed_process(
                stdout=json.dumps({"data": [{"id": "version-new"}]})
            ),  # re-resolve current version
            _completed_process(stdout=json.dumps({"data": {"id": "loc-2"}})),
        ]
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value="123456789")  # type: ignore[method-assign]

        result = client.update_listing(
            bundle_id="com.example.app", full_description="New description"
        )

        assert result["updated_fields"] == {"full_description": "New description"}
        assert mock_run.call_count == 6


class TestAscBackedReviews:
    """get_reviews/reply_to_review must use the authenticated asc API, not RSS."""

    @patch("app_store_mcp.client.subprocess.run")
    def test_get_reviews_returns_real_asc_review_ids(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(
            stdout=json.dumps(
                {
                    "data": [
                        {
                            "id": "00000063-7bf5-c503-2e23-f36100000000",
                            "attributes": {
                                "rating": 5,
                                "title": "Great",
                                "body": "Loved it",
                                "reviewerNickname": "Cleo",
                                "createdDate": "2026-01-21T05:29:01-08:00",
                                "territory": "USA",
                            },
                        }
                    ]
                }
            )
        )
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value="123456789")  # type: ignore[method-assign]

        reviews = client.get_reviews(bundle_id="com.example.app", max_results=10)

        assert reviews == [
            {
                "review_id": "00000063-7bf5-c503-2e23-f36100000000",
                "author_name": "Cleo",
                "star_rating": 5,
                "comment": "Great\nLoved it",
                "territory": "USA",
                "last_modified": "2026-01-21T05:29:01-08:00",
            }
        ]
        called_args = mock_run.call_args.args[0]
        assert called_args[0] == "asc"
        assert "reviews" in called_args and "--app" in called_args

    def test_get_reviews_raises_if_bundle_id_cannot_be_resolved(self) -> None:
        client = AppStoreClient()
        client._resolve_app_id = MagicMock(return_value=None)  # type: ignore[method-assign]
        with pytest.raises(AppStoreClientError, match="Could not resolve"):
            client.get_reviews(bundle_id="com.unknown.app")

    @patch("app_store_mcp.client.subprocess.run")
    def test_reply_to_review_posts_via_asc(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(stdout=json.dumps({"data": {"id": "resp-1"}}))
        client = AppStoreClient()

        result = client.reply_to_review(review_id="review-1", reply_text="Thanks!")

        assert result == {
            "success": True,
            "review_id": "review-1",
            "message": "Reply posted successfully",
            "error": None,
        }
        called_args = mock_run.call_args.args[0]
        assert called_args[0] == "asc"
        assert "respond" in called_args
        assert "--review-id" in called_args and "review-1" in called_args
        assert "--response" in called_args and "Thanks!" in called_args

    @patch("app_store_mcp.client.subprocess.run")
    def test_reply_to_review_failure_does_not_fake_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(returncode=1, stderr="Error: review not found")
        client = AppStoreClient()

        result = client.reply_to_review(review_id="bad-id", reply_text="Thanks!")

        assert result["success"] is False
        assert "review not found" in result["error"]


class TestAppStoreServerTools:
    def test_get_app_details(self, mock_client: MagicMock) -> None:
        mock_client.get_app_details.return_value = {
            "title": "Test App",
            "short_description": "Sub",
            "full_description": "Long desc",
        }
        res = get_app_details(bundle_id="com.example.app", language="en-US")
        mock_client.get_app_details.assert_called_once_with(
            bundle_id="com.example.app", language="en-US"
        )
        assert res["title"] == "Test App"

    def test_get_reviews(self, mock_client: MagicMock) -> None:
        mock_client.get_reviews.return_value = [{"review_id": "r1", "comment": "Good"}]
        res = get_reviews(bundle_id="com.example.app", max_results=10)
        mock_client.get_reviews.assert_called_once_with(
            bundle_id="com.example.app", max_results=10, profile=None
        )
        assert len(res) == 1
        assert res[0]["review_id"] == "r1"

    def test_reply_to_review(self, mock_client: MagicMock) -> None:
        mock_client.reply_to_review.return_value = {
            "success": True,
            "review_id": "r1",
            "message": "Reply posted successfully",
            "error": None,
        }
        res = reply_to_review(review_id="r1", reply_text="Thanks!")
        mock_client.reply_to_review.assert_called_once_with(
            review_id="r1", reply_text="Thanks!", profile=None
        )
        assert res["success"] is True

    def test_get_keyword_rank(self, mock_client: MagicMock) -> None:
        mock_client.get_keyword_rank.return_value = {
            "keyword": "pomodoro",
            "rank": None,
            "total_results": 196,
            "country": "us",
        }
        res = get_keyword_rank(bundle_id="com.example.app", keyword="pomodoro")
        mock_client.get_keyword_rank.assert_called_once_with(
            bundle_id="com.example.app", keyword="pomodoro", country="us", limit=200
        )
        assert res["rank"] is None

    def test_update_listing(self, mock_client: MagicMock) -> None:
        mock_client.update_listing.return_value = {"status": "success"}
        res = update_listing(bundle_id="com.example.app", title="New Title")
        mock_client.update_listing.assert_called_once_with(
            bundle_id="com.example.app",
            title="New Title",
            short_description=None,
            full_description=None,
            locale="en-US",
            profile=None,
        )
        assert res["status"] == "success"
