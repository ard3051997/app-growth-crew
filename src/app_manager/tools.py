"""Custom tools for the coordinator agent — cross-cutting insights."""

from __future__ import annotations

from datetime import UTC, datetime


def get_system_status() -> str:
    """Check which app management services are currently configured and available.

    Returns a summary of which MCP servers are reachable and configured.
    Use this to understand what data sources are available before answering questions.
    """
    import os
    from pathlib import Path

    google_ads_env = os.environ.get("GOOGLE_ADS_CONFIGURATION_FILE_PATH")
    google_ads_path = Path(google_ads_env) if google_ads_env else Path.cwd() / "google-ads.yaml"
    services = {
        "Play Store": bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")),
        "RevenueCat": bool(os.environ.get("REVENUECAT_API_KEY")),
        "Analytics (GA4)": bool(os.environ.get("GA4_PROPERTY_ID")),
        "AdMob": bool(os.environ.get("ADMOB_ACCOUNT_ID")),
        "Google Ads": google_ads_path.exists(),
        "ASO Keywords": True,  # Always available (uses public scraping)
        "Google Cloud Storage": bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
        and bool(os.environ.get("GCS_PLAY_CONSOLE_BUCKET")),
    }

    lines = ["Service Status:"]
    for name, available in services.items():
        status = "✅ Configured" if available else "❌ Not configured"
        lines.append(f"  {name}: {status}")

    configured_count = sum(1 for v in services.values() if v)
    lines.append(f"\n{configured_count}/{len(services)} services available.")

    return "\n".join(lines)


def generate_daily_report_prompt(package_name: str) -> str:
    """Generate a prompt for the agent to create a comprehensive daily app health report.

    Args:
        package_name: The app package name to report on.

    Returns:
        A structured prompt that guides the coordinator to gather data from all sources.
    """
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    return f"""Generate a comprehensive daily health report for {package_name} ({today}).

Gather data from ALL available services and present as a unified dashboard:

## 1. Play Store Health
- Current active release (track, version, rollout %)
- Crash rate and ANR rate from vitals
- Recent reviews summary (avg rating, count, sentiment)
- Any halted or in-progress releases

## 2. Revenue (RevenueCat)
- Current MRR and trend
- Active subscribers count
- Active trials
- Churn rate
- Recent refunds

## 3. User Analytics (GA4)
- DAU/WAU/MAU
- D1/D7 retention rates
- Top acquisition channels
- Top 5 events by count

## 4. Ad Revenue (AdMob)
- Today's estimated earnings
- Yesterday's earnings
- eCPM
- Impressions and clicks

## 5. ASO Performance
- Current keyword rankings for top 3 keywords
- Listing ASO score
- Any recommendations

## Summary & Actions
- Key highlights (positive trends)
- Concerns requiring attention
- Recommended actions

Format with tables and clear sections. Use ↑↓→ for trends."""


def compare_revenue_prompt(package_name: str, days: int = 30) -> str:
    """Generate a prompt to compare subscription vs ad revenue.

    Args:
        package_name: App package name.
        days: Number of days to compare.

    Returns:
        Prompt for revenue comparison analysis.
    """
    return f"""Compare revenue sources for {package_name} over the last {days} days:

1. Get subscription revenue from RevenueCat (MRR, total revenue)
2. Get ad revenue from AdMob (last {days} days earnings)
3. Get total revenue from Analytics (GA4 revenue report)

Present:
- Side-by-side comparison table
- Revenue mix percentages
- Daily trend comparison
- Which source is growing faster
- Recommendations for revenue optimization"""


def suggest_actions_prompt(package_name: str) -> str:
    """Generate a prompt for AI-driven action recommendations.

    Args:
        package_name: App package name.

    Returns:
        Prompt for generating actionable recommendations.
    """
    return f"""Analyze all available data for {package_name} and suggest the top 5 actions:

Consider:
- Play Store: Are there releases to promote? Reviews to reply to? Listings to update?
- RevenueCat: Is churn rising? Are trials converting? Billing issues?
- Analytics: Is engagement dropping? Where are users coming from?
- AdMob: Are ad earnings declining? eCPM trends?
- ASO: Are keyword rankings slipping? Is the listing optimized?
- Google Ads: Are acquisition campaigns performing well? Is the CPA within targets? Which campaigns are driving high-value subscribers?

For each action, provide:
1. What to do
2. Why (data-driven reasoning)
3. Expected impact
4. Priority (High/Medium/Low)

Rank actions by expected impact."""


def get_app_rulebook() -> str:
    """Retrieve the rule book and compliance guidelines for the active app.

    Returns the raw YAML rule book. Always call this tool to inspect policies,
    character limits, budget caps, and prohibited terms before planning storefront updates.
    """
    import os
    from pathlib import Path

    package_name = os.environ.get("APP_PACKAGE_NAME", "")
    if not package_name:
        return "No active app configured (APP_PACKAGE_NAME is empty)."

    rulebook_path = Path("rulebooks") / f"{package_name}.yaml"
    if not rulebook_path.exists():
        return f"No rule book configured for {package_name}."

    try:
        return rulebook_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading rule book for {package_name}: {e}"
