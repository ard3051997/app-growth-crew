#!/usr/bin/env python3
"""
Play Console Scraper: Robust CSL Navigation
Dev ID: 6540145348460836433
App ID: 4973265764915933466
"""

import sys
import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

DEV_ID = "6540145348460836433"
APP_ID = "4973265764915933466"
PACKAGE_NAME = "com.finance.loan.emicalculator"

async def main():
    print("🚀 Connecting to Chrome CDP port 9222...")
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

        csl_url = f"https://play.google.com/console/u/0/developers/{DEV_ID}/app/{APP_ID}/store-presence/custom-store-listings"
        print(f"🌐 Navigating to Custom Store Listings: {csl_url}")
        
        await page.goto(csl_url, wait_until="commit")
        print("Waiting 10 seconds for Angular/Dart app initialization...")
        await asyncio.sleep(10)

        # Force scroll to bottom to ensure dynamic lists render
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

        screenshot_path = output_dir / "csl_direct_page.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"📸 Screenshot saved to: {screenshot_path}")

        # Search for listing names / table content in page DOM
        page_title = await page.title()
        body_text = await page.locator("body").text_content()

        # Extract text snippets
        snippets = []
        if body_text:
            lines = [line.strip() for line in body_text.split("\n") if len(line.strip()) > 3]
            # Filter lines that mention India, Keywords, Custom, Main, Draft, Published
            for line in lines:
                if any(k in line for k in ["India", "Keywords", "Custom", "Main", "Draft", "Published", "Listing", "listing", "EMI"]):
                    snippets.append(line)

        report = {
            "package_name": PACKAGE_NAME,
            "url": page.url,
            "page_title": page_title,
            "screenshot": str(screenshot_path),
            "detected_snippets": snippets[:40],
            "contains_india": "India" in body_text,
            "contains_keywords": "Keywords" in body_text,
            "contains_published": "Published" in body_text,
            "contains_draft": "Draft" in body_text
        }

        report_file = output_dir / "csl_final_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"✅ Scraping complete! Output written to: {report_file}")

if __name__ == "__main__":
    asyncio.run(main())
