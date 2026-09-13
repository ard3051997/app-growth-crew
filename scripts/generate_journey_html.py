#!/usr/bin/env python3
import os
import sys
import json
import re
from pathlib import Path

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load dotenv if exists
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

import csv
import io
from funnel_engine_mcp.server import run_funnel_analysis

def fetch_gcs_play_stats(package_name):
    bucket = os.environ.get("GCS_PLAY_CONSOLE_BUCKET")
    if not bucket:
        print("GCS_PLAY_CONSOLE_BUCKET not set. Skipping GCS Play Stats fetch.")
        return None
        
    try:
        from gcs_mcp.client import GCSClient
        client = GCSClient()
        
        # List files to find the latest month's reports
        print("Fetching GCS file list...")
        blobs = client.list_blobs(bucket)
        
        # Filter for our package name
        store_blobs = [b for b in blobs if f"total_store_performance_{package_name}_" in b['name']]
        install_blobs = [b for b in blobs if f"installs_{package_name}_" in b['name']]
        
        if not store_blobs or not install_blobs:
            print(f"No GCS stats files found for package {package_name} in bucket {bucket}.")
            return None
            
        # Group traffic source blobs and find latest month
        traffic_blobs = [b for b in store_blobs if "traffic_source" in b['name']]
        country_blobs = [b for b in store_blobs if "country" in b['name']]
        overview_blobs = [b for b in install_blobs if "overview" in b['name']]
        
        if not traffic_blobs or not country_blobs or not overview_blobs:
            print("Missing some stats files (traffic source, country, or overview installs).")
            return None
            
        # Sort by name to get latest
        latest_traffic_blob = sorted(traffic_blobs, key=lambda x: x['name'])[-1]['name']
        m = re.search(r"_(\d{6})_traffic_source\.csv", latest_traffic_blob)
        if not m:
            print("Could not parse month from latest traffic source blob.")
            return None
        month_str = m.group(1)
        
        latest_country_blob = next((b['name'] for b in country_blobs if month_str in b['name']), None)
        latest_overview_blob = next((b['name'] for b in overview_blobs if month_str in b['name']), None)
        
        if not latest_country_blob or not latest_overview_blob:
            latest_country_blob = sorted(country_blobs, key=lambda x: x['name'])[-1]['name']
            latest_overview_blob = sorted(overview_blobs, key=lambda x: x['name'])[-1]['name']
            
        print(f"Latest Traffic Source Blob: {latest_traffic_blob}")
        print(f"Latest Country Blob: {latest_country_blob}")
        print(f"Latest Overview Installs Blob: {latest_overview_blob}")
        
        # Read content
        traffic_data = client.read_blob_content(bucket, latest_traffic_blob)
        country_data = client.read_blob_content(bucket, latest_country_blob)
        overview_data = client.read_blob_content(bucket, latest_overview_blob)
        
        # Parse traffic source CSV
        traffic_sources = {}
        f_traffic = io.StringIO(traffic_data)
        reader = csv.DictReader(f_traffic)
        for row in reader:
            source = row.get("Traffic source")
            acquisitions = int(row.get("Total store acquisitions", 0))
            if source:
                traffic_sources[source] = traffic_sources.get(source, 0) + acquisitions
                
        # Parse country CSV
        countries = {}
        f_country = io.StringIO(country_data)
        reader = csv.DictReader(f_country)
        for row in reader:
            country = row.get("Country / region")
            acquisitions = int(row.get("Total store acquisitions", 0))
            if country:
                countries[country] = countries.get(country, 0) + acquisitions
                
        # Parse overview CSV
        f_overview = io.StringIO(overview_data)
        reader = csv.DictReader(f_overview)
        total_installs = 0
        total_uninstalls = 0
        active_devices_list = []
        for row in reader:
            inst = row.get("Daily Device Installs") or row.get("Daily User Installs") or row.get("Install events", 0)
            uninst = row.get("Uninstall events") or row.get("Daily Device Uninstalls") or row.get("Daily User Uninstalls", 0)
            total_installs += int(inst) if inst else 0
            total_uninstalls += int(uninst) if uninst else 0
            active = row.get("Active Device Installs")
            if active:
                active_devices_list.append(int(active))
                
        avg_active = int(sum(active_devices_list) / len(active_devices_list)) if active_devices_list else 0
        
        return {
            "month": f"{month_str[:4]}-{month_str[4:]}",
            "traffic_sources": traffic_sources,
            "countries": sorted(countries.items(), key=lambda x: x[1], reverse=True)[:5],
            "installs_summary": {
                "total_installs": total_installs,
                "total_uninstalls": total_uninstalls,
                "avg_active_devices": avg_active
            }
        }
    except Exception as e:
        print(f"Error fetching/parsing GCS Play Stats: {e}")
        return None

