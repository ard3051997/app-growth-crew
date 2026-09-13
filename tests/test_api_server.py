from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api_server.main import app
from app_manager.credential_store import AppCredentials

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_portfolio_endpoints():
    # Test /api/portfolio
    response = client.get("/api/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "apps" in data
    assert len(data["apps"]) >= 2
    packages = [a["package_name"] for a in data["apps"]]
    assert "com.finance.loan.emicalculator" in packages
    assert "com.cama.app.huge80sclockPro" in packages

    # Test /api/portfolio/summary
    response = client.get("/api/portfolio/summary")
    assert response.status_code == 200
    summary = response.json()
    assert "portfolio_summary" in summary
    assert summary["portfolio_summary"]["trust_tier"] in ("conservative", "moderate", "aggressive")


@patch("api_server.routes.apps.get_latest_app_snapshot")
@patch("api_server.routes.apps.run_funnel_analysis")
def test_app_funnel(mock_run_funnel, mock_get_snapshot):
    mock_get_snapshot.return_value = None
    mock_run_funnel.return_value = '{"funnel_health_score": 88, "all_steps": []}'

    response = client.get("/api/apps/com.finance.loan.emicalculator/funnel")
    assert response.status_code == 200
    data = response.json()
    assert data["funnel_health_score"] == 88
    mock_run_funnel.assert_called_once_with(
        package_name="com.finance.loan.emicalculator", app_category="finance", date_range="30d"
    )


@patch("api_server.routes.apps.PlayStoreClient")
def test_app_listing(mock_play_store_class):
    mock_client = MagicMock()
    mock_play_store_class.return_value = mock_client

    mock_details = MagicMock()
    mock_details.title = "EMI Calculator - Easy Loan"
    mock_details.short_description = "Easy loan calculator"
    mock_details.full_description = "A long loan calculator description"
    mock_details.default_language = "en-US"
    mock_client.get_app_details.return_value = mock_details

    response = client.get("/api/apps/com.finance.loan.emicalculator/listing/en-US")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "EMI Calculator - Easy Loan"
    assert data["short_description"] == "Easy loan calculator"
    mock_client.get_app_details.assert_called_once_with(
        package_name="com.finance.loan.emicalculator", language="en-US"
    )


@patch("api_server.routes.apps.get_country_performance")
@patch("api_server.routes.apps.get_traffic_performance")
@patch("api_server.routes.apps.get_search_performance")
@patch("api_server.routes.apps.get_source_watermarks")
def test_app_storefront(mock_watermarks, mock_search, mock_traffic, mock_country):
    mock_country.return_value = [
        {"date": "2026-06-01", "country": "US", "visitors": 20},
        {"date": "2026-06-30", "country": "IN", "visitors": 100},
    ]
    mock_traffic.return_value = [{"date": "2026-06-24", "traffic_source": "Search", "visitors": 80}]
    mock_search.return_value = [
        {"date": "2026-06-23", "search_term": "old", "visitors": 10},
        {"date": "2026-06-30", "search_term": "loan", "visitors": 50},
    ]
    mock_watermarks.return_value = [
        {
            "source": "storefront",
            "last_status": "success",
            "last_completed_at": "2026-07-01T00:00:00+00:00",
            "record_count": 4,
        }
    ]

    response = client.get("/api/apps/com.finance.loan.emicalculator/storefront?period=7d")
    assert response.status_code == 200
    data = response.json()
    assert "country" in data
    assert "traffic_source" in data
    assert "search_term" in data
    assert data["country"][0]["country"] == "IN"
    assert [row["date"] for row in data["traffic_source"]] == ["2026-06-24"]
    assert [row["date"] for row in data["search_term"]] == ["2026-06-30"]
    assert data["as_of"] == "2026-06-30"
    assert data["provenance"]["period"] == "7d"
    assert data["provenance"]["period_start"] == "2026-06-24"
    assert data["provenance"]["period_end"] == "2026-06-30"

    unsupported = client.get("/api/apps/com.finance.loan.emicalculator/storefront?period=14d")
    assert unsupported.status_code == 422


@patch("api_server.routes.apps.parse_events_md")
def test_app_journeys(mock_parse):
    mock_parse.return_value = {"journey_count": 1, "journeys": {}}
    response = client.get("/api/apps/com.finance.loan.emicalculator/journeys")
    assert response.status_code == 200
    assert response.json()["journey_count"] == 1


def test_system_status():
    response = client.get("/api/system/status")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_system_safety():
    response = client.get("/api/system/safety")
    assert response.status_code == 200
    assert "crash_rate" in response.json()


def test_experiments_list():
    response = client.get("/api/experiments/")
    assert response.status_code == 200
    assert "experiments" in response.json()


def test_actions_list():
    response = client.get("/api/actions/")
    assert response.status_code == 200
    assert "actions" in response.json()


@patch("api_server.routes.webhooks.FCMClient")
def test_revenuecat_webhook_ignored(mock_fcm_client_cls, monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_GC_INSECURE_DEV_WEBHOOKS", "1")
    monkeypatch.setattr("api_server.routes.webhooks.DEFAULT_DB_PATH", tmp_path / "ignored.db")
    payload = {
        "event": {
            "id": "ignored-event",
            "type": "INITIAL_PURCHASE",
            "app_id": "com.finance.loan.emicalculator",
            "app_user_id": "rc_user_1234",
            "product_id": "google_premium_ds70_lifetime",
        }
    }
    response = client.post("/api/webhooks/revenuecat", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    mock_fcm_client_cls.assert_not_called()


@patch("api_server.routes.webhooks.log_db_action")
@patch("api_server.routes.webhooks.FCMClient")
def test_revenuecat_webhook_processed(
    mock_fcm_client_cls, mock_log_db_action, monkeypatch, tmp_path
):
    monkeypatch.setenv("MCP_GC_INSECURE_DEV_WEBHOOKS", "1")
    monkeypatch.setattr("api_server.routes.webhooks.DEFAULT_DB_PATH", tmp_path / "processed.db")
    monkeypatch.setattr(
        "api_server.routes.webhooks.get_app_credentials",
        lambda package: AppCredentials(
            package_name=package,
            revenuecat_api_key="test-revenuecat-key",
            revenuecat_project_id="test-project",
            ga4_property_id="test-property",
            google_credentials_path="/test/service-account.json",
        ),
    )
    mock_client_instance = MagicMock()
    mock_client_instance.send_push_to_token.return_value = {
        "status": "success",
        "mode": "mocked",
        "message_id": "mock-msg-1",
    }
    mock_fcm_client_cls.return_value = mock_client_instance

    payload = {
        "event": {
            "id": "processed-event",
            "type": "CANCELLATION",
            "app_id": "com.finance.loan.emicalculator",
            "app_user_id": "rc_user_1234",
            "product_id": "google_premium_ds70_lifetime",
        }
    }

    response = client.post("/api/webhooks/revenuecat", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"

    # Verify that app-specific credentials were resolved and passed to the FCM client
    mock_fcm_client_cls.assert_called_once_with(credentials_path="/test/service-account.json")

    mock_client_instance.send_push_to_token.assert_called_once()
    call_args = mock_client_instance.send_push_to_token.call_args[0]
    assert call_args[0] == "rc_user_1234"  # token
    assert isinstance(call_args[1], str) and call_args[1]  # title
    assert isinstance(call_args[2], str) and call_args[2]  # body

    # Verify that the action was logged in the DB
    mock_log_db_action.assert_called_once()
    log_args = mock_log_db_action.call_args[1]
    assert log_args["action_type"] == "push_reengagement"
    assert log_args["app_package"] == "com.finance.loan.emicalculator"
    assert log_args["result"] == "success"
    assert "triggered FCM push" in log_args["reasoning"]


def test_app_keywords_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_GC_CONFIG_WRITES_ENABLED", "1")
    # Mock PROJECT_ROOT / rulebooks so we don't mess up real config files
    with patch("api_server.routes.apps.PROJECT_ROOT", tmp_path):
        rulebooks_dir = tmp_path / "rulebooks"
        rulebooks_dir.mkdir(exist_ok=True)

        # Test PUT /api/apps/com.finance.loan.emicalculator/keywords
        payload = {"keywords": ["test_keyword_1", "test_keyword_2"]}
        response = client.put("/api/apps/com.finance.loan.emicalculator/keywords", json=payload)
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["keywords"] == ["test_keyword_1", "test_keyword_2"]

        # Verify it created the yaml file
        yaml_file = rulebooks_dir / "com.finance.loan.emicalculator.yaml"
        assert yaml_file.exists()
        import yaml

        with yaml_file.open() as f:
            data = yaml.safe_load(f)
            assert data["package_name"] == "com.finance.loan.emicalculator"
            assert data["aso_strategy"]["target_keywords"] == ["test_keyword_1", "test_keyword_2"]

        # Test GET /api/apps/com.finance.loan.emicalculator/keywords
        with patch("api_server.routes.apps.ASOClient") as mock_aso_client_class:
            mock_client = MagicMock()
            mock_aso_client_class.return_value = mock_client

            mock_rank = MagicMock()
            mock_rank.rank = 3
            mock_rank.was_found = True
            mock_client.track_keyword_ranking.return_value = mock_rank

            mock_diff = MagicMock()
            mock_diff.difficulty_score = 45.0
            mock_diff.difficulty_label = "Medium"
            mock_client.get_keyword_difficulty.return_value = mock_diff

            mock_vol = MagicMock()
            mock_vol.estimated_volume = 80
            mock_client.get_keyword_volume.return_value = [mock_vol]

            with patch("app_manager.config.AppManagerConfig.get_rulebook") as mock_get_rulebook:
                mock_get_rulebook.return_value = {
                    "aso_strategy": {"target_keywords": ["test_keyword_1", "test_keyword_2"]}
                }
                response = client.get("/api/apps/com.finance.loan.emicalculator/keywords")
                assert response.status_code == 200
                kws = response.json()
                assert len(kws) == 2
                assert kws[0]["keyword"] == "test_keyword_1"
                assert kws[0]["rank"] == 3
                assert kws[0]["volume"] == 80
                assert kws[0]["difficulty"] == 45.0
