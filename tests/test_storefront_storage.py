import json
import sqlite3
from pathlib import Path

import pytest

from app_manager.storefront_analyst import (
    export_db_to_json,
    ingest_csv_data,
    parse_csv_content,
)
from funnel_engine.db import (
    get_country_performance,
    get_search_performance,
    get_total_impressions,
    get_total_storefront_metrics,
    get_traffic_performance,
    init_db,
    save_country_performance,
    save_impressions_performance,
    save_search_performance,
    save_traffic_performance,
)


@pytest.fixture
def temp_db(tmp_path):
    """Fixture to initialize a temporary database."""
    db_file = tmp_path / "test_store_performance.db"
    init_db(db_file)
    return db_file


def test_db_initialization(temp_db):
    """Test that all three tables are initialized correctly."""
    conn = sqlite3.connect(str(temp_db))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        assert "listing_performance_by_country" in tables
        assert "listing_performance_by_traffic_source" in tables
        assert "listing_performance_by_search_term" in tables
        assert "listing_impressions_by_country" in tables
    finally:
        conn.close()


def test_save_and_retrieve_impressions(temp_db):
    """Test real per-day impressions save/upsert and aggregate query."""
    pkg = "com.test.iosapp"

    save_impressions_performance(temp_db, "2026-06-01", pkg, "US", 1000)
    save_impressions_performance(temp_db, "2026-06-01", pkg, "IN", 500)
    assert get_total_impressions(temp_db, pkg, days=30) == 1500

    # Upsert overwrites rather than accumulating
    save_impressions_performance(temp_db, "2026-06-01", pkg, "US", 1200)
    assert get_total_impressions(temp_db, pkg, days=30) == 1700

    # No rows for an unknown package
    assert get_total_impressions(temp_db, "com.unknown.app", days=30) is None


def test_save_and_retrieve_country(temp_db):
    """Test country performance save/upsert and query."""
    pkg = "com.test.app"

    # Save first time
    save_country_performance(temp_db, "2026-06-01", pkg, "IN", 100, 10, 0.1)
    res = get_country_performance(temp_db, pkg)
    assert len(res) == 1
    assert res[0]["country"] == "IN"
    assert res[0]["visitors"] == 100
    assert res[0]["installs"] == 10
    assert res[0]["conversion_rate"] == 0.1

    # Save second time (upsert / overwrite)
    save_country_performance(temp_db, "2026-06-01", pkg, "IN", 150, 15, 0.1)
    res2 = get_country_performance(temp_db, pkg)
    assert len(res2) == 1
    assert res2[0]["visitors"] == 150
    assert res2[0]["installs"] == 15


def test_save_and_retrieve_traffic_and_search(temp_db):
    """Test traffic and search term metrics save and query."""
    pkg = "com.test.app"

    save_traffic_performance(temp_db, "2026-06-01", pkg, "Search", 200, 40, 0.2)
    save_search_performance(temp_db, "2026-06-01", pkg, "best app", 50, 5, 0.1)

    traffic_res = get_traffic_performance(temp_db, pkg)
    assert len(traffic_res) == 1
    assert traffic_res[0]["traffic_source"] == "Search"
    assert traffic_res[0]["visitors"] == 200
    assert traffic_res[0]["installs"] == 40

    search_res = get_search_performance(temp_db, pkg)
    assert len(search_res) == 1
    assert search_res[0]["search_term"] == "best app"
    assert search_res[0]["visitors"] == 50
    assert search_res[0]["installs"] == 5


def test_parse_csv_content_bom():
    """Test that CSV parsing handles UTF-16 BOM correctly."""
    csv_content = "\ufeffDate,Country,Store Listing Visitors,Store Listing Acquisitions\n2026-06-01,IN,100,20\n"
    rows = parse_csv_content(csv_content)
    assert len(rows) == 2
    assert rows[0] == ["Date", "Country", "Store Listing Visitors", "Store Listing Acquisitions"]
    assert rows[1] == ["2026-06-01", "IN", "100", "20"]


def test_ingest_csv_data_country(temp_db):
    """Test ingesting country CSV rows into database."""
    pkg = "com.test.app"
    csv_rows = [
        ["Date", "Country", "Store Listing Visitors", "Store Listing Acquisitions"],
        ["2026-06-01", "IN", "100", "20"],
        ["2026-06-01", "US", "50", "5"],
    ]

    count = ingest_csv_data(pkg, "country", csv_rows, temp_db)
    assert count == 2

    res = get_country_performance(temp_db, pkg)
    assert len(res) == 2
    # Verify IN conversion rate is 0.2
    in_record = next(r for r in res if r["country"] == "IN")
    assert in_record["visitors"] == 100
    assert in_record["installs"] == 20
    assert in_record["conversion_rate"] == 0.2


