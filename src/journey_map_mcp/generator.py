"""Journey Map generation logic — extracted from scripts/generate_journey_html.py.

Handles EVENTS.md parsing, GCS Play Console stats fetching, and HTML generation.
The scripts/generate_journey_html.py script is kept as a thin CLI wrapper around this.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path
from typing import Any

# Default template path relative to repo root
_DEFAULT_TEMPLATE = Path(__file__).parent.parent.parent / "scripts" / "journey_map_template.html"
_DEFAULT_EVENTS_MD = Path(__file__).parent.parent.parent / "docs" / "EVENTS.md"
if not _DEFAULT_EVENTS_MD.exists():
    _DEFAULT_EVENTS_MD = Path(__file__).parent.parent.parent / "EVENTS.md"
_DEFAULT_OUTPUT = Path(__file__).parent.parent.parent / "journey_map.html"


# ---------------------------------------------------------------------------
# EVENTS.md parser
# ---------------------------------------------------------------------------


def _save_table(
    journeys: dict[int, Any],
    j_id: int | None,
    section: str | None,
    headers: list[str],
    rows: list[list[str]],
) -> None:
    if j_id is None or j_id not in journeys:
        return
    parsed_rows = []
    for row in rows:
        row_dict: dict[str, str] = {}
        for idx, header in enumerate(headers):
            row_dict[header] = row[idx] if idx < len(row) else ""
        parsed_rows.append(row_dict)
    journeys[j_id]["sections"].append(
        {
            "section_title": section or "Core Flow",
            "headers": headers,
            "rows": parsed_rows,
        }
    )


def parse_events_md(events_md_path: str | Path | None = None) -> dict[int, Any]:
    """Parse EVENTS.md and return a dict of journey definitions.

    Returns:
        Dict keyed by journey number (1-based int). Each value contains:
        ``id``, ``title``, ``description``, and ``sections`` (list of table blocks).
    """
    path = Path(events_md_path) if events_md_path else _DEFAULT_EVENTS_MD
    content = path.read_text(encoding="utf-8")

    journeys: dict[int, Any] = {}
    current_journey: int | None = None
    current_section: str | None = None
    table_headers: list[str] = []
    table_rows: list[list[str]] = []
    in_table = False

    for raw_line in content.splitlines():
        line = raw_line.strip()

        m_j = re.match(r"^## JOURNEY (\d+):\s*(.*)", line)
        if m_j:
            if in_table and table_headers:
                _save_table(journeys, current_journey, current_section, table_headers, table_rows)
                table_headers, table_rows, in_table = [], [], False
            current_journey = int(m_j.group(1))
            current_section = None
            journeys[current_journey] = {
                "id": current_journey,
                "title": m_j.group(2).strip(),
                "description": "",
                "sections": [],
            }
            continue

        m_s = re.match(r"^###\s*(.*)", line)
        if m_s and current_journey is not None:
            if in_table and table_headers:
                _save_table(journeys, current_journey, current_section, table_headers, table_rows)
                table_headers, table_rows, in_table = [], [], False
            current_section = m_s.group(1).strip()
            continue

        if current_journey is not None and not line.startswith("|") and line:
            if not current_section:
                sep = "\n" if journeys[current_journey]["description"] else ""
                journeys[current_journey]["description"] += sep + line
            continue

        if line.startswith("|") and current_journey is not None:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if all(re.match(r"^:?-+:?$", c) for c in cells):
                continue
            if not in_table:
                table_headers = cells
                table_rows = []
                in_table = True
            else:
                table_rows.append(cells)
            continue

        if not line.startswith("|") and in_table:
            _save_table(journeys, current_journey, current_section, table_headers, table_rows)
            table_headers, table_rows, in_table = [], [], False

    if in_table and table_headers:
        _save_table(journeys, current_journey, current_section, table_headers, table_rows)

    return journeys


def get_journey_structure(events_md_path: str | Path | None = None) -> dict[str, Any]:
    """Return a lightweight summary of EVENTS.md without running any API calls.

    Returns:
        Dict with ``journey_count``, ``journey_titles``, ``total_sections``,
        ``ga4_events`` (unique event names found in tables), and ``source_files``.
    """
    journeys = parse_events_md(events_md_path)

    ga4_events: set[str] = set()
    source_files: set[str] = set()
    total_sections = 0

    for j in journeys.values():
        for sec in j["sections"]:
            total_sections += 1
            for row in sec["rows"]:
                event = row.get("Event", "")
                if event and not event.startswith("*") and event != "—":
                    # Strip markdown formatting
                    clean = re.sub(r"[`*_]", "", event).strip()
                    if clean:
                        ga4_events.add(clean)
                for val in row.values():
                    m = re.search(r"\[([^\]]+\.(?:kt|java))\]", val)
                    if m:
                        source_files.add(m.group(1))

    return {
        "journey_count": len(journeys),
        "journey_titles": {j["id"]: j["title"] for j in journeys.values()},
        "total_sections": total_sections,
        "ga4_events": sorted(ga4_events),
        "source_files": sorted(source_files),
    }


# ---------------------------------------------------------------------------
# GCS Play Console stats
# ---------------------------------------------------------------------------


def fetch_gcs_play_stats(package_name: str) -> dict[str, Any] | None:
    """Fetch Play Console stats from GCS. Returns None if bucket not configured."""
    bucket = os.environ.get("GCS_PLAY_CONSOLE_BUCKET")
    if not bucket:
        return None
    try:
        from datetime import date

        from gcs_mcp.client import GCSClient

        client = GCSClient()

        # Use prefix-filtered listing — much faster than listing all 19k blobs
        store_blobs = client.list_blobs(bucket, prefix="stats/store_performance/")
        install_blobs = client.list_blobs(bucket, prefix="stats/installs/")

        # Filter for this package
        traffic_blobs = [
            b
            for b in store_blobs
            if f"total_store_performance_{package_name}_" in b["name"]
            and "traffic_source" in b["name"]
        ]
        country_blobs = [
            b
            for b in store_blobs
            if f"total_store_performance_{package_name}_" in b["name"] and "country" in b["name"]
        ]
        overview_blobs = [
            b
            for b in install_blobs
            if f"installs_{package_name}_" in b["name"] and "overview" in b["name"]
        ]

        if not traffic_blobs or not overview_blobs:
            return None

        # Pick the last COMPLETE month (skip current partial month)
        current_ym = date.today().strftime("%Y%m")

        def _month_of(blob_name: str) -> str:
            m = re.search(r"_(\d{6})_", blob_name)
            return m.group(1) if m else ""

        complete_traffic = sorted(
            [b for b in traffic_blobs if _month_of(b["name"]) < current_ym],
            key=lambda b: _month_of(b["name"]),
        )
        if not complete_traffic:
            complete_traffic = sorted(traffic_blobs, key=lambda b: _month_of(b["name"]))

        latest_traffic = complete_traffic[-1]["name"]
        month_str = _month_of(latest_traffic)

        latest_country = next(
            (
                b["name"]
                for b in sorted(country_blobs, key=lambda b: _month_of(b["name"]))
                if _month_of(b["name"]) == month_str
            ),
            sorted(country_blobs, key=lambda b: _month_of(b["name"]))[-1]["name"]
            if country_blobs
            else None,
        )
        latest_overview = next(
            (
                b["name"]
                for b in sorted(overview_blobs, key=lambda b: _month_of(b["name"]))
                if _month_of(b["name"]) == month_str
            ),
            sorted(overview_blobs, key=lambda b: _month_of(b["name"]))[-1]["name"]
            if overview_blobs
            else None,
        )

        traffic_data = client.read_blob_content(bucket, latest_traffic)
        country_data = client.read_blob_content(bucket, latest_country) if latest_country else ""
        overview_data = client.read_blob_content(bucket, latest_overview) if latest_overview else ""

        # Parse traffic sources
        traffic_sources: dict[str, int] = {}
        for row in csv.DictReader(io.StringIO(traffic_data)):
            src = row.get("Traffic source", "")
            acq = int(row.get("Total store acquisitions", 0) or 0)
            if src:
                traffic_sources[src] = traffic_sources.get(src, 0) + acq

        # Compute organic vs paid breakdown
        ORGANIC_SOURCES = {"Google Play explore", "Google Play search", "Google Play Browse"}
        organic_acq = sum(v for k, v in traffic_sources.items() if k in ORGANIC_SOURCES)
        paid_acq = traffic_sources.get("Ads and referrals", 0)
        total_acq = sum(traffic_sources.values())
        organic_pct = round(organic_acq / total_acq * 100, 1) if total_acq > 0 else 0.0

        # Parse countries
        countries: dict[str, int] = {}
        if country_data:
            for row in csv.DictReader(io.StringIO(country_data)):
                country = row.get("Country / region", "")
                acq = int(row.get("Total store acquisitions", 0) or 0)
                if country:
                    countries[country] = countries.get(country, 0) + acq

        # Parse overview installs
        total_installs = total_uninstalls = 0
        active_list: list[int] = []
        if overview_data:
            for row in csv.DictReader(io.StringIO(overview_data)):
                inst = (
                    row.get("Daily Device Installs")
                    or row.get("Daily User Installs")
                    or row.get("Install events")
                    or 0
                )
                uninst = (
                    row.get("Uninstall events")
                    or row.get("Daily Device Uninstalls")
                    or row.get("Daily User Uninstalls")
                    or 0
                )
                total_installs += int(inst) if inst else 0
                total_uninstalls += int(uninst) if uninst else 0
                active = row.get("Active Device Installs")
                if active:
                    active_list.append(int(active))

        return {
            "month": f"{month_str[:4]}-{month_str[4:]}",
            "traffic_sources": traffic_sources,
            "total_acquisitions": total_acq,
            "organic_acquisitions": organic_acq,
            "paid_acquisitions": paid_acq,
            "organic_pct": organic_pct,
            "countries": sorted(countries.items(), key=lambda x: x[1], reverse=True)[:5],
            "installs_summary": {
                "total_installs": total_installs,
                "total_uninstalls": total_uninstalls,
                "avg_active_devices": int(sum(active_list) / len(active_list))
                if active_list
                else 0,
            },
        }
    except Exception:
        import traceback

        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Full generation pipeline
# ---------------------------------------------------------------------------


def generate_journey_map(
    package_name: str,
    events_md_path: str | Path | None = None,
    output_path: str | Path | None = None,
    date_range_days: int = 30,
    template_path: str | Path | None = None,
    app_name: str | None = None,
    force_refresh: bool = False,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full journey map generation pipeline.

    Steps:
    1. Load (or fetch) funnel analysis for ``date_range_days`` and 7d.
    2. Parse EVENTS.md.
    3. Fetch GCS Play Console stats.
    4. Inject all data into the HTML template.
    5. Write output HTML.

    Returns:
        Summary dict: ``output_path``, ``journey_count``, ``health_score``,
        ``total_revenue_impact``, ``gcs_stats_available``.
    """
    from funnel_engine_mcp.server import run_funnel_analysis

    resolved_cache = (
        Path(cache_dir) if cache_dir else Path(__file__).parent.parent.parent / "scripts"
    )
    resolved_output = Path(output_path) if output_path else _DEFAULT_OUTPUT
    resolved_template = Path(template_path) if template_path else _DEFAULT_TEMPLATE
    resolved_events = Path(events_md_path) if events_md_path else _DEFAULT_EVENTS_MD

    if not resolved_template.exists():
        raise FileNotFoundError(f"Template not found: {resolved_template}")
    if not resolved_events.exists():
        raise FileNotFoundError(f"EVENTS.md not found: {resolved_events}")

    # --- 1. Funnel data ---
    cache_30d = resolved_cache / "funnel_data_30d.json"
    cache_7d = resolved_cache / "funnel_data_7d.json"
    date_key = f"{date_range_days}d"

    if not force_refresh and cache_30d.exists():
        data_30d = json.loads(cache_30d.read_text())
    else:
        data_30d = json.loads(
            run_funnel_analysis(package_name, app_category="finance", date_range=date_key)
        )
        cache_30d.write_text(json.dumps(data_30d, indent=2))

    if not force_refresh and cache_7d.exists():
        data_7d = json.loads(cache_7d.read_text())
    else:
        data_7d = json.loads(
            run_funnel_analysis(package_name, app_category="finance", date_range="7d")
        )
        cache_7d.write_text(json.dumps(data_7d, indent=2))

    # --- 2. Parse EVENTS.md ---
    journeys = parse_events_md(resolved_events)

    # --- 3. GCS stats ---
    gcs_stats = fetch_gcs_play_stats(package_name)

    # --- 4. Build master data ---
    master_data: dict[str, Any] = {
        "package_name": package_name,
        "app_name": app_name or package_name.split(".")[-1].replace("_", " ").title(),
        "aso_score": 84,
        "funnel_data_30d": data_30d,
        "funnel_data_7d": data_7d,
        "journeys": journeys,
        "play_store_gcs_data": gcs_stats,
    }

    # --- 5. Render HTML ---
    template_content = resolved_template.read_text(encoding="utf-8")
    html_content = template_content.replace("__MASTER_DATA__", json.dumps(master_data, indent=2))
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(html_content, encoding="utf-8")

    health_score = data_30d.get("funnel_health_score", data_30d.get("health_score", "N/A"))
    revenue_impact = data_30d.get("total_monthly_revenue_impact", 0)

    return {
        "output_path": str(resolved_output),
        "journey_count": len(journeys),
        "health_score": health_score,
        "total_revenue_impact": revenue_impact,
        "gcs_stats_available": gcs_stats is not None,
    }
