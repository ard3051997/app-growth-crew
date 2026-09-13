"""Google Ads metrics fetcher using the official google-ads Python SDK.

Uses GoogleAdsClient.load_from_storage() which reads google-ads.yaml
(developer_token, client_id, client_secret, refresh_token) and handles
gRPC transport + manager-account auth automatically.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

EXCHANGE_RATES = {
    "USD": 1.0,
    "THB": 0.027,
    "SGD": 0.74,
    "INR": 0.012,
    "EUR": 1.08,
    "GBP": 1.27,
}

_METRICS_QUERY = """
    SELECT
        metrics.impressions,
        metrics.clicks,
        metrics.conversions,
        metrics.cost_micros,
        customer.currency_code
    FROM customer
    WHERE segments.date DURING LAST_{days}_DAYS
"""


def convert_to_usd(amount: float, currency: str) -> float:
    """Convert amount from local currency to USD."""
    rate = EXCHANGE_RATES.get(currency.upper(), 1.0)
    return amount * rate


def _normalize_customer_id(customer_id: str) -> str:
    """Strip dashes — Google Ads API expects plain digits."""
    return re.sub(r"[^0-9]", "", customer_id)


def _load_client(config_path: str) -> Any:
    """Load a GoogleAdsClient from the YAML config file."""
    from google.ads.googleads.client import GoogleAdsClient  # type: ignore[import]

    client = GoogleAdsClient.load_from_storage(config_path, version="v24")
    # Set login_customer_id from environment or KalaGato default manager
    manager_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "9064502435")
    client.login_customer_id = _normalize_customer_id(manager_id)
    return client


def _build_metrics_query(days: int) -> str:
    """Build GAQL using only an integer lookback value."""
    return _METRICS_QUERY.format(days=int(days))


def fetch_google_ads_metrics(
    config_path: str,
    customer_id: str,
    days: int = 30,
) -> dict[str, Any]:
    """Fetch aggregated campaign metrics for one Google Ads customer account.

    Returns a dict with keys: impressions, clicks, installs, cost_usd, cpi.
    Returns an empty dict on any failure so callers handle it gracefully.
    """
    if not Path(config_path).exists():
        logger.warning("google-ads.yaml not found", path=config_path)
        return {}

    cid = _normalize_customer_id(customer_id)
    if not cid:
        logger.warning("Invalid customer_id", raw=customer_id)
        return {}

    try:
        client = _load_client(config_path)
        ga_service = client.get_service("GoogleAdsService")

        query = _build_metrics_query(days)

        response = ga_service.search(customer_id=cid, query=query)

        total_impressions = 0
        total_clicks = 0
        total_conversions = 0.0
        total_cost_micros = 0
        currency = "USD"

        for row in response:
            m = row.metrics
            total_impressions += m.impressions
            total_clicks += m.clicks
            total_conversions += m.conversions
            total_cost_micros += m.cost_micros
            currency = row.customer.currency_code

        cost_local = total_cost_micros / 1_000_000
        cost_usd = convert_to_usd(cost_local, currency)
        installs = int(total_conversions)
        cpi = round(cost_usd / installs, 4) if installs > 0 else 0.0

        return {
            "impressions": total_impressions,
            "clicks": total_clicks,
            "installs": installs,
            "cost_usd": round(cost_usd, 2),
            "cpi": cpi,
        }

    except Exception as exc:
        logger.warning(
            "Google Ads SDK query failed",
            customer_id=customer_id,
            error=str(exc),
        )
        return {}


def fetch_google_ads_metrics_bulk(
    config_path: str,
    customer_map: dict[str, str],
    days: int = 30,
) -> dict[str, dict[str, Any]]:
    """Fetch metrics for multiple customer accounts in parallel (one SDK client).

    Args:
        config_path: Path to google-ads.yaml.
        customer_map: {package_name: customer_id} mapping.
        days: Lookback window in days.

    Returns:
        {package_name: metrics_dict} — empty dict per app on failure.
    """
    if not customer_map or not Path(config_path).exists():
        return {pkg: {} for pkg in customer_map}

    try:
        client = _load_client(config_path)
    except Exception as exc:
        logger.warning("Failed to load Google Ads client", error=str(exc))
        return {pkg: {} for pkg in customer_map}

    results: dict[str, dict[str, Any]] = {}

    def _query_one(pkg: str, cid_raw: str) -> tuple[str, dict[str, Any]]:
        cid = _normalize_customer_id(cid_raw)
        if not cid:
            return pkg, {}
        try:
            ga_service = client.get_service("GoogleAdsService")
            query = _build_metrics_query(days)
            response = ga_service.search(customer_id=cid, query=query)

            impressions = clicks = cost_micros = 0
            conversions = 0.0
            currency = "USD"
            for row in response:
                m = row.metrics
                impressions += m.impressions
                clicks += m.clicks
                conversions += m.conversions
                cost_micros += m.cost_micros
                currency = row.customer.currency_code

            cost_local = cost_micros / 1_000_000
            cost_usd = convert_to_usd(cost_local, currency)
            installs = int(conversions)
            return pkg, {
                "impressions": impressions,
                "clicks": clicks,
                "installs": installs,
                "cost_usd": round(cost_usd, 2),
                "cpi": round(cost_usd / installs, 4) if installs > 0 else 0.0,
            }
        except Exception as exc:
            logger.warning("Bulk Google Ads query failed", pkg=pkg, error=str(exc))
            return pkg, {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_query_one, pkg, cid): pkg for pkg, cid in customer_map.items()}
        for fut in as_completed(futures, timeout=20):
            try:
                pkg, data = fut.result()
                results[pkg] = data
            except Exception:
                results[futures[fut]] = {}

    return results
