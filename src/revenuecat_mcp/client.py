"""RevenueCat REST API v2 client."""

from __future__ import annotations

import functools
import os
import random
import time
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from revenuecat_mcp.models import (
    ChartData,
    ChartDataPoint,
    Entitlement,
    EntitlementGrantResult,
    NonSubscription,
    Offering,
    OverviewMetrics,
    Package,
    Product,
    RefundResult,
    Subscriber,
    Subscription,
    Transaction,
)

logger = structlog.get_logger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 32.0

BASE_URL = "https://api.revenuecat.com"
V1_BASE = f"{BASE_URL}/v1"
V2_BASE = f"{BASE_URL}/v2"


class RevenueCatClientError(Exception):
    """Base exception for RevenueCat client errors."""


def retry_with_backoff(func):  # type: ignore[no-untyped-def]
    """Decorator to retry API calls with exponential backoff on transient errors."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        retries = 0
        backoff = INITIAL_BACKOFF

        while retries < MAX_RETRIES:
            try:
                return func(*args, **kwargs)
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 500, 502, 503):
                    retries += 1
                    if retries >= MAX_RETRIES:
                        raise
                    sleep_time = backoff * (0.5 + random.random())  # noqa: S311
                    logger.warning(
                        "API error, retrying",
                        status=e.response.status_code,
                        retry=retries,
                        sleep=sleep_time,
                    )
                    time.sleep(sleep_time)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                else:
                    raise
            except httpx.ConnectError:
                retries += 1
                if retries >= MAX_RETRIES:
                    raise
                sleep_time = backoff * (0.5 + random.random())  # noqa: S311
                logger.warning("Connection error, retrying", retry=retries, sleep=sleep_time)
                time.sleep(sleep_time)
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue

    return wrapper


class RevenueCatClient:
    """Client for interacting with RevenueCat REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Initialize the RevenueCat client.

        Args:
            api_key: RevenueCat API secret key.
                    Defaults to REVENUECAT_API_KEY env var.
            project_id: RevenueCat project ID for v2 endpoints.
                       Defaults to REVENUECAT_PROJECT_ID env var.
        """
        self._api_key = api_key or os.environ.get("REVENUECAT_API_KEY")
        self._project_id = project_id or os.environ.get("REVENUECAT_PROJECT_ID")
        self._logger = logger.bind(component="RevenueCatClient")
        self._http: httpx.Client | None = None

        if not self._api_key:
            raise RevenueCatClientError(
                "No API key found. Set REVENUECAT_API_KEY environment variable "
                "or pass api_key parameter."
            )

    def _get_http(self) -> httpx.Client:
        """Return the shared HTTP client, creating it on first use."""
        if self._http is None:
            self._http = httpx.Client(timeout=30.0)
        return self._http

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        if self._http is not None:
            self._http.close()
            self._http = None

    def _get_headers(self) -> dict[str, str]:
        """Get request headers for the API."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _v1_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a v1 API request."""
        url = f"{V1_BASE}{path}"
        response = self._get_http().request(
            method,
            url,
            headers=self._get_headers(),
            json=json_body,
            params=params,
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def _v2_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a v2 API request."""
        url = f"{V2_BASE}{path}"
        response = self._get_http().request(
            method,
            url,
            headers=self._get_headers(),
            json=json_body,
            params=params,
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    # =========================================================================
    # Subscriber Management
    # =========================================================================

    @retry_with_backoff
    def get_subscriber(self, app_user_id: str) -> Subscriber:
        """Get subscriber information by app user ID.

        Args:
            app_user_id: The app user ID to look up.

        Returns:
            Subscriber profile with entitlements and purchase history.
        """
        self._logger.info("Fetching subscriber", app_user_id=app_user_id)

        data = self._v1_request("GET", f"/subscribers/{app_user_id}")
        subscriber_data = data.get("subscriber", {})

        # Parse entitlements
        entitlements: dict[str, Entitlement] = {}
        for ent_id, ent_data in subscriber_data.get("entitlements", {}).items():
            entitlements[ent_id] = Entitlement(
                entitlement_id=ent_id,
                product_id=ent_data.get("product_identifier"),
                expires_date=_parse_iso(ent_data.get("expires_date")),
                purchase_date=_parse_iso(ent_data.get("purchase_date")),
                is_active=_is_active(ent_data.get("expires_date")),
                will_renew=ent_data.get("will_renew", False),
                period_type=ent_data.get("period_type"),
                store=ent_data.get("store"),
                is_sandbox=ent_data.get("is_sandbox", False),
                unsubscribe_detected_at=_parse_iso(ent_data.get("unsubscribe_detected_at")),
                billing_issues_detected_at=_parse_iso(ent_data.get("billing_issues_detected_at")),
            )

        # Parse subscriptions
        subscriptions: dict[str, Subscription] = {}
        for sub_id, sub_data in subscriber_data.get("subscriptions", {}).items():
            subscriptions[sub_id] = Subscription(
                product_id=sub_id,
                expires_date=_parse_iso(sub_data.get("expires_date")),
                purchase_date=_parse_iso(sub_data.get("purchase_date")),
                original_purchase_date=_parse_iso(sub_data.get("original_purchase_date")),
                store=sub_data.get("store"),
                is_sandbox=sub_data.get("is_sandbox", False),
                period_type=sub_data.get("period_type"),
                unsubscribe_detected_at=_parse_iso(sub_data.get("unsubscribe_detected_at")),
                billing_issues_detected_at=_parse_iso(sub_data.get("billing_issues_detected_at")),
                refunded_at=_parse_iso(sub_data.get("refunded_at")),
                auto_resume_date=_parse_iso(sub_data.get("auto_resume_date")),
            )

        # Parse non-subscriptions
        non_subscriptions: dict[str, list[NonSubscription]] = {}
        for prod_id, purchases in subscriber_data.get("non_subscriptions", {}).items():
            non_subscriptions[prod_id] = [
                NonSubscription(
                    product_id=prod_id,
                    purchase_date=_parse_iso(p.get("purchase_date")),
                    store=p.get("store"),
                    is_sandbox=p.get("is_sandbox", False),
                    id=p.get("id"),
                )
                for p in purchases
            ]

        return Subscriber(
            app_user_id=app_user_id,
            original_app_user_id=subscriber_data.get("original_app_user_id"),
            first_seen=_parse_iso(subscriber_data.get("first_seen")),
            last_seen=_parse_iso(subscriber_data.get("last_seen")),
            entitlements=entitlements,
            subscriptions=subscriptions,
            non_subscriptions=non_subscriptions,
            management_url=subscriber_data.get("management_url"),
            original_purchase_date=_parse_iso(subscriber_data.get("original_purchase_date")),
        )

    # =========================================================================
    # Offerings
    # =========================================================================

    @retry_with_backoff
    def _get_offering_packages(self, offering_id: str) -> list[Package]:
        """Fetch packages for one offering.

        The v2 offerings endpoints never embed packages inline — RevenueCat
        requires a separate call per offering to retrieve them.
        """
        if not self._project_id:
            raise RevenueCatClientError(
                "Project ID required for v2 endpoints. Set REVENUECAT_PROJECT_ID."
            )

        data = self._v2_request(
            "GET",
            f"/projects/{self._project_id}/offerings/{offering_id}/packages",
        )

        return [
            Package(
                identifier=pkg.get("lookup_key", ""),
                platform_product_identifier=pkg.get("platform_product_identifier"),
                display_string=pkg.get("display_name"),
            )
            for pkg in data.get("items", [])
        ]

    @retry_with_backoff
    def list_offerings(self) -> list[Offering]:
        """List all offerings for the project.

        Returns:
            List of offerings with their packages.
        """
        self._logger.info("Listing offerings")

        if not self._project_id:
            raise RevenueCatClientError(
                "Project ID required for v2 endpoints. Set REVENUECAT_PROJECT_ID."
            )

        data = self._v2_request("GET", f"/projects/{self._project_id}/offerings")

        offerings: list[Offering] = []
        for item in data.get("items", []):
            offerings.append(
                Offering(
                    identifier=item.get("lookup_key", ""),
                    description=item.get("display_name"),
                    is_current=item.get("is_current", False),
                    packages=self._get_offering_packages(item.get("id", "")),
                    metadata=item.get("metadata"),
                )
            )

        return offerings

    @retry_with_backoff
    def get_offering(self, offering_id: str) -> Offering:
        """Get a specific offering by ID.

        Args:
            offering_id: The offering identifier.

        Returns:
            Offering details with packages.
        """
        self._logger.info("Fetching offering", offering_id=offering_id)

        if not self._project_id:
            raise RevenueCatClientError(
                "Project ID required for v2 endpoints. Set REVENUECAT_PROJECT_ID."
            )

        data = self._v2_request(
            "GET",
            f"/projects/{self._project_id}/offerings/{offering_id}",
        )

        return Offering(
            identifier=data.get("lookup_key", ""),
            description=data.get("display_name"),
            is_current=data.get("is_current", False),
            packages=self._get_offering_packages(data.get("id", offering_id)),
            metadata=data.get("metadata"),
        )

    # =========================================================================
    # Metrics & Charts
    # =========================================================================

    @retry_with_backoff
    def get_overview_metrics(self, store: str | None = None) -> OverviewMetrics:
        """Get revenue overview metrics.

        Args:
            store: Optional store filter. Use "app_store" for iOS or "play_store"
                   for Android. Pass None for cross-platform totals (default).

        Returns:
            Overview metrics including MRR, active subscribers, trials, churn.
        """
        self._logger.info("Fetching overview metrics", store=store)

        if not self._project_id:
            raise RevenueCatClientError(
                "Project ID required for v2 endpoints. Set REVENUECAT_PROJECT_ID."
            )

        params: dict[str, Any] | None = None
        if store:
            params = {
                "filters[0][type]": "store",
                "filters[0][value]": store,
            }

        data = self._v2_request(
            "GET",
            f"/projects/{self._project_id}/metrics/overview",
            params=params,
        )

        metrics = data.get("metrics", [])
        result = OverviewMetrics()

        for metric in metrics:
            metric_id = metric.get("id", "")
            name = metric.get("name", "")
            value = metric.get("value", 0)

            if metric_id == "active_subscriptions" or name == "active_subscribers_count":
                result.active_subscribers = int(value)
            elif metric_id == "active_trials" or name == "active_trials_count":
                result.active_trials = int(value)
            elif metric_id == "mrr" or name == "mrr":
                result.mrr = float(value)
            elif metric_id == "revenue" or name == "revenue":
                result.revenue = float(value)
            elif metric_id == "new_customers" or name == "new_customers_count":
                result.new_subscribers = int(value)
            elif metric_id == "churn" or name == "churn":
                result.churn_rate = float(value)
            elif metric_id == "refund_rate" or name == "refund_rate":
                result.refund_rate = float(value)
            elif metric_id == "active_users" or name == "active_users_count":
                result.active_users = int(value)

        return result

    @retry_with_backoff
    def get_charts(
        self,
        metric_name: str = "revenue",
        resolution: str = "day",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ChartData:
        """Get chart data for a specific metric.

        Args:
            metric_name: Metric to chart (revenue, mrr, active_subscribers,
                        new_subscribers, churn, active_trials, etc.)
            resolution: Data resolution (day, week, month)
            start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago.
            end_date: End date (YYYY-MM-DD). Defaults to today.

        Returns:
            Chart data with time-series data points.
        """
        self._logger.info(
            "Fetching chart data",
            metric=metric_name,
            resolution=resolution,
        )

        if not self._project_id:
            raise RevenueCatClientError("Project ID required. Set REVENUECAT_PROJECT_ID.")

        if not start_date:
            start_date = (datetime.now(tz=UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

        params = {
            "resolution": resolution,
            "start_date": start_date,
            "end_date": end_date,
        }

        data = self._v2_request(
            "GET",
            f"/projects/{self._project_id}/metrics/{metric_name}",
            params=params,
        )

        data_points = [
            ChartDataPoint(
                date=dp.get("date", ""),
                value=float(dp.get("value", 0)),
            )
            for dp in data.get("values", [])
        ]

        total = sum(dp.value for dp in data_points) if data_points else None

        return ChartData(
            metric_name=metric_name,
            period=resolution,
            data_points=data_points,
            total=total,
        )

    @retry_with_backoff
    def get_revenue_by_store(
        self,
        store: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get revenue and MRR filtered to a single store using the charts endpoint.

        The /metrics/overview endpoint returns project-wide totals with no
        store filter. This method uses /charts/revenue and /charts/mrr with
        a store filter to get per-platform revenue.

        Args:
            store: "app_store" (iOS) or "play_store" (Android).
            days: Lookback window in days (default 30).

        Returns:
            {"revenue": float, "mrr": float, "store": str}
        """
        if not self._project_id:
            raise RevenueCatClientError("Project ID required. Set REVENUECAT_PROJECT_ID.")

        import json as _json
        from datetime import UTC, datetime, timedelta

        start_date = (datetime.now(tz=UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

        store_filter = _json.dumps([{"name": "store", "values": [store]}])

        params = {
            "start_date": start_date,
            "end_date": end_date,
            "resolution": "day",
            "filters": store_filter,
        }

        revenue = 0.0
        mrr = 0.0

        try:
            rev_data = self._v2_request(
                "GET",
                f"/projects/{self._project_id}/charts/revenue",
                params=params,
            )
            revenue = sum(float(dp.get("value", 0)) for dp in rev_data.get("values", []))
        except Exception as exc:
            self._logger.warning(
                "Failed to fetch revenue chart by store", store=store, error=str(exc)
            )

        try:
            # MRR — use latest data point value (it's a stock metric, not a flow)
            mrr_data = self._v2_request(
                "GET",
                f"/projects/{self._project_id}/charts/mrr",
                params={**params, "resolution": "month"},
            )
            values = mrr_data.get("values", [])
            if values:
                mrr = float(values[-1].get("value", 0))
        except Exception as exc:
            self._logger.warning("Failed to fetch MRR chart by store", store=store, error=str(exc))

        return {"revenue": round(revenue, 2), "mrr": round(mrr, 2), "store": store}

    # =========================================================================
    # Transactions
    # =========================================================================

    @retry_with_backoff
    def get_transaction_history(
        self,
        app_user_id: str,
        limit: int = 100,
    ) -> list[Transaction]:
        """Get transaction history for a subscriber.

        Args:
            app_user_id: The app user ID.
            limit: Maximum transactions to return.

        Returns:
            List of transactions.
        """
        self._logger.info(
            "Fetching transactions",
            app_user_id=app_user_id,
            limit=limit,
        )

        # Get subscriber data and reconstruct transaction history from purchases
        subscriber = self.get_subscriber(app_user_id)
        transactions: list[Transaction] = []

        for sub_id, sub in subscriber.subscriptions.items():
            transactions.append(
                Transaction(
                    transaction_id=f"sub_{sub_id}_{sub.purchase_date}",
                    product_id=sub.product_id,
                    app_user_id=app_user_id,
                    purchased_at=sub.purchase_date,
                    store=sub.store,
                    is_trial=sub.period_type == "trial",
                    is_renewal=sub.purchase_date != sub.original_purchase_date,
                    was_refunded=sub.refunded_at is not None,
                )
            )

        for prod_id, purchases in subscriber.non_subscriptions.items():
            for purchase in purchases:
                transactions.append(
                    Transaction(
                        transaction_id=purchase.id or f"iap_{prod_id}",
                        product_id=prod_id,
                        app_user_id=app_user_id,
                        purchased_at=purchase.purchase_date,
                        store=purchase.store,
                    )
                )

        # Sort by date descending
        transactions.sort(
            key=lambda t: t.purchased_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

        return transactions[:limit]

    # =========================================================================
    # Entitlements Management
    # =========================================================================

    @retry_with_backoff
    def grant_entitlement(
        self,
        app_user_id: str,
        entitlement_id: str,
        duration: str = "monthly",
    ) -> EntitlementGrantResult:
        """Grant a promotional entitlement to a user.

        Args:
            app_user_id: The app user ID.
            entitlement_id: Entitlement identifier to grant.
            duration: Duration (daily, three_day, weekly, monthly, two_month,
                     three_month, six_month, yearly, lifetime).

        Returns:
            Grant result.
        """
        self._logger.info(
            "Granting entitlement",
            app_user_id=app_user_id,
            entitlement_id=entitlement_id,
            duration=duration,
        )

        try:
            self._v1_request(
                "POST",
                f"/subscribers/{app_user_id}/entitlements/{entitlement_id}/promotional",
                json_body={"duration": duration},
            )

            return EntitlementGrantResult(
                success=True,
                app_user_id=app_user_id,
                entitlement_id=entitlement_id,
                message=f"Successfully granted {entitlement_id} ({duration}) to {app_user_id}",
            )
        except httpx.HTTPStatusError as e:
            return EntitlementGrantResult(
                success=False,
                app_user_id=app_user_id,
                entitlement_id=entitlement_id,
                message=f"Failed to grant entitlement: {e.response.status_code}",
                error=str(e),
            )

    @retry_with_backoff
    def revoke_entitlement(
        self,
        app_user_id: str,
        entitlement_id: str,
    ) -> EntitlementGrantResult:
        """Revoke a promotional entitlement from a user.

        Args:
            app_user_id: The app user ID.
            entitlement_id: Entitlement identifier to revoke.

        Returns:
            Revocation result.
        """
        self._logger.info(
            "Revoking entitlement",
            app_user_id=app_user_id,
            entitlement_id=entitlement_id,
        )

        try:
            self._v1_request(
                "POST",
                f"/subscribers/{app_user_id}/entitlements/{entitlement_id}/revoke_promotionals",
            )

            return EntitlementGrantResult(
                success=True,
                app_user_id=app_user_id,
                entitlement_id=entitlement_id,
                message=f"Successfully revoked {entitlement_id} from {app_user_id}",
            )
        except httpx.HTTPStatusError as e:
            return EntitlementGrantResult(
                success=False,
                app_user_id=app_user_id,
                entitlement_id=entitlement_id,
                message=f"Failed to revoke entitlement: {e.response.status_code}",
                error=str(e),
            )

    # =========================================================================
    # Refunds
    # =========================================================================

    def _find_subscription_for_transaction(
        self, app_user_id: str, store_transaction_id: str
    ) -> str | None:
        """Locate the RevenueCat subscription ID owning a given store transaction."""
        encoded_id = urllib.parse.quote(app_user_id, safe="")
        subs_data = self._v2_request(
            "GET", f"/projects/{self._project_id}/customers/{encoded_id}/subscriptions"
        )
        for sub in subs_data.get("items", []):
            sub_id = sub.get("id")
            if not sub_id:
                continue
            tx_data = self._v2_request(
                "GET", f"/projects/{self._project_id}/subscriptions/{sub_id}/transactions"
            )
            if any(tx.get("id") == store_transaction_id for tx in tx_data.get("items", [])):
                return str(sub_id)
        return None

    @retry_with_backoff
    def refund_purchase(
        self,
        app_user_id: str,
        store_transaction_id: str,
    ) -> RefundResult:
        """Refund a Play Store or Galaxy subscription transaction via RevenueCat.

        Uses the v2 API (`.../subscriptions/{id}/transactions/{id}/actions/refund`)
        since v1's subscriber-level refund endpoint requires a legacy secret key
        that newer RevenueCat projects are not issued.

        Args:
            app_user_id: The app user ID.
            store_transaction_id: The store transaction identifier.

        Returns:
            Refund result.
        """
        self._logger.info(
            "Processing refund",
            app_user_id=app_user_id,
            store_transaction_id=store_transaction_id,
        )

        try:
            subscription_id = self._find_subscription_for_transaction(
                app_user_id, store_transaction_id
            )
            if subscription_id is None:
                return RefundResult(
                    success=False,
                    app_user_id=app_user_id,
                    store_transaction_id=store_transaction_id,
                    message="Refund failed: transaction not found on any subscription",
                    error="transaction_not_found",
                )

            self._v2_request(
                "POST",
                f"/projects/{self._project_id}/subscriptions/{subscription_id}"
                f"/transactions/{store_transaction_id}/actions/refund",
            )

            return RefundResult(
                success=True,
                app_user_id=app_user_id,
                store_transaction_id=store_transaction_id,
                message=f"Successfully refunded transaction {store_transaction_id}",
            )
        except httpx.HTTPStatusError as e:
            return RefundResult(
                success=False,
                app_user_id=app_user_id,
                store_transaction_id=store_transaction_id,
                message=f"Refund failed: {e.response.status_code}",
                error=str(e),
            )

    # =========================================================================
    # Products
    # =========================================================================

    @retry_with_backoff
    def list_products(self) -> list[Product]:
        """List all products configured in RevenueCat.

        Returns:
            List of products.
        """
        self._logger.info("Listing products")

        if not self._project_id:
            raise RevenueCatClientError("Project ID required. Set REVENUECAT_PROJECT_ID.")

        data = self._v2_request(
            "GET",
            f"/projects/{self._project_id}/products",
        )

        return [
            Product(
                product_id=item.get("id", ""),
                store_identifier=item.get("store_identifier"),
                product_type=item.get("type"),
                app_id=item.get("app_id"),
                display_name=item.get("display_name"),
                created_at=_parse_iso(item.get("created_at")),
            )
            for item in data.get("items", [])
        ]

    @retry_with_backoff
    def create_offering(
        self,
        project_id: str | None = None,
        offering_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new offering in RevenueCat.

        Args:
            project_id: RevenueCat project ID.
            offering_config: Offering configuration dictionary.
        """
        proj_id = project_id or self._project_id
        if not proj_id:
            raise RevenueCatClientError("Project ID required. Set REVENUECAT_PROJECT_ID.")

        self._logger.info("Creating RevenueCat offering", project_id=proj_id)
        config = offering_config or {}

        try:
            res = self._v2_request(
                "POST",
                f"/projects/{proj_id}/offerings",
                json_body=config,
            )
            return {"success": True, "offering": res}
        except httpx.HTTPStatusError as e:
            self._logger.exception("Failed to create offering", status=e.response.status_code)
            return {
                "success": False,
                "error": f"Failed to create offering: {e.response.status_code}",
            }

    @retry_with_backoff
    def update_offering(
        self,
        offering_id: str,
        updates: dict[str, Any],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Update an offering in RevenueCat.

        Args:
            offering_id: The offering identifier.
            updates: Dictionary of update fields.
            project_id: RevenueCat project ID.
        """
        proj_id = project_id or self._project_id
        if not proj_id:
            raise RevenueCatClientError("Project ID required. Set REVENUECAT_PROJECT_ID.")

        self._logger.info(
            "Updating RevenueCat offering", project_id=proj_id, offering_id=offering_id
        )
        try:
            res = self._v2_request(
                "PATCH",
                f"/projects/{proj_id}/offerings/{offering_id}",
                json_body=updates,
            )
            return {"success": True, "offering": res}
        except httpx.HTTPStatusError as e:
            self._logger.exception("Failed to update offering", status=e.response.status_code)
            return {
                "success": False,
                "error": f"Failed to update offering: {e.response.status_code}",
            }

    @retry_with_backoff
    def create_package(
        self,
        offering_id: str,
        package_config: dict[str, Any],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a package under an offering in RevenueCat.

        Args:
            offering_id: The offering identifier.
            package_config: Package configuration dictionary.
            project_id: RevenueCat project ID.
        """
        proj_id = project_id or self._project_id
        if not proj_id:
            raise RevenueCatClientError("Project ID required. Set REVENUECAT_PROJECT_ID.")

        self._logger.info(
            "Creating RevenueCat package", project_id=proj_id, offering_id=offering_id
        )
        try:
            res = self._v2_request(
                "POST",
                f"/projects/{proj_id}/offerings/{offering_id}/packages",
                json_body=package_config,
            )
            return {"success": True, "package": res}
        except httpx.HTTPStatusError as e:
            self._logger.exception("Failed to create package", status=e.response.status_code)
            return {
                "success": False,
                "error": f"Failed to create package: {e.response.status_code}",
            }

    @retry_with_backoff
    def attach_product(
        self,
        package_id: str,
        product_config: dict[str, Any],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach a product to a package in RevenueCat.

        Args:
            package_id: The package identifier.
            product_config: Product configuration dictionary.
            project_id: RevenueCat project ID.
        """
        proj_id = project_id or self._project_id
        if not proj_id:
            raise RevenueCatClientError("Project ID required. Set REVENUECAT_PROJECT_ID.")

        self._logger.info("Attaching RevenueCat product", project_id=proj_id, package_id=package_id)
        try:
            res = self._v2_request(
                "POST",
                f"/projects/{proj_id}/packages/{package_id}/products",
                json_body=product_config,
            )
            return {"success": True, "product": res}
        except httpx.HTTPStatusError as e:
            self._logger.exception("Failed to attach product", status=e.response.status_code)
            return {
                "success": False,
                "error": f"Failed to attach product: {e.response.status_code}",
            }


# =============================================================================
# Helpers
# =============================================================================


def _parse_iso(value: str | int | float | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string or epoch timestamp (ms/sec) to datetime, or None."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    try:
        # Handle various ISO formats
        cleaned = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def _is_active(expires_date: str | None) -> bool:
    """Check if an entitlement is still active based on expiry."""
    if not expires_date:
        return False
    parsed = _parse_iso(expires_date)
    if not parsed:
        return False
    return parsed > datetime.now(tz=UTC)
