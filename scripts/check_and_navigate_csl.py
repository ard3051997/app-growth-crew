#!/usr/bin/env python3
"""
Play Console Scraper: App Store Presence & Custom Store Listings
Dev ID: 6540145348460836433
App Package: com.finance.loan.emicalculator
"""

import sys
import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

DEV_ID = "6540145348460836433"
PACKAGE_NAME = "com.finance.loan.emicalculator"

async def main():
    print("🚀 Connecting to running Chrome on port 9222...")
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0] if len(context.pages) > 0 else await context.new_page()
        except Exception as e:
            print(f"❌ Error connecting to CDP: {e}")
            sys.exit(1)

        output_dir = Path("artifacts/play_console_csl")
        output_dir.mkdir(parents=True, exist_ok=True)

        print("🌐 Navigating to App List page...")
        await page.goto(f"https://play.google.com/console/u/0/developers/{DEV_ID}/app-list", wait_until="networkidle")
        await asyncio.sleep(4)

        print("🔍 Locating EMI Calculator row...")
        emi_row = page.locator("text='com.finance.loan.emicalculator'")
        if await emi_row.count() > 0:
            print("👉 Clicking EMI Calculator row...")
            await emi_row.first.click()
            await asyncio.sleep(5)

        app_url = page.url
        print(f"📍 App Dashboard URL: {app_url}")

        # Construct or find Custom store listings link
        # Path format: /developers/{DEV_ID}/app/{APP_INTERNAL_ID}/store-presence/custom-store-listings
        if "/app/" in app_url:
            internal_app_id = app_url.split("/app/")[1].split("/")[0]
            print(f"🆔 Internal App ID extracted: {internal_app_id}")
            
            csl_target_url = f"https://play.google.com/console/u/0/developers/{DEV_ID}/app/{internal_app_id}/store-presence/custom-store-listings"
            print(f"🌐 Navigating to Custom Store Listings URL: {csl_target_url}")
            await page.goto(csl_target_url, wait_until="networkidle")
            await asyncio.sleep(5)

        csl_screenshot = output_dir / "emi_custom_store_listings.png"
        await page.screenshot(path=str(csl_screenshot), full_page=True)
        print(f"📸 Screenshot saved to: {csl_screenshot}")

        # Extract text content
        body_text = await page.locator("body").text_content()

        # Find table / cards on CSL page
        csl_items = []
        csl_cards = page.locator("tr, div[data-test-id], div[role='row']")
        count = await csl_cards.count()
        print(f"Found {count} candidate rows/cards on CSL page.")

        for i in range(count):
            try:
                txt = await csl_cards.nth(i).text_content()
                if txt and len(txt.strip()) > 0:
                    cleaned = " ".join(txt.split())
                    csl_items.append(cleaned)
            except Exception:
                pass

        report = {
            "package_name": PACKAGE_NAME,
            "csl_url": page.url,
            "page_title": await page.title(),
            "csl_screenshot": str(csl_screenshot),
            "csl_items": csl_items[:25],
            "has_india": "India" in body_text,
            "has_keywords": "Keywords" in body_text,
            "body_snippet": body_text[:3000] if body_text else ""
        }

        report_json = output_dir / "csl_scraped_data.json"
        with open(report_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"✅ Scraping completed! Output saved to: {report_json}")

if __name__ == "__main__":
    asyncio.run(main())
