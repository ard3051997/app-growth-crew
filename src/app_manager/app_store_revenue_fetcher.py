"""Fetch sales/revenue data from Apple App Store Connect Sales Reports API.

Requires AppCredentials with:
  app_store_connect_key_id    — API key ID (e.g. ABCDE12345)
  app_store_connect_issuer_id — Issuer UUID from App Store Connect
  app_store_connect_private_key_path — Path to .p8 private key file

API reference:
  GET https://api.appstoreconnect.apple.com/v1/salesReports
  Params: frequency=MONTHLY, reportType=SALES, reportSubType=SUMMARY, vendorNumber=...
"""

from __future__ import annotations

import csv
import io
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import jwt
import structlog

if TYPE_CHECKING:
    from app_manager.credential_store import AppCredentials

logger = structlog.get_logger(__name__)

_ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
IAP_PRODUCT_TYPES = frozenset({"IA1", "IA9"})
SUBSCRIPTION_PRODUCT_TYPES = frozenset({"IAC", "IAY"})


def _generate_jwt(key_id: str, issuer_id: str, private_key_path: str) -> str:
    """Generate a signed JWT for the App Store Connect API (ES256, 20-min expiry)."""
    private_key = Path(private_key_path).read_text()
    now = int(time.time())
    payload = {
        "iss": issuer_id,
        "iat": now,
        "exp": now + 1200,  # 20 minutes
        "aud": "appstoreconnect-v1",
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": key_id})


def fetch_app_store_revenue(
    creds: AppCredentials,
    year_month: str,
) -> dict[str, Any] | None:
    """Fetch monthly App Store sales summary for an iOS app.

    Args:
        creds: AppCredentials with has_app_store_connect() == True.
        year_month: Month in YYYY-MM format (e.g. "2026-06").

    Returns:
        {"iap_revenue_30d": float, "subscription_revenue_30d": float,
         "source": "app_store_connect"} or None on failure.
    """
    if not creds.has_app_store_connect():
        return None
    key_id = creds.app_store_connect_key_id
    issuer_id = creds.app_store_connect_issuer_id
    private_key_path = creds.app_store_connect_private_key_path
    if not key_id or not issuer_id or not private_key_path:
        return None

    try:
        token = _generate_jwt(key_id, issuer_id, private_key_path)
    except Exception as exc:
        logger.warning("Failed to generate App Store Connect JWT", error=str(exc))
        return None

    # First, get the vendor number from the account
    vendor_number = _get_vendor_number(token)
    if not vendor_number:
        return None

    # Resolve the bundle ID from the package_name (strip -id suffix if present)
    bundle_id = _resolve_bundle_id(creds.package_name)

    return _fetch_sales_report(token, vendor_number, year_month, bundle_id)


def _get_vendor_number(token: str) -> str | None:
    """Fetch vendor number from App Store Connect account."""
    try:
        resp = httpx.get(
            f"{_ASC_BASE}/salesReports",
            params={
                "filter[reportType]": "SALES",
                "filter[reportSubType]": "SUMMARY",
                "filter[frequency]": "MONTHLY",
                "filter[reportDate]": datetime.now(UTC).strftime("%Y-%m"),
                "filter[vendorNumber]": "PLACEHOLDER",
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        # Extract vendor number from error response if placeholder used
        if resp.status_code == 400:
            data = resp.json()
            for err in data.get("errors", []):
                detail = err.get("detail", "")
                if "vendor" in detail.lower():
                    import re

                    match = re.search(r"\b\d{8,10}\b", detail)
                    if match:
                        return match.group(0)
    except Exception as exc:
        logger.debug("Unable to infer vendor number from sales report response", error=str(exc))

    # Fallback: query the first accessible vendor via financialReports
    try:
        resp = httpx.get(
            f"{_ASC_BASE}/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            vendor_info = resp.json().get("data", {}).get("relationships", {})
            logger.info("ASC /me response", keys=list(vendor_info.keys()))
    except Exception as exc:
        logger.debug("App Store account metadata fallback failed", error=str(exc))

    return None


def _resolve_bundle_id(package_name: str) -> str | None:
    """Extract numeric App Store track ID or return bundle ID."""
    import re

    match = re.search(r"id(\d+)$", package_name)
    return match.group(1) if match else package_name


def _fetch_sales_report(
    token: str, vendor_number: str, year_month: str, bundle_id: str | None
) -> dict[str, Any] | None:
    """Download and parse the monthly SALES SUMMARY report."""
    try:
        resp = httpx.get(
            f"{_ASC_BASE}/salesReports",
            params={
                "filter[reportType]": "SALES",
                "filter[reportSubType]": "SUMMARY",
                "filter[frequency]": "MONTHLY",
                "filter[reportDate]": year_month,
                "filter[vendorNumber]": vendor_number,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
        )

        if resp.status_code != 200:
            logger.warning("ASC sales report API error", status=resp.status_code)
            return None

        # Response is a gzipped TSV; httpx decompresses automatically
        content = resp.text
    except Exception as exc:
        logger.warning("ASC sales report fetch failed", error=str(exc))
        return None

    return _parse_sales_tsv(content, bundle_id)


def _parse_sales_tsv(content: str, bundle_id: str | None) -> dict[str, Any] | None:
    """Parse App Store Connect sales TSV report."""
    try:
        reader = csv.DictReader(io.StringIO(content), delimiter="\t")
        iap_total = 0.0
        sub_total = 0.0

        for row in reader:
            # Filter by Apple Identifier (numeric) or Developer App Name
            if bundle_id:
                app_id_col = row.get("Apple Identifier", "") or row.get("SKU", "")
                if bundle_id not in app_id_col:
                    continue

            product_type = row.get("Product Type Identifier", "").strip()
            proceeds_currency = row.get("Currency of Proceeds", "").strip()
            if proceeds_currency != "USD":
                continue
            try:
                units = float(row.get("Units", ""))
                proceeds = float(row.get("Developer Proceeds", ""))
            except (TypeError, ValueError):
                continue
            revenue = units * proceeds

            if product_type in IAP_PRODUCT_TYPES:
                iap_total += revenue
            elif product_type in SUBSCRIPTION_PRODUCT_TYPES:
                sub_total += revenue

        if iap_total == 0 and sub_total == 0:
            return None

        return {
            "iap_revenue_30d": round(iap_total, 2),
            "subscription_revenue_30d": round(sub_total, 2),
            "currency": "USD",
            "source": "app_store_connect",
        }
    except Exception as exc:
        logger.warning("Failed to parse ASC sales TSV", error=str(exc))
        return None
