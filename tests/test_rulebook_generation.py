"""Tests for funnel_engine_mcp.server.generate_app_rulebook."""

from __future__ import annotations

import types
from pathlib import Path

import pytest
import yaml

from app_manager.credential_store import AppCredentials
from funnel_engine_mcp.server import generate_app_rulebook


def _android_creds(package_name: str) -> AppCredentials:
    return AppCredentials(
        package_name=package_name,
        google_credentials_path="/fake/fake-creds.json",
        revenuecat_api_key="sk_test_xxx",
        revenuecat_project_id="proj_test",
        admob_account_id="pub-123",
    )


def _ios_creds(package_name: str) -> AppCredentials:
    return AppCredentials(
        package_name=package_name,
        app_store_connect_key_id="key123",
        app_store_connect_issuer_id="issuer123",
        app_store_connect_private_key_path="/fake/fake-key.p8",
    )


@pytest.fixture(autouse=True)
def _cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_generates_conservative_android_rulebook(monkeypatch: pytest.MonkeyPatch) -> None:
    package_name = "com.example.testapp"

    monkeypatch.setattr(
        "app_manager.credential_store.get_app_credentials",
        lambda pkg: _android_creds(pkg),
    )

    fake_listing = types.SimpleNamespace(
        title="Test App", short_description="Short", full_description="Full"
    )
    monkeypatch.setattr(
        "funnel_engine_mcp.server.PlayStoreClient",
        lambda **kwargs: types.SimpleNamespace(get_listing=lambda pkg: fake_listing),  # noqa: ARG005
    )

    fake_keywords = types.SimpleNamespace(
        title_keywords=["test", "app"], description_keywords=["productivity", "test"]
    )
    monkeypatch.setattr(
        "aso_keyword_mcp.client.ASOClient",
        lambda: types.SimpleNamespace(get_app_keywords=lambda pkg: fake_keywords),  # noqa: ARG005
    )

    fake_offering = types.SimpleNamespace(identifier="default")
    monkeypatch.setattr(
        "funnel_engine_mcp.server.RevenueCatClient",
        lambda **kwargs: types.SimpleNamespace(list_offerings=lambda: [fake_offering]),  # noqa: ARG005
    )

    result = generate_app_rulebook(package_name)

    rulebook_path = Path("rulebooks") / f"{package_name}.yaml"
    assert rulebook_path.exists()
    assert str(rulebook_path) in result

    data = yaml.safe_load(rulebook_path.read_text(encoding="utf-8"))
    assert data["package_name"] == package_name
    assert data["safety_rules"]["require_telegram_approval"] is True
    assert data["safety_rules"]["interceptor_tools"] == ["play_store/update_listing"]
    assert data["monetization"]["has_subscriptions"] is True
    assert data["monetization"]["has_ads"] is True
    assert data["monetization"]["revenue_gate_type"] == "subscription"
    assert set(data["aso_strategy"]["target_keywords"]) == {"test", "app", "productivity"}
    assert data["metadata_constraints"]["title"]["max_length"] == 30
    assert data["metadata_constraints"]["title"]["required_keywords"] == ["Test"]


def test_generates_conservative_ios_rulebook(monkeypatch: pytest.MonkeyPatch) -> None:
    package_name = "com.example.iosapp"

    monkeypatch.setattr(
        "app_manager.credential_store.get_app_credentials",
        lambda pkg: _ios_creds(pkg),
    )
    monkeypatch.setattr(
        "app_store_mcp.client.AppStoreClient",
        lambda: types.SimpleNamespace(get_app_details=lambda pkg: {"title": "iOS App"}),  # noqa: ARG005
    )

    result = generate_app_rulebook(package_name)
    assert "Generated rulebook" in result

    data = yaml.safe_load((Path("rulebooks") / f"{package_name}.yaml").read_text())
    assert data["safety_rules"]["interceptor_tools"] == ["app_store_connect/update_listing"]
    assert "subtitle" in data["metadata_constraints"]
    assert data["monetization"]["has_subscriptions"] is False


def test_refuses_to_overwrite_without_force(monkeypatch: pytest.MonkeyPatch) -> None:
    package_name = "com.example.existing"
    rulebook_path = Path("rulebooks")
    rulebook_path.mkdir()
    (rulebook_path / f"{package_name}.yaml").write_text("package_name: existing\n")

    monkeypatch.setattr(
        "app_manager.credential_store.get_app_credentials",
        lambda pkg: _android_creds(pkg),
    )

    result = generate_app_rulebook(package_name)
    assert "already exists" in result
    assert "force=True" in result
    # Original content untouched.
    assert "existing" in (rulebook_path / f"{package_name}.yaml").read_text()
