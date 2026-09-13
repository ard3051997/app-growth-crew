"""Tests for App Store Connect analytics ingestion (asc_analytics_ingest.py).

No real network or subprocess calls -- subprocess.run is mocked exactly like
tests/test_app_store_mcp.py's TestAscBackedUpdateListing does.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app_manager.asc_analytics_ingest import (
    INSTALLS_REPORT_NAME,
    PAGE_VIEWS_REPORT_NAME,
    AscAnalyticsIngestError,
    _download_segment,
    _list_instances,
    _list_segments,
    download_instance_csv,
    ensure_ongoing_request,
    ingest_asc_reports,
    parse_metric_rows,
)
from funnel_engine.db import get_total_impressions, get_total_storefront_metrics, init_db


def _completed_process(
    *, stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["asc"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestEnsureOngoingRequest:
    @patch("app_manager.asc_analytics_ingest.subprocess.run")
    def test_reuses_an_existing_ongoing_request(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(
            stdout=json.dumps({"data": [{"id": "req-1", "attributes": {"accessType": "ONGOING"}}]})
        )
        request_id = ensure_ongoing_request("123456789")
        assert request_id == "req-1"
        mock_run.assert_called_once()

    @patch("app_manager.asc_analytics_ingest.subprocess.run")
    def test_creates_one_when_none_exists(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed_process(stdout=json.dumps({"data": []})),
            _completed_process(
                stdout=json.dumps(
                    {"requestId": "new-req", "appId": "123456789", "accessType": "ONGOING"}
                )
            ),
        ]
        request_id = ensure_ongoing_request("123456789")
        assert request_id == "new-req"
        assert mock_run.call_count == 2
        create_args = mock_run.call_args_list[1].args[0]
        assert "--access-type" in create_args and "ONGOING" in create_args

    @patch("app_manager.asc_analytics_ingest.subprocess.run")
    def test_raises_on_asc_failure_instead_of_faking_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(returncode=1, stderr="Error: unauthorized")
        with pytest.raises(AscAnalyticsIngestError, match="unauthorized"):
            ensure_ongoing_request("123456789")


class TestListInstances:
    @patch("app_manager.asc_analytics_ingest.subprocess.run")
    def test_follows_pagination_via_next_link(self, mock_run: MagicMock) -> None:
        related_url = (
            "https://api.appstoreconnect.apple.com/v1/analyticsReports/r14-req-1/instances"
        )
        next_url = related_url + "?cursor=2"
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {"data": {"relationships": {"instances": {"links": {"related": related_url}}}}}
                )
            ),
            _completed_process(
                stdout=json.dumps({"data": [{"id": "inst-1"}], "links": {"next": next_url}})
            ),
            _completed_process(stdout=json.dumps({"data": [{"id": "inst-2"}], "links": {}})),
        ]
        instances = _list_instances("r14-req-1")
        assert [inst["id"] for inst in instances] == ["inst-1", "inst-2"]
        # The pagination workaround: reports links is called with --next, never --report-id,
        # sidestepping the real asc 0.47.0 bug that rejects composite report IDs there.
        for call in mock_run.call_args_list[1:]:
            assert "--report-id" not in call.args[0]


class TestListSegmentsAndDownload:
    @patch("app_manager.asc_analytics_ingest.subprocess.run")
    def test_no_segments_means_a_single_file(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(stdout=json.dumps({"data": []}))
        assert _list_segments("inst-1") == []

    @patch("app_manager.asc_analytics_ingest.subprocess.run")
    def test_multiple_segments_are_listed(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed_process(
            stdout=json.dumps({"data": [{"id": "seg-1"}, {"id": "seg-2"}]})
        )
        assert _list_segments("inst-1") == ["seg-1", "seg-2"]

    def test_download_segment_reads_and_cleans_up_the_output_file(self, tmp_path) -> None:
        csv_text = "Date,Territory,Counts\n2026-08-01,US,42\n"

        def _fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            output_path = command[command.index("--output") + 1]
            with Path(output_path).open("w", encoding="utf-8") as fh:
                fh.write(csv_text)
            return _completed_process(stdout=json.dumps({"requestId": "req-1"}))

        with patch("app_manager.asc_analytics_ingest.subprocess.run", side_effect=_fake_run):
            content = _download_segment("req-1", "inst-1", tmp_dir=tmp_path)

        assert content == csv_text
        assert list(tmp_path.iterdir()) == []

    def test_download_instance_csv_downloads_every_segment(self, tmp_path) -> None:
        with (
            patch(
                "app_manager.asc_analytics_ingest._list_segments", return_value=["seg-1", "seg-2"]
            ),
            patch(
                "app_manager.asc_analytics_ingest._download_segment",
                side_effect=lambda *_a, segment_id=None, **_k: f"csv-for-{segment_id}",
            ) as mock_download,
        ):
            texts = download_instance_csv("req-1", "inst-1", tmp_dir=tmp_path)
        assert texts == ["csv-for-seg-1", "csv-for-seg-2"]
        assert mock_download.call_count == 2


class TestParseMetricRows:
    def test_wide_format_page_views(self) -> None:
        rows = [
            ["Date", "Territory", "Product Page Views Unique Devices"],
            ["2026-08-01", "US", "1,200"],
            ["2026-08-01", "IN", "300"],
            ["2026-08-02", "US", "50"],
        ]
        totals = parse_metric_rows(rows, metric_markers=("page", "view"))
        assert totals == {
            ("2026-08-01", "US"): 1200,
            ("2026-08-01", "IN"): 300,
            ("2026-08-02", "US"): 50,
        }

    def test_wide_format_downloads_excludes_deletions_column(self) -> None:
        rows = [
            ["Date", "Territory", "Total Downloads", "Total Deletions"],
            ["2026-08-01", "US", "40", "5"],
        ]
        totals = parse_metric_rows(rows, metric_markers=("download",))
        assert totals == {("2026-08-01", "US"): 40}

    def test_tidy_long_format_filters_by_event_and_excludes_markers(self) -> None:
        rows = [
            ["Date", "Territory", "Event", "Counts"],
            ["2026-08-01", "US", "Impression", "500"],
            ["2026-08-01", "US", "Page View", "120"],
            ["2026-08-01", "US", "First-Time Download", "30"],
            ["2026-08-01", "US", "Deletion", "9"],
        ]
        assert parse_metric_rows(rows, metric_markers=("impression",)) == {
            ("2026-08-01", "US"): 500
        }
        assert parse_metric_rows(rows, metric_markers=("download",), exclude=("delet",)) == {
            ("2026-08-01", "US"): 30
        }

    def test_unrecognized_shape_returns_empty_without_raising(self) -> None:
        rows = [["Date", "Territory", "Something Else"], ["2026-08-01", "US", "1"]]
        assert parse_metric_rows(rows, metric_markers=("impression",)) == {}

    def test_empty_rows_return_empty(self) -> None:
        assert parse_metric_rows([], metric_markers=("impression",)) == {}


class TestIngestAscReportsEndToEnd:
    def test_populates_country_and_impressions_tables(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "store_performance.db"
        init_db(db_path)

        monkeypatch.setattr(
            "app_manager.asc_analytics_ingest._asc_target",
            lambda _package_name: ("123456789", "TestProfile"),
        )
        monkeypatch.setattr(
            "app_manager.asc_analytics_ingest.ensure_ongoing_request",
            lambda _app_id, **_kwargs: "req-1",
        )

        def _find_report(_request_id, report_name, **_kwargs):
            if report_name == PAGE_VIEWS_REPORT_NAME:
                return "r14-req-1"
            if report_name == INSTALLS_REPORT_NAME:
                return "r6-req-1"
            return None

        monkeypatch.setattr("app_manager.asc_analytics_ingest._find_report", _find_report)
        monkeypatch.setattr(
            "app_manager.asc_analytics_ingest._list_instances",
            lambda _report_id, **_kwargs: [{"id": "inst-1"}],
        )

        page_view_csv = (
            "Date,Territory,Event,Counts\n"
            "2026-08-01,US,Impression,1000\n"
            "2026-08-01,US,Page View,200\n"
        )
        installs_csv = "Date,Territory,Event,Counts\n2026-08-01,US,First-Time Download,50\n"

        def _download(_request_id, _instance_id, **_kwargs):
            # Page views are ingested before installs, so the first call is
            # always for the page-view report and the second for installs.
            _download.calls += 1
            return [page_view_csv] if _download.calls == 1 else [installs_csv]

        _download.calls = 0
        monkeypatch.setattr("app_manager.asc_analytics_ingest.download_instance_csv", _download)

        result = ingest_asc_reports("com.example.iosapp", db_path=db_path)

        assert result["success"] is True
        assert result["status"] == "success"
        assert result["records_inserted"] > 0

        metrics = get_total_storefront_metrics(db_path, "com.example.iosapp", days=30)
        assert metrics == {"visitors": 200, "installs": 50}
        assert get_total_impressions(db_path, "com.example.iosapp", days=30) == 1000

    def test_no_instances_yet_is_reported_honestly_not_as_success(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "store_performance.db"
        init_db(db_path)

        monkeypatch.setattr(
            "app_manager.asc_analytics_ingest._asc_target",
            lambda _package_name: ("123456789", None),
        )
        monkeypatch.setattr(
            "app_manager.asc_analytics_ingest.ensure_ongoing_request",
            lambda _app_id, **_kwargs: "req-1",
        )
        monkeypatch.setattr(
            "app_manager.asc_analytics_ingest._find_report",
            lambda _request_id, _report_name, **_kwargs: "r14-req-1",
        )
        monkeypatch.setattr(
            "app_manager.asc_analytics_ingest._list_instances",
            lambda _report_id, **_kwargs: [],
        )

        result = ingest_asc_reports("com.example.iosapp", db_path=db_path)

        assert result["status"] == "partial"
        assert result["records_inserted"] == 0
        assert get_total_storefront_metrics(db_path, "com.example.iosapp", days=30) is None
