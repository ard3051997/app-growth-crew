# Funnel Engine Architecture & Failure Modes

## How It Works
The Funnel Engine is the core analytic component of MCP-GC, responsible for stitching together metrics from four distinct sources into a single unified 10-stage funnel:
1. **Google Analytics 4 (via `analytics-mcp`)**: Engagement metrics (D1 active, Onboarding, Paywall, Trial start, Retention).
2. **Google Play Store (via GCS)**: Top of funnel metrics (Store Visitors, Installs, Conversion Rates).
3. **RevenueCat (via `revenuecat-mcp`)**: Subscription revenue and paid conversions.
4. **AdMob (via `admob-mcp`)**: Ad revenue and impressions.

The execution flow for `run_funnel_analysis` works as follows:
1. **Data Ingestion**: GCS Play Store CSV files are fetched and converted by `app_manager/storefront_analyst.py` into a SQLite database (`data/store_performance.db`). This handles the very top of the funnel.
2. **Analytics Fetch**: GA4 events are fetched to build the middle of the funnel.
3. **Revenue Fetch**: Real revenue metrics are aggregated from AdMob and RevenueCat.
4. **Funnel Assembly**: `funnel_engine/analyzer.py` calculates conversion rates across all 10 stages and checks them against category benchmarks (from `benchmarks.py`). Missing top-of-funnel metrics are back-calculated using category benchmarks if the real data is missing.

## Where It Breaks (The Top-of-Funnel Conversion Issue)

Currently, the Funnel Engine is silently failing to surface real Play Store conversion data and instead falls back to estimated benchmarks. The symptom is that "Impression → Store View" and "Store View → Install" stages are marked as estimated, or the real metrics don't show up. 

This happens due to two major architectural gaps:

### 1. SQLite Database Path Resolution (CWD Mismatch)
Both `storefront_analyst.py` and `funnel_engine/db.py` use a relative path for the database: `DEFAULT_DB_PATH = Path("data/store_performance.db")`. 
Because the `funnel_engine_mcp` is an MCP server, it runs in a different working directory than the main `app_manager`. When `_prepare_play_store_details` attempts to query the database, it resolves `data/store_performance.db` relative to the MCP server's CWD, resulting in it creating a new, empty SQLite database instead of reading the one populated by `storefront_analyst.py`. As a result, `real_metrics` is always `None`, and the engine falls back to estimated benchmarks.

**Fix**: Ensure `DEFAULT_DB_PATH` is resolved absolutely from the project root (e.g. `Path(__file__).parent.parent.parent / "data" / "store_performance.db"`).

### 2. GA4 vs Play Store Install Discrepancy
The analysis uses `installs` fetched from GA4 (`first_open` events) as the ground truth for the middle of the funnel, but uses `installs` from the Play Store SQLite db for the top of the funnel. If these two numbers differ significantly (e.g., users download but never open the app), the funnel conversion rates become distorted. The system currently forces `details_dict["installs"] = real_metrics["installs"]` overwriting the GA4 number in the top layer, but the lower layers (like D1 active) are computed against the GA4 cohort. This creates a mismatched denominator when computing `Install → Day 1 Active`.

**Fix**: The funnel analyzer must explicitly reconcile GA4 `first_open` events and Play Store Installs, either by displaying them as two distinct stages (Store Install vs App Open) or standardizing on one source of truth.

### 3. SQLite Date Query Formatting 
The queries in `funnel_engine/db.py` rely on the SQLite `date()` function to filter a 30-day window from the latest available date:
```sql
SELECT SUM(visitors), SUM(installs)
FROM listing_performance_by_traffic_source
WHERE package_name = ? AND date >= date(?, '-30 days');
```
While this query works correctly *if* the `date` string in the database conforms strictly to the `YYYY-MM-DD` format, if `storefront_analyst.py` ever ingests a CSV where dates are exported in `MM/DD/YYYY` or another non-ISO format, the `date()` function evaluates to `NULL` and the query returns 0.

## Next Steps
To resolve the Play Store conversion missing data:
1. Hardcode or resolve `DEFAULT_DB_PATH` as an absolute path in `db.py` and `storefront_analyst.py`.
2. Standardize `installs` handling between Play Store and GA4 across the Funnel Analyzer.
