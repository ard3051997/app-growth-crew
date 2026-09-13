"""Parse Play Console sales ZIP exports from Google Cloud Storage.

Play Console exports sales monthly to GCS under:
  sales/salesreport_{YYYYMM}.zip

Each ZIP contains a single CSV file (salesreport_{YYYYMM}.csv) with ALL transactions
for the account in that month. The CSV is UTF-8 encoded.

Relevant columns:
  - Package ID         : app package identifier
  - Financial Status   : "Charged" | "Refund" | "Partial refund"
  - Charged Amount     : gross charged amount in local currency (includes tax, signed)
  - Taxes Collected    : tax portion of the charge (signed)
  - Currency of Sale   : 3-letter local currency code
  - Order Charged Date : YYYY-MM-DD
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Field size limit — Play Console CSVs can have very large fields
csv.field_size_limit(10_000_000)

# Standard exchange rates to USD (matching aggregate_revenue.py)
EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "CAD": 0.73,
    "AUD": 0.66,
    "INR": 0.012,
    "MXN": 0.054,
    "TRY": 0.031,
    "BRL": 0.18,
    "SGD": 0.74,
    "PHP": 0.017,
    "JPY": 0.0064,
    "CLP": 0.0011,
    "PEN": 0.27,
    "COP": 0.00025,
    "BOB": 0.14,
    "CRC": 0.0019,
    "PYG": 0.00013,
    "AED": 0.27,
    "SAR": 0.27,
    "PLN": 0.25,
    "SEK": 0.096,
    "NOK": 0.094,
    "ILS": 0.27,
    "MYR": 0.21,
    "THB": 0.027,
    "IDR": 0.000061,
    "VND": 0.000039,
    "KRW": 0.00072,
    "TWD": 0.031,
    "NZD": 0.61,
    "CHF": 1.11,
    "CZK": 0.043,
    "HUF": 0.0027,
    "RON": 0.22,
    "BGN": 0.55,
    "UAH": 0.025,
    "EGP": 0.021,
    "BDT": 0.0085,
    "QAR": 0.27,
    "KWD": 3.26,
    "BHD": 2.65,
    "ZAR": 0.054,
}


def fetch_play_console_revenue(
    credentials_path: str,
    bucket_name: str,
    package_name: str,
    days: int = 30,
) -> dict[str, Any] | None:
    """Fetch gross IAP/subscription revenue and net profit from Play Console GCS sales ZIP.

    Finds the most recent monthly sales ZIP, parses the embedded CSV,
    filters to the given package and date window, and sums Gross Revenue & Developer Proceeds.

    Args:
        credentials_path: Path to the Google service account JSON file.
        bucket_name: Play Console GCS export bucket name.
        package_name: Android package name (e.g. com.ponicamedia.voicechanger).
        days: How many past days to include (default 30).

    Returns:
        {"iap_revenue_30d": float, "iap_profit_30d": float, "currency": "USD",
         "charge_count": int, "source": "play_console_gcs"} or None on failure.
    """
    try:
        from google.cloud import storage
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(credentials_path)
        client = storage.Client(credentials=creds, project=creds.project_id)
        bucket = client.bucket(bucket_name)
    except Exception as exc:
        logger.warning("Failed to init GCS client for sales reports", error=str(exc))
        return None

    # Find the most recent sales report ZIPs
    try:
        blobs = list(bucket.list_blobs(prefix="sales/"))
        zip_blobs = [b for b in blobs if "salesreport_" in b.name and b.name.endswith(".zip")]
        if not zip_blobs:
            logger.info("No sales ZIP files found", bucket=bucket_name)
            return None
        # Sort by name descending → most recent month first
        zip_blobs.sort(key=lambda b: b.name, reverse=True)
    except Exception as exc:
        logger.warning("Failed to list sales blobs", error=str(exc))
        return None

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    total_gross = 0.0
    total_profit = 0.0
    charge_count = 0
    success = False

    # Process up to the 2 most recent ZIPs to handle month boundaries
    for target_blob in zip_blobs[:2]:
        logger.info(
            "Parsing Play Console sales report", blob=target_blob.name, package=package_name
        )
        try:
            raw = target_blob.download_as_bytes()
            sub_gross, sub_profit, sub_count = _parse_sales_zip(raw, package_name, cutoff, now=now)
            total_gross += sub_gross
            total_profit += sub_profit
            charge_count += sub_count
            success = True
        except Exception as exc:
            logger.warning(
                "Failed to download or parse sales ZIP", blob=target_blob.name, error=str(exc)
            )

    if not success or (total_gross == 0.0 and charge_count == 0):
        return None

    return {
        "iap_revenue_30d": round(total_gross, 2),
        "iap_profit_30d": round(total_profit, 2),
        "currency": "USD",
        "charge_count": charge_count,
        "source": "play_console_gcs",
    }


def _decode_csv(csv_bytes: bytes) -> str:
    """Decode Play Console CSV bytes — handles UTF-16-LE BOM and UTF-8 correctly."""
    if csv_bytes[:2] == b"\xff\xfe":
        return csv_bytes[2:].decode("utf-16-le", errors="replace")
    if csv_bytes[:2] == b"\xfe\xff":
        return csv_bytes[2:].decode("utf-16-be", errors="replace")
    return csv_bytes.decode("utf-8", errors="replace")


def _parse_sales_zip(
    raw: bytes,
    package_name: str,
    cutoff: datetime,
    now: datetime | None = None,
) -> tuple[float, float, int]:
    """Extract the CSV from the ZIP and parse it for a specific package."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_names:
            logger.warning("No CSV file inside sales ZIP")
            return 0.0, 0.0, 0
        csv_bytes = zf.read(csv_names[0])
    except Exception as exc:
        logger.warning("Failed to extract CSV from sales ZIP", error=str(exc))
        return 0.0, 0.0, 0

    csv_text = _decode_csv(csv_bytes)

    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        total_gross = 0.0
        total_profit = 0.0
        charge_count = 0

        upper_bound = now or datetime.now(UTC)
        for row in reader:
            # Match package ID
            pkg = row.get("Package ID") or ""
            if pkg.strip() != package_name:
                continue

            # Status can be Charged, Refund, Partial refund
            status = row.get("Financial Status") or ""
            if status not in ("Charged", "Refund", "Partial refund"):
                continue

            # Date filter — format: YYYY-MM-DD
            date_str = row.get("Order Charged Date", "")
            try:
                txn_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
                if txn_date < cutoff or txn_date > upper_bound:
                    continue
            except ValueError:
                continue

            # Parse amounts and currency
            charged_amt_str = row.get("Charged Amount", "0").replace(",", "").strip()
            taxes_collected_str = row.get("Taxes Collected", "0").replace(",", "").strip()
            cur = row.get("Currency of Sale", "").strip()
            rate = EXCHANGE_RATES.get(cur)
            if rate is None:
                logger.warning("Skipping unsupported sales currency", currency=cur)
                continue

            try:
                charged_amt = float(charged_amt_str)
            except ValueError:
                continue

            try:
                taxes_collected = float(taxes_collected_str) if taxes_collected_str else 0.0
            except ValueError:
                continue

            # Gross Revenue = Charged Amount * Exchange Rate
            total_gross += charged_amt * rate

            # Net Proceeds = (Charged Amount - Taxes Collected) * 85% * Exchange Rate
            pre_tax_amount = charged_amt - taxes_collected
            total_profit += pre_tax_amount * 0.85 * rate

            if status == "Charged":
                charge_count += 1

        return total_gross, total_profit, charge_count

    except Exception as exc:
        logger.warning("Failed to parse sales CSV", error=str(exc))
        return 0.0, 0.0, 0
