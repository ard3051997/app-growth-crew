"""Tests for package name translation and dynamic GA4 user journeys fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api_server.main import app
from api_server.routes.apps import get_db_package, get_url_package

client = TestClient(app)


class TestPackageTranslation:
    def test_get_db_package_converts_id_suffix(self) -> None:
        assert (
            get_db_package("huge-digital-clock-id1515003825") == "huge-digital-clock/id1515003825"
        )
        assert get_db_package("com.finance.loan.emicalculator") == "com.finance.loan.emicalculator"

    def test_get_url_package_converts_id_slash(self) -> None:
        assert (
            get_url_package("huge-digital-clock/id1515003825") == "huge-digital-clock-id1515003825"
        )
        assert get_url_package("com.finance.loan.emicalculator") == "com.finance.loan.emicalculator"


class TestJourneyFallback:
    @patch("api_server.routes.apps.Path.exists", return_value=False)
    @patch("app_manager.credential_store.get_app_credentials")
    @patch("api_server.routes.apps.AnalyticsClient")
    def test_journeys_fallback_triggers_when_no_events_file(
        self, MockAnalytics: MagicMock, mock_get_creds: MagicMock, _mock_exists: MagicMock
    ) -> None:
        # Mock credentials
        mock_creds = MagicMock()
        mock_creds.ga4_property_id = "151002871"
        mock_creds.google_credentials_path = "/path/to/fake.json"
        mock_creds.has_analytics.return_value = True
        mock_get_creds.return_value = mock_creds

        # Mock analytics client to return a valid report
        mock_client = MagicMock()
        mock_report = MagicMock()

        # Simulating GA4 get_events report response mapping to .events list
        mock_event = MagicMock()
        mock_event.get.side_effect = lambda k, d=None: {
            "event_name": "first_open",
            "event_count": 100,
            "total_users": 50,
        }.get(k, d)

        mock_report.events = [mock_event]
        mock_client.get_events.return_value = mock_report
        MockAnalytics.return_value = mock_client

        response = client.get("/api/apps/huge-digital-clock-id1515003825/journeys")
        assert response.status_code == 200

        data = response.json()
        assert "journeys" in data
        assert "1" in data["journeys"]

        journey = data["journeys"]["1"]
        assert journey["title"] == "Live GA4 Auto-Discovered Flow"
        assert len(journey["sections"]) == 1
        assert len(journey["sections"][0]["rows"]) == 1
        assert journey["sections"][0]["rows"][0]["Event"] == "first_open"

    @patch("api_server.routes.apps.Path.exists", return_value=False)
    @patch("app_manager.credential_store.get_app_credentials")
    @patch("api_server.routes.apps.AnalyticsClient", side_effect=Exception("API failure"))
    def test_journeys_reports_unavailable_on_client_error(
        self, _MockAnalytics: MagicMock, mock_get_creds: MagicMock, _mock_exists: MagicMock
    ) -> None:
        # Mock credentials to bypass has_analytics check and enter try block
        mock_creds = MagicMock()
        mock_creds.ga4_property_id = "151002871"
        mock_creds.google_credentials_path = "/path/to/fake.json"
        mock_creds.has_analytics.return_value = True
        mock_get_creds.return_value = mock_creds

        response = client.get("/api/apps/huge-digital-clock-id1515003825/journeys")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "unavailable"
        assert data["journey_count"] == 0
        assert data["journeys"] == {}
        assert data["unavailable_sources"] == ["events_md", "analytics"]
