#!/usr/bin/env python3
"""
Play Console DOM Scraper for Custom Store Listings
Target App: com.finance.loan.emicalculator
"""

import sys
import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PACKAGE_NAME = "com.finance.loan.emicalculator"

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

        print("🌐 Opening Play Console homepage...")
        await page.goto("https://play.google.com/console/u/0/developers/6540145348460836433/app-list", wait_until="networkidle")
        await asyncio.sleep(3)

        print("🔍 Searching for EMI Calculator app row...")
        # Find exact row containing package name
        row_locator = page.locator(f"tr:has-text('{PACKAGE_NAME}'), div:has-text('{PACKAGE_NAME}')")
        
        if await row_locator.count() > 0:
            print("Found app row, clicking View app link...")
            view_app_link = row_locator.locator("a, button, span:has-text('View app')").first
            if await view_app_link.count() > 0:
                await view_app_link.click()
            else:
                await row_locator.first.click()
            await asyncio.sleep(5)

        print(f"📍 Current URL: {page.url}")
        await page.screenshot(path=str(output_dir / "step1_dashboard.png"), full_page=True)

        # Expand Store presence menu if present
        print("🔍 Looking for 'Store presence' in navigation...")
        store_presence = page.locator("text='Store presence'")
        if await store_presence.count() > 0:
            await store_presence.first.click()
            await asyncio.sleep(2)

        # Click Custom store listings
        print("🔍 Looking for 'Custom store listings' menu item...")
        csl_menu = page.locator("text='Custom store listings'")
        if await csl_menu.count() > 0:
            await csl_menu.first.click()
            await asyncio.sleep(5)

        print(f"📍 Final CSL URL: {page.url}")
        screenshot_final = output_dir / "csl_findings_final.png"
        await page.screenshot(path=str(screenshot_final), full_page=True)
        print(f"📸 Screenshot saved to: {screenshot_final}")

        # Extract text snippets
        body_text = await page.locator("body").text_content()
        lines = [l.strip() for l in body_text.split("\n") if len(l.strip()) > 0]
        
        csl_details = []
        for l in lines:
            if any(term in l for term in ["India", "Keywords", "Custom", "Published", "Draft", "Targeting", "Audience", "Main"]):
                if l not in csl_details:
                    csl_details.append(l)

        report = {
            "package_name": PACKAGE_NAME,
            "url": page.url,
            "title": await page.title(),
            "screenshot": str(screenshot_final),
            "detected_snippets": csl_details[:30]
        }

        report_file = output_dir / "csl_ui_scraped.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"✅ Scraping complete! Output written to: {report_file}")

if __name__ == "__main__":
    asyncio.run(main())
