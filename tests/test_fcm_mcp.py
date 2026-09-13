"""Tests for fcm_push_mcp server and client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from fcm_push_mcp.client import FCMClient
from fcm_push_mcp.server import (
    mcp,
    send_push_notification,
    send_push_to_condition,
    send_push_to_token,
)


def _mock_context(client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock(spec=FCMClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


class TestFCMClient:
    def test_client_init_mock_mode_no_creds(self) -> None:
        client = FCMClient(credentials_path="/nonexistent/file.json")
        assert client._is_mock is True

    def test_client_init_parses_project_id(self, tmp_path: Any) -> None:
        creds_file = tmp_path / "creds.json"
        creds_file.write_text('{"project_id": "test-project-123"}')
        client = FCMClient(credentials_path=str(creds_file))
        assert client._project_id == "test-project-123"
        assert client._is_mock is False


class TestFCMServerTools:
    def test_send_push_notification(self, mock_client: MagicMock) -> None:
        mock_client.send_push_notification.return_value = {"status": "success", "message_id": "1"}
        res = send_push_notification(topic="all", title="Hello", body="World", data={"key": "val"})
        mock_client.send_push_notification.assert_called_once_with(
            topic="all", title="Hello", body="World", data={"key": "val"}
        )
        assert res["status"] == "success"

    def test_send_push_to_token(self, mock_client: MagicMock) -> None:
        mock_client.send_push_to_token.return_value = {"status": "success", "message_id": "2"}
        res = send_push_to_token(token="tok123", title="Hi", body="There")
        mock_client.send_push_to_token.assert_called_once_with(
            token="tok123", title="Hi", body="There", data=None
        )
        assert res["status"] == "success"

    def test_send_push_to_condition(self, mock_client: MagicMock) -> None:
        mock_client.send_push_to_condition.return_value = {"status": "success"}
        res = send_push_to_condition(condition="cond", title="A", body="B")
        mock_client.send_push_to_condition.assert_called_once_with(
            condition="cond", title="A", body="B", data=None
        )
        assert res["status"] == "success"