def test_ingest_validates_normalizes_dates_and_reports_only_persisted_coverage(temp_db):
    persisted_dates: set[str] = set()
    rows = [
        ["Date", "Country", "Store Listing Visitors", "Store Listing Acquisitions"],
        ["20260601", "IN", "100", "20"],
        ["not-a-date", "US", "50", "5"],
        ["2026-06-03", "GB", "not-a-number", "5"],
    ]

    count = ingest_csv_data(
        "com.test.app", "country", rows, temp_db, persisted_dates=persisted_dates
    )

    assert count == 1
    assert persisted_dates == {"2026-06-01"}
    stored = get_country_performance(temp_db, "com.test.app")
    assert [row["date"] for row in stored] == ["2026-06-01"]


def test_ingest_csv_data_traffic_source(temp_db):
    """Test ingesting traffic source and search term CSV rows into database."""
    pkg = "com.test.app"
    # Traffic source CSV with search terms if applicable
    csv_rows = [
        [
            "Date",
            "Traffic Source",
            "Search Term",
            "Store Listing Visitors",
            "Store Listing Acquisitions",
        ],
        ["2026-06-01", "Google Play search", "loan calc", "200", "40"],
        ["2026-06-01", "Explore", "", "300", "15"],
    ]

    count = ingest_csv_data(pkg, "traffic_source", csv_rows, temp_db)
    assert count == 2

    traffic_res = get_traffic_performance(temp_db, pkg)
    assert len(traffic_res) == 2

    search_res = get_search_performance(temp_db, pkg)
    assert len(search_res) == 1
    assert search_res[0]["search_term"] == "loan calc"
    assert search_res[0]["visitors"] == 200
    assert search_res[0]["installs"] == 40
    assert search_res[0]["conversion_rate"] == 0.2


def test_export_db_to_json(temp_db, tmp_path):
    """Test exporting SQLite database contents to JSON."""
    pkg = "com.test.app"
    export_file = tmp_path / "export.json"

    save_country_performance(temp_db, "2026-06-01", pkg, "IN", 100, 10, 0.1)
    save_traffic_performance(temp_db, "2026-06-01", pkg, "Search", 200, 20, 0.1)
    save_search_performance(temp_db, "2026-06-01", pkg, "best app", 50, 5, 0.1)

    export_db_to_json(pkg, temp_db, export_file)

    assert export_file.exists()
    with Path(export_file).open() as f:
        data = json.load(f)

    assert data["package_name"] == pkg
    assert len(data["country_performance"]) == 1
    assert data["country_performance"][0]["country"] == "IN"
    assert len(data["traffic_source_performance"]) == 1
    assert data["traffic_source_performance"][0]["traffic_source"] == "Search"
    assert len(data["search_term_performance"]) == 1
    assert data["search_term_performance"][0]["search_term"] == "best app"


def test_get_total_storefront_metrics(temp_db):
    """Test retrieving aggregated storefront metrics within a relative day range."""
    pkg = "com.test.app"

    # Save some records on different dates
    save_country_performance(temp_db, "2026-06-01", pkg, "IN", 100, 10, 0.1)
    save_country_performance(temp_db, "2026-06-01", pkg, "US", 50, 5, 0.1)
    save_country_performance(temp_db, "2026-06-05", pkg, "IN", 200, 20, 0.1)
    save_country_performance(temp_db, "2026-06-10", pkg, "US", 300, 30, 0.1)

    # Latest date is 2026-06-10. Range -30d starts from 2026-05-11. All records fall inside.
    res_30d = get_total_storefront_metrics(temp_db, pkg, 30)
    assert res_30d is not None
    assert res_30d["visitors"] == 650
    assert res_30d["installs"] == 65

    # Range -7d starts from 2026-06-03. Records on 2026-06-01 (150 visitors) fall outside.
    # Total within last 7 days should only include 2026-06-05 and 2026-06-10.
    res_7d = get_total_storefront_metrics(temp_db, pkg, 7)
    assert res_7d is not None
    assert res_7d["visitors"] == 500
    assert res_7d["installs"] == 50
