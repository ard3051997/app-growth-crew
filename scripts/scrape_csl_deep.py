#!/usr/bin/env python3
"""
Deep Play Console Custom Store Listings Scraper
Target App: com.finance.loan.emicalculator
"""

import sys
import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

DEV_ID = "6540145348460836433"
APP_ID = "4973265764915933466"
PACKAGE_NAME = "com.finance.loan.emicalculator"

CSL_URL = f"https://play.google.com/console/u/0/developers/{DEV_ID}/app/{APP_ID}/store-presence/custom-store-listings"

async def main():
    print("🚀 Connecting to running Chrome on port 9222...")
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0] if len(context.pages) > 0 else await context.new_page()
        except Exception as e:
            print(f"❌ Connection error: {e}")
            sys.exit(1)

        output_dir = Path("artifacts/play_console_csl")
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"🌐 Navigating to CSL URL: {CSL_URL}")
        await page.goto(CSL_URL)
        print("⏳ Waiting 15 seconds for Play Console Dart UI to render...")
        await asyncio.sleep(15)

        # Capture screenshot
        screenshot_path = output_dir / "csl_deep_view.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"📸 Saved full screenshot to: {screenshot_path}")

        # Scrape all visible text elements
        text_content = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('body *'))
                .map(el => el.innerText)
                .filter(txt => txt && txt.trim().length > 0 && txt.length < 500);
        }""")

        # Filter lines that mention custom listing names, status, target countries
        relevant_items = []
        for txt in text_content:
            clean = " ".join(txt.split())
            if any(term in clean for term in ["India", "Keywords", "Custom", "Main", "Default", "Published", "Draft", "Unpublished", "Targeting", "Audience", "listing"]):
                if clean not in relevant_items:
                    relevant_items.append(clean)

        report = {
            "package_name": PACKAGE_NAME,
            "url": page.url,
            "title": await page.title(),
            "screenshot": str(screenshot_path),
            "relevant_ui_elements": relevant_items[:50]
        }

        report_file = output_dir / "csl_deep_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"✅ Report saved to: {report_file}")

if __name__ == "__main__":
    asyncio.run(main())
