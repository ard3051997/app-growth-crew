"""Tests for analytics_mcp/client.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from analytics_mcp.client import AnalyticsClient, AnalyticsClientError


def _header(field_name: str) -> MagicMock:
    h = MagicMock()
    h.name = field_name
    return h


def _make_mock_response(
    dim_names: list[str],
    met_names: list[str],
    rows: list[tuple[list[str], list[str]]],
    row_count: int | None = None,
) -> MagicMock:
    """Build a fake GA4 RunReportResponse."""
    resp = MagicMock()
    resp.dimension_headers = [_header(n) for n in dim_names]
    resp.metric_headers = [_header(n) for n in met_names]
    resp.row_count = row_count if row_count is not None else len(rows)

    mock_rows = []
    for dims, mets in rows:
        row = MagicMock()
        row.dimension_values = [MagicMock(value=v) for v in dims]
        row.metric_values = [MagicMock(value=v) for v in mets]
        mock_rows.append(row)
    resp.rows = mock_rows
    return resp


class TestAnalyticsClientInit:
    def test_raises_without_property_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GA4_PROPERTY_ID", raising=False)
        with pytest.raises(AnalyticsClientError, match="GA4_PROPERTY_ID"):
            AnalyticsClient()

    def test_uses_env_property_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GA4_PROPERTY_ID", "123456")
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        client = AnalyticsClient()
        assert client._property_id == "123456"

    def test_explicit_property_id(self) -> None:
        client = AnalyticsClient(property_id="999")
        assert client._property_id == "999"

    def test_property_path(self) -> None:
        client = AnalyticsClient(property_id="42")
        assert client._property_path == "properties/42"


class TestAnalyticsClientGetClient:
    def test_initialises_with_credentials_path(self, tmp_path: Any) -> None:
        creds_file = tmp_path / "creds.json"
        creds_file.write_text("{}")

        mock_creds = MagicMock()
        mock_ga4 = MagicMock()

        with (
            patch(
                "analytics_mcp.client.service_account.Credentials.from_service_account_file",
                return_value=mock_creds,
            ),
            patch("analytics_mcp.client.BetaAnalyticsDataClient", return_value=mock_ga4) as MockGA4,
        ):
            client = AnalyticsClient(property_id="1", credentials_path=str(creds_file))
            ga4 = client._get_client()
            MockGA4.assert_called_once_with(credentials=mock_creds)
            assert ga4 is mock_ga4

    def test_caches_client_on_second_call(self) -> None:
        mock_ga4 = MagicMock()
        client = AnalyticsClient(property_id="1")
        client._client = mock_ga4
        assert client._get_client() is mock_ga4

    def test_initialises_with_credentials_json_string(self) -> None:
        creds_json = '{"type": "service_account"}'
        mock_creds = MagicMock()
        mock_ga4 = MagicMock()

        with (
            patch(
                "analytics_mcp.client.service_account.Credentials.from_service_account_info",
                return_value=mock_creds,
            ),
            patch("analytics_mcp.client.BetaAnalyticsDataClient", return_value=mock_ga4),
        ):
            client = AnalyticsClient(property_id="1", credentials_json=creds_json)
            client._get_client()
            assert client._client is mock_ga4

    def test_initialises_with_credentials_json_dict(self) -> None:
        creds_dict = {"type": "service_account"}
        mock_creds = MagicMock()

        with (
            patch(
                "analytics_mcp.client.service_account.Credentials.from_service_account_info",
                return_value=mock_creds,
            ),
            patch("analytics_mcp.client.BetaAnalyticsDataClient") as MockGA4,
        ):
            client = AnalyticsClient(property_id="1", credentials_json=creds_dict)
            client._get_client()
            MockGA4.assert_called_once_with(credentials=mock_creds)

    def test_falls_back_to_adc_when_no_creds(self) -> None:
        with patch("analytics_mcp.client.BetaAnalyticsDataClient") as MockGA4:
            client = AnalyticsClient(property_id="1")
            client._get_client()
            MockGA4.assert_called_once_with()


class TestAnalyticsClientRunReport:
    @pytest.fixture
    def client(self) -> AnalyticsClient:
        c = AnalyticsClient(property_id="123")
        c._client = MagicMock()
        return c

    def test_run_report_returns_analytics_report(self, client: AnalyticsClient) -> None:
        response = _make_mock_response(
            ["date"], ["activeUsers"], [(["2024-01-01"], ["500"])], row_count=1
        )
        client._client.run_report.return_value = response  # type: ignore[union-attr]

        report = client.run_report(dimensions=["date"], metrics=["activeUsers"])

        assert report.property_id == "123"
        assert report.row_count == 1
        assert len(report.rows) == 1
        assert report.rows[0].dimensions[0].name == "date"
        assert report.rows[0].dimensions[0].value == "2024-01-01"
        assert report.rows[0].metrics[0].name == "activeUsers"
        assert report.rows[0].metrics[0].value == "500"

    def test_run_report_empty_rows(self, client: AnalyticsClient) -> None:
        response = _make_mock_response(["date"], ["sessions"], [], row_count=0)
        client._client.run_report.return_value = response  # type: ignore[union-attr]

        report = client.run_report(dimensions=["date"], metrics=["sessions"])
        assert report.row_count == 0
        assert report.rows == []

    def test_run_report_passes_limit(self, client: AnalyticsClient) -> None:
        from google.analytics.data_v1beta.types import RunReportRequest

        response = _make_mock_response(["date"], ["activeUsers"], [], row_count=0)
        client._client.run_report.return_value = response  # type: ignore[union-attr]

        client.run_report(dimensions=["date"], metrics=["activeUsers"], limit=25)

        call_args = client._client.run_report.call_args  # type: ignore[union-attr]
        req: RunReportRequest = call_args[0][0]
        assert req.limit == 25


class TestAnalyticsClientRealtimeReport:
    @pytest.fixture
    def client(self) -> AnalyticsClient:
        c = AnalyticsClient(property_id="123")
        c._client = MagicMock()
        return c

    def test_realtime_report_defaults(self, client: AnalyticsClient) -> None:
        response = _make_mock_response(
            ["unifiedScreenName"], ["activeUsers"], [(["/home"], ["42"])]
        )
        response.row_count = 1
        client._client.run_realtime_report.return_value = response  # type: ignore[union-attr]

        report = client.get_realtime_report()
        assert report.active_users == 42

    def test_realtime_report_zero_users(self, client: AnalyticsClient) -> None:
        response = _make_mock_response(["unifiedScreenName"], ["activeUsers"], [])
        response.row_count = 0
        client._client.run_realtime_report.return_value = response  # type: ignore[union-attr]

        report = client.get_realtime_report()
        assert report.active_users == 0


class TestAnalyticsClientRetry:
    def test_retries_on_rate_limit(self) -> None:
        from google.api_core import exceptions as google_exceptions

        client = AnalyticsClient(property_id="1")
        mock_ga4 = MagicMock()
        client._client = mock_ga4

        response = _make_mock_response(["date"], ["activeUsers"], [], row_count=0)
        mock_ga4.run_report.side_effect = [
            google_exceptions.TooManyRequests("rate limited"),
            response,
        ]

        with patch("mcp_gc_shared.retry.time.sleep"):
            report = client.run_report(dimensions=["date"], metrics=["activeUsers"])

        assert mock_ga4.run_report.call_count == 2
        assert report.row_count == 0

    def test_raises_after_max_retries(self) -> None:
        from google.api_core import exceptions as google_exceptions

        client = AnalyticsClient(property_id="1")
        mock_ga4 = MagicMock()
        client._client = mock_ga4
        mock_ga4.run_report.side_effect = google_exceptions.ServiceUnavailable("down")

        with (
            patch("mcp_gc_shared.retry.time.sleep"),
            pytest.raises(google_exceptions.ServiceUnavailable),
        ):
            client.run_report(dimensions=["date"], metrics=["activeUsers"])

        assert mock_ga4.run_report.call_count == 3  # MAX_RETRIES

    def test_does_not_retry_on_non_transient_error(self) -> None:
        from google.api_core import exceptions as google_exceptions

        client = AnalyticsClient(property_id="1")
        mock_ga4 = MagicMock()
        client._client = mock_ga4
        mock_ga4.run_report.side_effect = google_exceptions.NotFound("not found")

        with pytest.raises(google_exceptions.NotFound):
            client.run_report(dimensions=["date"], metrics=["activeUsers"])

        assert mock_ga4.run_report.call_count == 1
