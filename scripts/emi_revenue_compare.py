#!/usr/bin/env python3
"""
EMI Calculator — Revenue Comparison: GA4 vs AdMob
Fetches revenue data from both sources and prints a side-by-side comparison.
"""

import os
import sys
from pathlib import Path

# ── Load .env ──────────────────────────────────────────────────────────────
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analytics_mcp.client import AnalyticsClient
from admob_mcp.client import AdMobClient

PACKAGE_NAME = os.environ.get("APP_PACKAGE_NAME", "com.finance.loan.emicalculator")
DATE_RANGES = [
    ("7d",  "7daysAgo",  "Last 7 Days"),
    ("30d", "30daysAgo", "Last 30 Days"),
]


def separator(char="─", width=60):
    print(char * width)


def fetch_ga4_revenue(client: AnalyticsClient):
    """Fetch revenue data from GA4."""
    results = {}
    for key, start, label in DATE_RANGES:
        try:
            r = client.get_revenue_report(start_date=start, end_date="today")
            results[key] = {
                "label": label,
                "total_revenue": getattr(r, "total_revenue", 0.0),
                "purchase_revenue": getattr(r, "purchase_revenue", 0.0),
                "ad_revenue": getattr(r, "ad_revenue", 0.0),
            }
        except Exception as e:
            results[key] = {"label": label, "error": str(e)}
    return results


def fetch_admob_revenue(client: AdMobClient):
    """Fetch earnings summary from AdMob (uses its own date ranges)."""
    try:
        from admob_mcp.mappings import get_app_id_for_package
        
        # Try resolving app ID from mappings first
        app_id = get_app_id_for_package(PACKAGE_NAME, publisher_id=client._account_id)
        
        if not app_id:
            # Fallback to search list_apps
            apps = client.list_apps()
            for app in apps:
                linked_id = getattr(app, "linked_app_store_id", "") or ""
                if PACKAGE_NAME in linked_id:
                    app_id = getattr(app, "app_id", None) or getattr(app, "name", None)
                    break

        if not app_id:
            # Try to get earnings summary without filtering by app
            summary = client.get_earnings_summary()
        else:
            summary = client.get_earnings_summary(app_id=app_id)

        return {
            "app_id": app_id,
            "today":         getattr(summary, "today", 0.0),
            "yesterday":     getattr(summary, "yesterday", 0.0),
            "last_7_days":   getattr(summary, "last_7_days", 0.0),
            "last_30_days":  getattr(summary, "last_30_days", 0.0),
            "impressions_today": getattr(summary, "impressions_today", 0),
            "clicks_today":      getattr(summary, "clicks_today", 0),
            "ecpm_today":        getattr(summary, "ecpm_today", 0.0),
        }
    except Exception as e:
        return {"error": str(e)}


def print_ga4_section(ga4_data: dict):
    separator()
    print("📊  GA4 Analytics Revenue")
    separator()
    for key, data in ga4_data.items():
        label = data.get("label", key)
        if "error" in data:
            print(f"  {label}: ❌ Error — {data['error']}")
        else:
            print(f"  {label}:")
            print(f"    Total Revenue     : ${data['total_revenue']:,.2f}")
            print(f"    Purchase Revenue  : ${data['purchase_revenue']:,.2f}")
            print(f"    Ad Revenue (GA4)  : ${data['ad_revenue']:,.2f}")
    print()


def print_admob_section(admob_data: dict):
    separator()
    print("💰  AdMob Earnings")
    separator()
    if "error" in admob_data:
        print(f"  ❌ Error — {admob_data['error']}")
    else:
        app_id = admob_data.get("app_id") or "All apps"
        print(f"  App ID: {app_id}")
        print()
        print(f"  Today             : ${admob_data['today']:,.2f}")
        print(f"  Yesterday         : ${admob_data['yesterday']:,.2f}")
        print(f"  Last 7 Days       : ${admob_data['last_7_days']:,.2f}")
        print(f"  Last 30 Days      : ${admob_data['last_30_days']:,.2f}")
        print()
        print(f"  Impressions Today : {admob_data['impressions_today']:,}")
        print(f"  Clicks Today      : {admob_data['clicks_today']:,}")
        print(f"  eCPM Today        : ${admob_data['ecpm_today']:,.2f}")
    print()


def print_comparison(ga4_data: dict, admob_data: dict):
    separator("═")
    print("🔍  Comparison — GA4 Ad Revenue vs AdMob Earnings")
    separator("═")

    if "error" in admob_data:
        print("  Cannot compare — AdMob fetch failed.")
        return

    for key, data in ga4_data.items():
        if "error" in data:
            continue
        label = data.get("label", key)
        ga4_ad_rev = data.get("ad_revenue", 0.0)

        if key == "7d":
            admob_rev = admob_data.get("last_7_days", 0.0)
        else:
            admob_rev = admob_data.get("last_30_days", 0.0)

        if admob_rev > 0:
            diff = ga4_ad_rev - admob_rev
            pct = (diff / admob_rev) * 100
            direction = "↑ GA4 higher" if diff > 0 else "↓ GA4 lower"
            print(f"\n  {label}:")
            print(f"    GA4 Ad Revenue  : ${ga4_ad_rev:,.2f}")
            print(f"    AdMob Earnings  : ${admob_rev:,.2f}")
            print(f"    Difference      : ${abs(diff):,.2f}  ({abs(pct):.1f}%  {direction})")
        else:
            print(f"\n  {label}:")
            print(f"    GA4 Ad Revenue  : ${ga4_ad_rev:,.2f}")
            print(f"    AdMob Earnings  : $0.00  (no data)")

    print()
    separator("═")
    print()
    print("ℹ️  Note: GA4 ad revenue is attribution-modelled (Firebase SDK).")
    print("   AdMob earnings are network-verified (source of truth for payouts).")
    print("   A 10-20% gap is normal due to attribution windows and reporting lag.")
    print()


def main():
    print()
    separator("═")
    print(f"  EMI Calculator Revenue Report — {PACKAGE_NAME}")
    separator("═")
    print()

    print("🔌 Connecting to GA4...")
    ga4_client = AnalyticsClient()
    ga4_data = fetch_ga4_revenue(ga4_client)
    print_ga4_section(ga4_data)

    print("🔌 Connecting to AdMob...")
    admob_client = AdMobClient()
    admob_data = fetch_admob_revenue(admob_client)
    print_admob_section(admob_data)

    print_comparison(ga4_data, admob_data)


if __name__ == "__main__":
    main()
