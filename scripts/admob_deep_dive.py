#!/usr/bin/env python3
"""
AdMob Revenue Deep Dive — EMI Calculator
Breaks down AdMob earnings by APP and by DATE to find the root cause
of the discrepancy vs GA4.
"""

import os
import sys
from datetime import UTC, datetime, timedelta
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

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from admob_mcp.client import AdMobClient

PACKAGE_NAME = os.environ.get("APP_PACKAGE_NAME", "com.finance.loan.emicalculator")

now = datetime.now(tz=UTC)
start_30d = (now - timedelta(days=30)).strftime("%Y-%m-%d")
start_7d  = (now - timedelta(days=7)).strftime("%Y-%m-%d")
today     = now.strftime("%Y-%m-%d")
yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")


def sep(char="─", width=70):
    print(char * width)


def main():
    client = AdMobClient()

    sep("═")
    print("  AdMob Revenue Deep Dive — Diagnosing the Calculation")
    sep("═")
    print()

    # ── 1. List all apps in the AdMob account ─────────────────────────────
    print("📱  STEP 1: All Apps in AdMob Account")
    sep()
    from admob_mcp.mappings import get_package_for_app_id
    apps = client.list_apps()
    emi_app_id = None
    for app in apps:
        store_id = getattr(app, "linked_app_store_id", "") or ""
        app_id   = getattr(app, "app_id", "")
        name     = getattr(app, "name", "")
        platform = getattr(app, "platform", "")
        
        # Try resolving using mappings if not in linked_app_store_id
        mapped_pkg = get_package_for_app_id(app_id)
        display_pkg = store_id or mapped_pkg or "N/A"
        
        marker = ""
        if PACKAGE_NAME == display_pkg:
            marker = " ← EMI Calculator"
            emi_app_id = app_id
            
        print(f"  {name or '(no name)':<40} | {platform:<8} | store:{display_pkg:<35} | admob_id:{app_id}{marker}")
    print()

    if not emi_app_id:
        print(f"⚠️  Could not find AdMob app matching package: {PACKAGE_NAME}")
        print("   Checking store IDs above — will use account-wide totals as fallback")
    else:
        print(f"✅  Found EMI Calculator AdMob App ID: {emi_app_id}")
    print()

    # ── 2. Account-wide 30-day total (no filter) ─────────────────────────
    print("📊  STEP 2: Account-Wide Totals (ALL apps, no filter)")
    sep()
    total_report = client.get_network_report(
        start_date=start_30d,
        end_date=today,
        dimensions=["APP"],
        metrics=["ESTIMATED_EARNINGS", "IMPRESSIONS", "CLICKS"],
    )
    account_total = 0.0
    print(f"  {'App ID':<45} | {'Earnings':>10} | {'Impressions':>12} | {'Clicks':>8}")
    sep("-")
    for row in total_report.rows:
        app_dim = row.dimensions.get("APP", "unknown")
        earn    = row.metrics.get("ESTIMATED_EARNINGS", 0.0)
        imps    = int(row.metrics.get("IMPRESSIONS", 0))
        clks    = int(row.metrics.get("CLICKS", 0))
        account_total += earn
        marker = " ← EMI" if emi_app_id and app_dim == emi_app_id else ""
        print(f"  {app_dim:<45} | ${earn:>9.2f} | {imps:>12,} | {clks:>8,}{marker}")
    sep("-")
    print(f"  {'TOTAL':<45} | ${account_total:>9.2f}")
    print()

    # ── 3. EMI Calculator only (filtered) ────────────────────────────────
    if emi_app_id:
        print(f"📊  STEP 3: EMI Calculator Only (filter: {emi_app_id})")
        sep()
        emi_filters = [{"dimension": "APP", "matchesAny": {"values": [emi_app_id]}}]

        emi_30d = client.get_network_report(
            start_date=start_30d,
            end_date=today,
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS", "IMPRESSIONS", "CLICKS"],
            dimension_filters=emi_filters,
        )
        emi_30d_total = sum(r.metrics.get("ESTIMATED_EARNINGS", 0) for r in emi_30d.rows)
        emi_30d_imps  = sum(int(r.metrics.get("IMPRESSIONS", 0)) for r in emi_30d.rows)

        emi_7d = client.get_network_report(
            start_date=start_7d,
            end_date=today,
            dimensions=["DATE"],
            metrics=["ESTIMATED_EARNINGS", "IMPRESSIONS"],
            dimension_filters=emi_filters,
        )
        emi_7d_total = sum(r.metrics.get("ESTIMATED_EARNINGS", 0) for r in emi_7d.rows)

        print(f"  Last 30 Days  : ${emi_30d_total:,.2f}  ({len(emi_30d.rows)} days of data, {emi_30d_imps:,} impressions)")
        print(f"  Last 7 Days   : ${emi_7d_total:,.2f}  ({len(emi_7d.rows)} days of data)")
        print()

        # ── Day-by-day breakdown for last 7 days ─────────────────────────
        print("  Day-by-day (last 7 days):")
        sep("-", 50)
        for row in sorted(emi_7d.rows, key=lambda r: r.dimensions.get("DATE", ""), reverse=True):
            date = row.dimensions.get("DATE", "?")
            earn = row.metrics.get("ESTIMATED_EARNINGS", 0.0)
            imps = int(row.metrics.get("IMPRESSIONS", 0))
            print(f"    {date}  ${earn:>8.2f}  ({imps:,} impressions)")
        print()

    # ── 4. Reproduce get_earnings_summary logic manually ─────────────────
    print("🔍  STEP 4: Reproduce get_earnings_summary Calculation")
    sep()
    print("  (This is what the old script called — checking date math)")
    print()

    # Original logic: today, yesterday, 7d (now-7 to now), 30d (now-30 to now)
    old_today_start = today
    old_7d_start    = (now - timedelta(days=7)).strftime("%Y-%m-%d")  # 8 days inclusive
    old_30d_start   = (now - timedelta(days=30)).strftime("%Y-%m-%d")  # 31 days inclusive

    emi_filters_check = [{"dimension": "APP", "matchesAny": {"values": [emi_app_id]}}] if emi_app_id else None

    old_today_rep = client.get_network_report(
        start_date=old_today_start, end_date=today,
        dimensions=["DATE"], metrics=["ESTIMATED_EARNINGS"],
        dimension_filters=emi_filters_check,
    )
    old_7d_rep = client.get_network_report(
        start_date=old_7d_start, end_date=today,
        dimensions=["DATE"], metrics=["ESTIMATED_EARNINGS"],
        dimension_filters=emi_filters_check,
    )
    old_30d_rep = client.get_network_report(
        start_date=old_30d_start, end_date=today,
        dimensions=["DATE"], metrics=["ESTIMATED_EARNINGS"],
        dimension_filters=emi_filters_check,
    )

    old_today_total = sum(r.metrics.get("ESTIMATED_EARNINGS", 0) for r in old_today_rep.rows)
    old_7d_total    = sum(r.metrics.get("ESTIMATED_EARNINGS", 0) for r in old_7d_rep.rows)
    old_30d_total   = sum(r.metrics.get("ESTIMATED_EARNINGS", 0) for r in old_30d_rep.rows)

    print(f"  get_earnings_summary 'Today'     : ${old_today_total:.2f}  (date: {today} to {today})")
    print(f"  get_earnings_summary 'Last 7d'   : ${old_7d_total:.2f}   (date: {old_7d_start} to {today}) → {len(old_7d_rep.rows)} days")
    print(f"  get_earnings_summary 'Last 30d'  : ${old_30d_total:.2f}  (date: {old_30d_start} to {today}) → {len(old_30d_rep.rows)} days")
    print()
    print(f"  ⚠️  '30d' uses now-30 to now (inclusive) = {len(old_30d_rep.rows)} rows")
    print(f"      True 30-day period (exclusive today): see STEP 3 above")
    print()

    # ── 5. Summary ────────────────────────────────────────────────────────
    sep("═")
    print("  SUMMARY")
    sep("═")
    if emi_app_id:
        print(f"  Account-wide 30d total (all apps)         : ${account_total:,.2f}")
        print(f"  EMI Calculator only 30d (true 30 days)    : ${emi_30d_total:,.2f}")
        print(f"  EMI Calculator only 7d  (true 7 days)     : ${emi_7d_total:,.2f}")
        print()
        other_apps_rev = account_total - emi_30d_total
        print(f"  Other apps revenue in account (30d)       : ${other_apps_rev:,.2f}")
        print()
    print(f"  For reference — GA4 reported ad revenue:")
    print(f"    Last 7 Days  : $712.61")
    print(f"    Last 30 Days : $3,047.17")
    print()
    print("  💡 Root cause check: Is AdMob under- or over-counting vs GA4?")
    print("     GA4 = Firebase SDK attribution (includes ALL mediation partners)")
    print("     AdMob = AdMob network earnings only (excludes 3rd-party mediation)")
    print()


if __name__ == "__main__":
    main()
