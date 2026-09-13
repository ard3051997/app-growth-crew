#!/usr/bin/env python3
"""
UI Navigation Scraper for Play Console Custom Store Listings
App: com.finance.loan.emicalculator
"""

import sys
import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PACKAGE_NAME = "com.finance.loan.emicalculator"
DEV_ID = "6540145348460836433"

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

        print(f"🌐 Step 1: Navigating to App List: https://play.google.com/console/u/0/developers/{DEV_ID}/app-list")
        await page.goto(f"https://play.google.com/console/u/0/developers/{DEV_ID}/app-list", wait_until="networkidle")
        await asyncio.sleep(4)

        print("🔍 Step 2: Clicking EMI Calculator app link...")
        # Search for EMI Calculator row or link
        app_link = page.locator(f"tr:has-text('{PACKAGE_NAME}'), div:has-text('{PACKAGE_NAME}'), a:has-text('EMI Calculator')").first
        if await app_link.count() > 0:
            print("Found app row link, clicking...")
            await app_link.click()
            await asyncio.sleep(6)

        print(f"📍 Current URL after app click: {page.url}")
        await page.screenshot(path=str(output_dir / "step2_dashboard.png"), full_page=True)

        print("🔍 Step 3: Expanding 'Store presence' in navigation...")
        # Play Console left nav menu: click 'Store presence'
        store_presence_btn = page.locator("text='Store presence'").first
        if await store_presence_btn.count() > 0:
            print("Clicking Store presence menu item...")
            try:
                await store_presence_btn.click(force=True)
                await asyncio.sleep(3)
            except Exception as ex:
                print(f"Click warning: {ex}")

        print("🔍 Step 4: Clicking 'Custom store listings'...")
        csl_btn = page.locator("text='Custom store listings'").first
        if await csl_btn.count() > 0:
            print("Clicking Custom store listings menu item...")
            try:
                await csl_btn.click(force=True)
                await asyncio.sleep(6)
            except Exception as ex:
                print(f"Click warning: {ex}")

        csl_final_screenshot = output_dir / "csl_ui_final.png"
        await page.screenshot(path=str(csl_final_screenshot), full_page=True)
        print(f"📸 Saved final CSL UI screenshot to: {csl_final_screenshot}")

        body_text = await page.locator("body").text_content()

        # Extract structured text lines
        lines = [line.strip() for line in body_text.split("\n") if len(line.strip()) > 0]
        
        csl_matches = []
        for line in lines:
            if any(term in line for term in ["India", "Keywords", "Custom", "Main", "Default", "Published", "Draft", "Unpublished", "listing", "Listing"]):
                csl_matches.append(line)

        report = {
            "package_name": PACKAGE_NAME,
            "final_url": page.url,
            "page_title": await page.title(),
            "screenshot": str(csl_final_screenshot),
            "csl_matches": csl_matches[:40],
            "body_snippet": body_text[:3000] if body_text else ""
        }

        report_file = output_dir / "csl_ui_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"✅ Scraping complete! Output written to: {report_file}")

if __name__ == "__main__":
    asyncio.run(main())
