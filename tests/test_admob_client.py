"""Tests for admob_mcp/client.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from admob_mcp.client import AdMobClient, AdMobClientError


def _make_service(accounts: list[dict] | None = None) -> MagicMock:
    """Return a fake googleapiclient service object."""
    svc = MagicMock()
    acct_list = svc.accounts.return_value.list.return_value
    acct_list.execute.return_value = {"account": accounts or []}
    return svc


class TestAdMobClientInit:
    def test_reads_account_id_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ADMOB_ACCOUNT_ID", "pub-1234")
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        client = AdMobClient()
        assert client._account_id == "pub-1234"

    def test_explicit_account_id(self) -> None:
        client = AdMobClient(account_id="pub-9999")
        assert client._account_id == "pub-9999"

    def test_account_path_requires_account_id(self) -> None:
        client = AdMobClient(account_id=None)
        with pytest.raises(AdMobClientError, match="ADMOB_ACCOUNT_ID"):
            _ = client._account_path

    def test_account_path_format(self) -> None:
        client = AdMobClient(account_id="pub-1234")
        assert client._account_path == "accounts/pub-1234"


class TestAdMobClientGetService:
    def test_raises_when_no_credentials(self, tmp_path: Any) -> None:
        # Pass an explicit non-existent token path so __init__ doesn't auto-detect
        # any real token.json sitting in the project root.
        client = AdMobClient(
            account_id="pub-1",
            token_path=str(tmp_path / "no-token.json"),
        )
        with pytest.raises(AdMobClientError, match="No valid credentials"):
            client._get_service()

    def test_initialises_from_service_account_path(self, tmp_path: Any) -> None:
        creds_file = tmp_path / "sa.json"
        creds_file.write_text("{}")
        no_token = str(tmp_path / "no-token.json")  # non-existent, prevents cwd auto-detect

        mock_creds = MagicMock()
        mock_service = MagicMock()

        with (
            patch(
                "admob_mcp.client.service_account.Credentials.from_service_account_file",
                return_value=mock_creds,
            ),
            patch("admob_mcp.client.build", return_value=mock_service) as mock_build,
        ):
            client = AdMobClient(
                account_id="pub-1", credentials_path=str(creds_file), token_path=no_token
            )
            svc = client._get_service()

        mock_build.assert_called_once_with(
            "admob", "v1", credentials=mock_creds, cache_discovery=False
        )
        assert svc is mock_service

    def test_initialises_from_credentials_json_dict(self, tmp_path: Any) -> None:
        creds_dict = {"type": "service_account"}
        mock_creds = MagicMock()
        mock_service = MagicMock()
        no_token = str(tmp_path / "no-token.json")

        with (
            patch(
                "admob_mcp.client.service_account.Credentials.from_service_account_info",
                return_value=mock_creds,
            ),
            patch("admob_mcp.client.build", return_value=mock_service),
        ):
            client = AdMobClient(
                account_id="pub-1", credentials_json=creds_dict, token_path=no_token
            )
            svc = client._get_service()

        assert svc is mock_service

    def test_caches_service_on_second_call(self) -> None:
        mock_service = MagicMock()
        client = AdMobClient(account_id="pub-1")
        client._service = mock_service
        assert client._get_service() is mock_service

    def test_loads_oauth_token_from_file(self, tmp_path: Any) -> None:
        token_file = tmp_path / "token.json"
        token_file.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_service = MagicMock()

        with (
            patch(
                "admob_mcp.client.Credentials.from_authorized_user_file", return_value=mock_creds
            ),
            patch("admob_mcp.client.build", return_value=mock_service),
        ):
            client = AdMobClient(account_id="pub-1", token_path=str(token_file))
            svc = client._get_service()

        assert svc is mock_service


class TestAdMobClientListAccounts:
    def test_list_accounts_returns_accounts(self) -> None:
        mock_service = _make_service(
            accounts=[{"publisherId": "pub-1234", "name": "accounts/pub-1234"}]
        )
        client = AdMobClient(account_id="pub-1234")
        client._service = mock_service

        accounts = client.list_accounts()

        assert len(accounts) == 1
        assert accounts[0].publisher_id == "pub-1234"

    def test_list_accounts_empty(self) -> None:
        mock_service = _make_service(accounts=[])
        client = AdMobClient(account_id="pub-1234")
        client._service = mock_service

        accounts = client.list_accounts()
        assert accounts == []


class TestAdMobClientRetry:
    def test_retries_on_http_error(self) -> None:
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 429

        mock_service = MagicMock()
        mock_service.accounts.return_value.list.return_value.execute.side_effect = [
            HttpError(mock_resp, b"rate limited"),
            {"account": []},
        ]

        client = AdMobClient(account_id="pub-1")
        client._service = mock_service

        with patch("admob_mcp.client.time.sleep"):
            accounts = client.list_accounts()

        assert mock_service.accounts.return_value.list.return_value.execute.call_count == 2
        assert accounts == []

    def test_raises_on_non_transient_http_error(self) -> None:
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 403

        mock_service = MagicMock()
        mock_service.accounts.return_value.list.return_value.execute.side_effect = HttpError(
            mock_resp, b"forbidden"
        )

        client = AdMobClient(account_id="pub-1")
        client._service = mock_service

        with pytest.raises(HttpError):
            client.list_accounts()

        assert mock_service.accounts.return_value.list.return_value.execute.call_count == 1

    def test_raises_after_max_retries(self) -> None:
        from googleapiclient.errors import HttpError

        mock_resp = MagicMock()
        mock_resp.status = 503

        mock_service = MagicMock()
        mock_service.accounts.return_value.list.return_value.execute.side_effect = HttpError(
            mock_resp, b"unavailable"
        )

        client = AdMobClient(account_id="pub-1")
        client._service = mock_service

        with (
            patch("admob_mcp.client.time.sleep"),
            pytest.raises(HttpError),
        ):
            client.list_accounts()

        assert mock_service.accounts.return_value.list.return_value.execute.call_count == 3