def parse_markdown_tables(md_content):
    """
    Parses EVENTS.md to extract all Journey definitions, sub-sections, and tables.
    Returns a dictionary of journeys.
    """
    journeys = {}
    current_journey = None
    current_section = None
    lines = md_content.splitlines()
    
    table_headers = []
    table_rows = []
    in_table = False
    
    # Simple state machine to parse markdown
    for line in lines:
        line_stripped = line.strip()
        
        # Check for Journey Header
        m_j = re.match(r"^## JOURNEY (\d+):\s*(.*)", line_stripped)
        if m_j:
            # Save previous table if any
            if in_table and table_headers:
                save_table(journeys, current_journey, current_section, table_headers, table_rows)
                table_headers = []
                table_rows = []
                in_table = False
                
            j_id = int(m_j.group(1))
            j_title = m_j.group(2).strip()
            current_journey = j_id
            current_section = None
            journeys[j_id] = {
                "id": j_id,
                "title": j_title,
                "description": "",
                "sections": []
            }
            continue
            
        # Check for Subsection Header
        m_s = re.match(r"^###\s*(.*)", line_stripped)
        if m_s and current_journey is not None:
            if in_table and table_headers:
                save_table(journeys, current_journey, current_section, table_headers, table_rows)
                table_headers = []
                table_rows = []
                in_table = False
            current_section = m_s.group(1).strip()
            continue
            
        # Parse description text (if not in table and not a header)
        if current_journey is not None and not line_stripped.startswith("|") and line_stripped:
            if not current_section:
                # Add to journey description
                if journeys[current_journey]["description"]:
                    journeys[current_journey]["description"] += "\n" + line_stripped
                else:
                    journeys[current_journey]["description"] = line_stripped
            continue
            
        # Check for Table rows
        if line_stripped.startswith("|") and current_journey is not None:
            cells = [c.strip() for c in line_stripped.split("|")[1:-1]]
            
            # Skip separator line (e.g. |---|---|)
            if all(re.match(r"^:?-+:?$", cell) for cell in cells):
                continue
                
            if not in_table:
                # This is the header row
                table_headers = cells
                table_rows = []
                in_table = True
            else:
                table_rows.append(cells)
            continue
            
        # Empty line or non-table line ends table
        if not line_stripped.startswith("|") and in_table:
            save_table(journeys, current_journey, current_section, table_headers, table_rows)
            table_headers = []
            table_rows = []
            in_table = False
            
    # Save last table if remaining
    if in_table and table_headers:
        save_table(journeys, current_journey, current_section, table_headers, table_rows)
        
    return journeys

def save_table(journeys, j_id, section, headers, rows):
    """Save parsed table details into the journeys structure."""
    if j_id not in journeys:
        return
        
    # Convert rows to lists of dicts
    parsed_rows = []
    for row in rows:
        row_dict = {}
        # Handle cases where row might have fewer cells than headers
        for idx, header in enumerate(headers):
            if idx < len(row):
                row_dict[header] = row[idx]
            else:
                row_dict[header] = ""
        parsed_rows.append(row_dict)
        
    journeys[j_id]["sections"].append({
        "section_title": section or "Core Flow",
        "headers": headers,
        "rows": parsed_rows
    })

def main():
    """Thin CLI wrapper — delegates to journey_map_mcp.generator."""
    from journey_map_mcp.generator import generate_journey_map

    package_name = os.environ.get("APP_PACKAGE_NAME", "com.finance.loan.emicalculator")
    force = "--force" in sys.argv or "-f" in sys.argv

    print(f"Generating journey map for {package_name} (force_refresh={force})...")
    result = generate_journey_map(
        package_name=package_name,
        app_name="EMI Calculator Android",
        force_refresh=force,
    )
    print(f"Done! health_score={result['health_score']}, "
          f"journeys={result['journey_count']}, "
          f"revenue_impact=${result['total_revenue_impact']:.0f}/mo")
    print(f"Output: {result['output_path']}")

if __name__ == "__main__":
    main()
