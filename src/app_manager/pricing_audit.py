"""Regional pricing completeness audits.

Generalizes the pattern proven by hand in scratch/audit_pricing.py and
scratch/remediate_pricing.py, which found and fixed a real regional-pricing gap
for one app (com.wordbox.ai) by comparing a hardcoded list of old/new SKU pairs.
That specific SKU-migration comparison was one-off and app-specific, but the
underlying finding generalizes: any app can silently be missing regional prices
for a target market on some of its products, and nothing in the portfolio
currently checks for that automatically, for any app.

This module reuses the existing PlayStoreClient (list_subscriptions,
list_in_app_products, get_in_app_product) so it works for any app with Play
Store credentials configured via credential_store, not just the one app this
was originally checked for by hand.

Output stays read-only / human-reviewable — it does not patch prices. Automated
pricing changes are explicitly out of scope per docs/remaining.md's beta plan; this
only makes the "find the gap" half of that proven pattern repeatable across the
portfolio instead of living in one-off scripts for one app.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app_manager.credential_store import get_app_credentials
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError

# Countries the wordbox pricing migration treated as "must have distinct pricing."
# Callers can override this with whatever markets matter for a given app.
DEFAULT_TARGET_COUNTRIES: frozenset[str] = frozenset(
    {
        "MX",
        "BR",
        "TR",
        "US",
        "PT",
        "ES",
        "IT",
        "FR",
        "AT",
        "UA",
        "KR",
        "CA",
        "DE",
        "GB",
        "AU",
        "JP",
        "NL",
        "DK",
        "CH",
        "NO",
    }
)


def _regional_countries_for_managed_product(prices: dict[str, Any] | None) -> set[str]:
    return set((prices or {}).keys())


def _regional_countries_for_subscription(base_plans: list[dict[str, Any]]) -> set[str]:
    countries: set[str] = set()
    for base_plan in base_plans:
        for regional_config in base_plan.get("regionalConfigs", []):
            region_code = regional_config.get("regionCode")
            if region_code:
                countries.add(str(region_code))
    return countries


def audit_regional_pricing_completeness(
    package_name: str,
    *,
    target_countries: frozenset[str] = DEFAULT_TARGET_COUNTRIES,
) -> dict[str, Any]:
    """Flag in-app products and subscriptions missing regional pricing for target markets.

    Args:
        package_name: App package name to audit.
        target_countries: Country codes the app is expected to price for. Defaults to
            the market list used in the proven wordbox pricing remediation.

    Returns:
        A report with one finding per product/subscription that is missing pricing
        for one or more target countries. Empty `findings` means full coverage (or
        no products were found).
    """
    credentials = get_app_credentials(package_name)
    if not credentials.has_play_store():
        return {
            "app_package": package_name,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "no_play_store_credentials",
            "findings": [],
        }

    client = PlayStoreClient(credentials_path=credentials.google_credentials_path)
    findings: list[dict[str, Any]] = []
    products_checked = 0

    try:
        for summary in client.list_in_app_products(package_name):
            products_checked += 1
            try:
                product = client.get_in_app_product(package_name, summary.sku)
            except PlayStoreClientError:
                continue
            covered = _regional_countries_for_managed_product(product.prices)
            missing = sorted(target_countries - covered)
            if missing:
                findings.append(
                    {
                        "experiment_type": "pricing_experiment",
                        "capability": "planning_only",
                        "product_type": "managed_product",
                        "sku": product.sku,
                        "hypothesis": (
                            f"'{product.sku}' has no regional price configured for "
                            f"{len(missing)} target market(s); users there may be seeing a "
                            "fallback price or be unable to purchase, leaving revenue on the table."
                        ),
                        "missing_countries": missing,
                        "covered_countries": sorted(covered),
                    }
                )

        for subscription in client.list_subscriptions(package_name):
            products_checked += 1
            covered = _regional_countries_for_subscription(subscription.base_plans)
            missing = sorted(target_countries - covered)
            if missing:
                findings.append(
                    {
                        "experiment_type": "pricing_experiment",
                        "capability": "planning_only",
                        "product_type": "subscription",
                        "sku": subscription.product_id,
                        "hypothesis": (
                            f"'{subscription.product_id}' has no regional price configured for "
                            f"{len(missing)} target market(s); users there may be seeing a "
                            "fallback price or be unable to purchase, leaving revenue on the table."
                        ),
                        "missing_countries": missing,
                        "covered_countries": sorted(covered),
                    }
                )
    except PlayStoreClientError as exc:
        return {
            "app_package": package_name,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": f"play_store_error: {exc}",
            "findings": findings,
        }

    return {
        "app_package": package_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "ok",
        "products_checked": products_checked,
        "findings": findings,
    }
