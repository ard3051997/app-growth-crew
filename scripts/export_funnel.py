#!/usr/bin/env python3
import os
import sys
import json
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

from funnel_engine_mcp.server import run_funnel_analysis

def main():
    package_name = os.environ.get("APP_PACKAGE_NAME", "com.finance.loan.emicalculator")
    print(f"Running funnel analysis for package: {package_name}...")
    try:
        data_str = run_funnel_analysis(package_name, app_category="finance", date_range="30d")
        data = json.loads(data_str)
        
        output_path = Path(__file__).parent / "funnel_data.json"
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Successfully exported funnel data to {output_path}")
    except Exception as e:
        print(f"Error running funnel analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
