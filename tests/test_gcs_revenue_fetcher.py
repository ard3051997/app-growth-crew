import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app_manager.gcs_revenue_fetcher import fetch_play_console_revenue


def create_mock_sales_csv(rows: list[dict[str, str]]) -> bytes:
    """Helper to create a zip file containing a sales report CSV."""
    csv_io = io.StringIO()
    headers = [
        "Order Number",
        "Order Charged Date",
        "Order Charged Timestamp",
        "Financial Status",
        "Device Model",
        "Product Title",
        "Package ID",
        "Product Type",
        "SKU ID",
        "Currency of Sale",
        "Item Price",
        "Taxes Collected",
        "Charged Amount",
        "City of Buyer",
        "State of Buyer",
        "Postal Code of Buyer",
        "Country of Buyer",
        "Base Plan or Purchase Option ID",
        "Offer ID",
        "Group ID",
        "First USD 1M Eligible",
        "Promotion ID",
        "Coupon Value",
        "Discount Rate",
        "Featured Product ID",
        "Price Experiment ID",
        "Sales Channel",
    ]
    writer = csv.DictWriter(csv_io, fieldnames=headers)
    writer.writeheader()
    for r in rows:
        # fill default values for missing columns
        full_row = dict.fromkeys(headers, "")
        full_row.update(r)
        writer.writerow(full_row)

    # Compress CSV into zip bytes
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("salesreport_202606.csv", csv_io.getvalue())
    return zip_buffer.getvalue()


class TestGcsRevenueFetcher:
    @patch("google.cloud.storage.Client")
    @patch("google.oauth2.service_account.Credentials.from_service_account_file")
    def test_fetch_play_console_revenue_success(self, mock_creds_fn, mock_storage_client) -> None:
        # Mock GCS setup
        mock_creds = MagicMock()
        mock_creds.project_id = "test-project"
        mock_creds_fn.return_value = mock_creds

        mock_bucket = MagicMock()
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_storage_client.return_value = mock_client

        # Mock blobs
        blob1 = MagicMock()
        blob1.name = "sales/salesreport_202606.zip"
        blob2 = MagicMock()
        blob2.name = "sales/salesreport_202605.zip"
        mock_bucket.list_blobs.return_value = [blob1, blob2]

        today_str = datetime.now(UTC).strftime("%Y-%m-%d")

        # Create sales records:
        # 1. Charged transaction in EUR (Gross 100, Tax 20 -> pre_tax 80)
        # 2. Refund transaction in GBP (Gross -50, Tax -10 -> pre_tax -40)
        # 3. Partial refund in USD (Gross -10, Tax -2 -> pre_tax -8)
        # 4. Transaction for a different package (should be ignored)
        # 5. Transaction outside lookback window (should be ignored)
        old_date_str = (datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%d")

        rows = [
            {
                "Package ID": "com.ponicamedia.voicechanger",
                "Financial Status": "Charged",
                "Order Charged Date": today_str,
                "Charged Amount": "100.00",
                "Taxes Collected": "20.00",
                "Currency of Sale": "EUR",
            },
            {
                "Package ID": "com.ponicamedia.voicechanger",
                "Financial Status": "Refund",
                "Order Charged Date": today_str,
                "Charged Amount": "-50.00",
                "Taxes Collected": "-10.00",
                "Currency of Sale": "GBP",
            },
            {
                "Package ID": "com.ponicamedia.voicechanger",
                "Financial Status": "Partial refund",
                "Order Charged Date": today_str,
                "Charged Amount": "-10.00",
                "Taxes Collected": "-2.00",
                "Currency of Sale": "USD",
            },
            {
                "Package ID": "com.other.app",
                "Financial Status": "Charged",
                "Order Charged Date": today_str,
                "Charged Amount": "9.99",
                "Taxes Collected": "0.00",
                "Currency of Sale": "USD",
            },
            {
                "Package ID": "com.ponicamedia.voicechanger",
                "Financial Status": "Charged",
                "Order Charged Date": old_date_str,
                "Charged Amount": "50.00",
                "Taxes Collected": "0.00",
                "Currency of Sale": "USD",
            },
        ]

        zip_bytes = create_mock_sales_csv(rows)
        blob1.download_as_bytes.return_value = zip_bytes
        # empty second zip
        blob2.download_as_bytes.return_value = create_mock_sales_csv([])

        res = fetch_play_console_revenue(
            credentials_path="/fake/creds.json",
            bucket_name="fake-bucket",
            package_name="com.ponicamedia.voicechanger",
            days=30,
        )

        assert res is not None
        assert res["currency"] == "USD"
        assert res["charge_count"] == 1  # Only row 1 is 'Charged' status
        assert res["source"] == "play_console_gcs"

        # Math validation:
        # EXCHANGE_RATES: EUR -> 1.08, GBP -> 1.27, USD -> 1.0
        # Gross = (100 * 1.08) + (-50 * 1.27) + (-10 * 1.0) = 108.0 - 63.5 - 10.0 = 34.50
        # Profit:
        # Pre-tax 1: 100 - 20 = 80 EUR. Profit1 = 80 * 0.85 * 1.08 = 73.44 USD
        # Pre-tax 2: -50 - (-10) = -40 GBP. Profit2 = -40 * 0.85 * 1.27 = -43.18 USD
        # Pre-tax 3: -10 - (-2) = -8 USD. Profit3 = -8 * 0.85 * 1.0 = -6.80 USD
        # Total Profit = 73.44 - 43.18 - 6.80 = 23.46 USD
        assert res["iap_revenue_30d"] == pytest.approx(34.50, 0.01)
        assert res["iap_profit_30d"] == pytest.approx(23.46, 0.01)
