#!/usr/bin/env python3
"""
Playwright Script: Smart Interactive Google Play Console Custom Store Listings (CSL) Scraper
App: com.finance.loan.emicalculator
"""

import sys
import json
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PACKAGE_NAME = "com.finance.loan.emicalculator"

async def scrape_csl(cdp_port: int = 9222):
    print("🚀 Initializing Playwright Play Console Scraper...")
    
    async with async_playwright() as p:
        print(f"🔗 Connecting to Chrome debug port {cdp_port}...")
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
            context = browser.contexts[0]
            
            # Use active page or create new
            if len(context.pages) > 0:
                page = context.pages[0]
            else:
                page = await context.new_page()
        except Exception as e:
            print(f"❌ Could not connect to Chrome port {cdp_port}: {e}")
            print("💡 Make sure Chrome was started with: --remote-debugging-port=9222")
            sys.exit(1)

        print("🌐 Navigating to Google Play Console App Dashboard...")
        await page.goto("https://play.google.com/console/u/0/developers", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Check if login / landing page
        if "console/about" in page.url or "accounts.google.com" in page.url:
            print("\n" + "="*70)
            print("⚠️ ACTION REQUIRED IN CHROME WINDOW:")
            print("Please log in to your Google Play Console account in the opened Chrome window.")
            print("The script will wait up to 180 seconds for you to log in...")
            print("="*70 + "\n")
            
            logged_in = False
            for i in range(180):
                await asyncio.sleep(1)
                curr_url = page.url
                if "developers/" in curr_url and "about" not in curr_url and "accounts.google.com" not in curr_url:
                    print("✅ Logged in successfully! Proceeding...")
                    logged_in = True
                    break
                if i % 15 == 0:
                    print(f"⏳ Waiting for login... ({180 - i}s remaining)")
            
            if not logged_in:
                print("❌ Login timeout reached. Please log in and re-run the script.")
                sys.exit(1)

        # We are logged in! Now navigate to developer apps
        print("🔍 Searching for app package:", PACKAGE_NAME)
        await asyncio.sleep(2)
        
        # Try navigating directly to app store listings or custom store listings page
        # Play Console URL structure for custom store listings:
        # https://play.google.com/console/u/0/developers/<dev_id>/app/<package>/store-presence/custom-store-listings
        
        print("📸 Capturing console homepage screenshot...")
        output_dir = Path("artifacts/play_console_csl")
        output_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(output_dir / "console_home.png"), full_page=True)

        # Extract all visible text / links to find the app URL
        links = page.locator("a[href*='app/']")
        link_count = await links.count()
        app_url = None
        
        for i in range(link_count):
            href = await links.nth(i).get_attribute("href")
            if href and (PACKAGE_NAME in href or "emicalculator" in href):
                app_url = href
                break
                
        if app_url:
            if not app_url.startswith("http"):
                app_url = "https://play.google.com/console/u/0" + (app_url if app_url.startswith("/") else "/" + app_url)
            print(f"🎯 Found app URL: {app_url}")
            await page.goto(app_url, wait_until="networkidle")
            await asyncio.sleep(3)

        # Now navigate to Custom Store Listings tab if available
        current_url = page.url
        print(f"📍 Current URL: {current_url}")
        
        # Attempt to find Custom store listings link in navigation menu
        csl_link = page.locator("text='Custom store listings'")
        if await csl_link.count() > 0:
            print("👉 Clicking 'Custom store listings' menu item...")
            await csl_link.first.click()
            await asyncio.sleep(4)

        # Capture final CSL screenshot
        csl_screenshot = output_dir / "csl_listings_page.png"
        await page.screenshot(path=str(csl_screenshot), full_page=True)
        print(f"📸 Custom Store Listings screenshot saved to: {csl_screenshot}")

        # Extract text / listing details from page
        body_text = await page.locator("body").text_content()
        
        csl_found = []
        if "India" in body_text:
            csl_found.append("Mentions 'India'")
        if "Keywords" in body_text:
            csl_found.append("Mentions 'Keywords'")
        if "Published" in body_text:
            csl_found.append("Mentions 'Published'")
        if "Draft" in body_text:
            csl_found.append("Mentions 'Draft'")

        report = {
            "package_name": PACKAGE_NAME,
            "url": page.url,
            "page_title": await page.title(),
            "detected_keywords": csl_found,
            "screenshot": str(csl_screenshot)
        }

        report_file = output_dir / "csl_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print("\n" + "="*70)
        print(f"🎉 SCRAPING COMPLETED! Report saved to: {report_file}")
        print(f"🖼️ Screenshot saved to: {csl_screenshot}")
        print("="*70 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Play Console Custom Store Listings Scraper")
    parser.add_argument("--cdp", type=int, default=9222, help="CDP port (default: 9222)")
    args = parser.parse_args()

    asyncio.run(scrape_csl(cdp_port=args.cdp))
