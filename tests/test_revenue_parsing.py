"""Revenue parser classification and malformed-row tests."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta

from app_manager.app_store_revenue_fetcher import _parse_sales_tsv
from app_manager.gcs_revenue_fetcher import _parse_sales_zip


def test_app_store_parser_separates_iap_and_subscription_and_rejects_unknowns() -> None:
    headers = [
        "Apple Identifier",
        "Product Type Identifier",
        "Units",
        "Developer Proceeds",
        "Currency of Proceeds",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, delimiter="\t")
    writer.writeheader()
    writer.writerows(
        [
            dict(zip(headers, ["123", "IA1", "2", "3.5", "USD"], strict=True)),
            dict(zip(headers, ["123", "IAY", "1", "9", "USD"], strict=True)),
            dict(zip(headers, ["123", "1E", "10", "99", "USD"], strict=True)),
            dict(zip(headers, ["123", "IA1", "1", "5", "EUR"], strict=True)),
            dict(zip(headers, ["123", "IA1", "bad", "5", "USD"], strict=True)),
        ]
    )

    result = _parse_sales_tsv(output.getvalue(), "123")
    assert result == {
        "iap_revenue_30d": 7.0,
        "subscription_revenue_30d": 9.0,
        "currency": "USD",
        "source": "app_store_connect",
    }


def test_play_sales_parser_rejects_bad_dates_amounts_future_and_currency() -> None:
    now = datetime.now(UTC)
    headers = [
        "Package ID",
        "Financial Status",
        "Order Charged Date",
        "Charged Amount",
        "Taxes Collected",
        "Currency of Sale",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    valid_date = now.strftime("%Y-%m-%d")
    writer.writerows(
        [
            dict(zip(headers, ["com.app", "Charged", valid_date, "10", "2", "USD"], strict=True)),
            dict(zip(headers, ["com.app", "Charged", "bad", "50", "0", "USD"], strict=True)),
            dict(zip(headers, ["com.app", "Charged", valid_date, "bad", "0", "USD"], strict=True)),
            dict(zip(headers, ["com.app", "Charged", valid_date, "50", "0", "XYZ"], strict=True)),
            dict(
                zip(
                    headers,
                    [
                        "com.app",
                        "Charged",
                        (now + timedelta(days=2)).strftime("%Y-%m-%d"),
                        "50",
                        "0",
                        "USD",
                    ],
                    strict=True,
                )
            ),
        ]
    )
    compressed = io.BytesIO()
    with zipfile.ZipFile(compressed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sales.csv", output.getvalue())

    gross, profit, count = _parse_sales_zip(
        compressed.getvalue(), "com.app", now - timedelta(days=30), now=now
    )
    assert gross == 10.0
    assert profit == 6.8
    assert count == 1
