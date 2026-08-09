#!/usr/bin/env python3
"""
Link Checker — Validates Google subscription activation links.
Uses Playwright with a persistent profile so you only need to log into Google once.

Usage:
  python3 scripts/check_links.py                     # Check all from extracted_links.csv
  python3 scripts/check_links.py --url "https://..."  # Check a single URL
  python3 scripts/check_links.py --login              # Just open browser to log in
"""
import asyncio
import argparse
import csv
import os
import sys
import time

PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "google_checker_profile")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
RESULTS_FILE = os.path.join(DATA_DIR, "link_check_results.csv")

# Keywords that indicate link status
VALID_INDICATORS = [
    "activate your plan",
    "accept and continue",
    "start your",
    "claim your",
    "get started",
    "activate plan",
    "confirm your",
    "redeem",
    "subscription included",
    "included with your plan",
    "google one",
]

USED_INDICATORS = [
    "already been redeemed",
    "already redeemed",
    "already been used",
    "already used",
    "already claimed",
    "already activated",
    "this link has expired",
    "expired",
    "no longer available",
    "not available",
    "code is invalid",
    "invalid",
    "something went wrong",
    "can't be redeemed",
    "cannot be redeemed",
]

LOGIN_INDICATORS = [
    "sign in",
    "sign-in",
    "accounts.google.com",
    "identifier",  # Google sign-in page has this
]


async def check_single_link(page, url, timeout=15):
    """Visit a link and determine its status. Returns (status, detail)."""
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        await asyncio.sleep(2)  # Let page render

        final_url = page.url

        # Get page text content
        try:
            body_text = await page.inner_text("body")
            body_text_lower = body_text.lower()
        except:
            body_text = ""
            body_text_lower = ""

        # Check for login page (not logged in)
        if "accounts.google.com" in final_url:
            return "NEEDS_LOGIN", "Redirected to Google sign-in page"

        # Check for used/expired indicators
        for indicator in USED_INDICATORS:
            if indicator in body_text_lower:
                return "USED", f"Found: '{indicator}'"

        # Check for valid/claimable indicators
        for indicator in VALID_INDICATORS:
            if indicator in body_text_lower:
                return "VALID", f"Found: '{indicator}'"

        # Check HTTP status
        if response and response.status >= 400:
            return "ERROR", f"HTTP {response.status}"

        # If we can't determine, save a snippet for manual review
        snippet = body_text[:200].strip().replace("\n", " ")
        return "UNKNOWN", f"Page loaded but status unclear. Snippet: {snippet}"

    except Exception as e:
        return "ERROR", str(e)[:100]


async def main():
    parser = argparse.ArgumentParser(description="Check if Google subscription links are valid or used")
    parser.add_argument("--url", help="Check a single URL")
    parser.add_argument("--login", action="store_true", help="Just open browser to log into Google")
    parser.add_argument("--file", default=os.path.join(DATA_DIR, "extracted_links.csv"), help="CSV file with links")
    parser.add_argument("--unchecked-only", action="store_true", default=True, help="Skip already-checked links")
    parser.add_argument("--delay", type=float, default=2, help="Delay between checks (seconds)")
    args = parser.parse_args()

    os.makedirs(PROFILE_DIR, exist_ok=True)

    from playwright.async_api import async_playwright

    print("🔍 Google Link Checker")
    print(f"   Profile: {PROFILE_DIR}")

    pw = await async_playwright().start()

    # Use persistent context so login persists
    context = await pw.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False,  # Need visible browser for initial login
        args=["--disable-blink-features=AutomationControlled"],
        viewport={"width": 1280, "height": 800},
    )

    page = context.pages[0] if context.pages else await context.new_page()

    # --- LOGIN MODE ---
    if args.login:
        print("\n📱 Opening Google sign-in...")
        print("   Log into your Google account, then close the browser when done.")
        print("   Your login will be saved for future checks.\n")
        await page.goto("https://accounts.google.com/")

        # Wait until user closes
        try:
            await page.wait_for_event("close", timeout=0)
        except:
            pass
        print("✅ Login saved! Run again without --login to check links.")
        await context.close()
        await pw.stop()
        return

    # --- Check if logged in ---
    print("   Checking Google login status...")
    await page.goto("https://myaccount.google.com/", wait_until="domcontentloaded", timeout=15000)
    await asyncio.sleep(2)

    if "accounts.google.com" in page.url:
        print("\n❌ Not logged into Google!")
        print("   Run: python3 scripts/check_links.py --login")
        print("   Log in, then try again.\n")
        await context.close()
        await pw.stop()
        return

    print("   ✅ Logged into Google!\n")

    # --- SINGLE URL MODE ---
    if args.url:
        print(f"🔗 Checking: {args.url[:80]}...")
        status, detail = await check_single_link(page, args.url)
        icon = {"VALID": "✅", "USED": "❌", "NEEDS_LOGIN": "🔒", "ERROR": "⚠️", "UNKNOWN": "❓"}.get(status, "?")
        print(f"   {icon} {status}: {detail}")
        await context.close()
        await pw.stop()
        return

    # --- BATCH MODE ---
    if not os.path.exists(args.file):
        print(f"❌ File not found: {args.file}")
        await context.close()
        await pw.stop()
        return

    # Load already-checked links
    checked_links = set()
    if args.unchecked_only and os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    checked_links.add(row[1])  # link column

    # Load links to check
    links_to_check = []
    with open(args.file, "r") as f:
        for row in csv.reader(f):
            if len(row) >= 4:
                phone = row[2]
                link = row[3]
                if link.startswith("http") and link not in checked_links:
                    links_to_check.append((phone, link))

    if not links_to_check:
        print("✅ All links already checked! (or no links found)")
        await context.close()
        await pw.stop()
        return

    print(f"📋 {len(links_to_check)} links to check ({len(checked_links)} already done)")
    print(f"   Results: {RESULTS_FILE}\n")

    stats = {"VALID": 0, "USED": 0, "ERROR": 0, "UNKNOWN": 0}

    sem = asyncio.Semaphore(5)
    done_count = 0
    total_count = len(links_to_check)

    async def process_link(phone, link):
        nonlocal done_count
        async with sem:
            worker_page = await context.new_page()
            status, detail = await check_single_link(worker_page, link)
            await worker_page.close()

            done_count += 1
            icon = {"VALID": "✅", "USED": "❌", "NEEDS_LOGIN": "🔒", "ERROR": "⚠️", "UNKNOWN": "❓"}.get(status, "?")
            print(f"[{done_count}/{total_count}] {phone}: {link[:60]}... {icon} {status}")

            stats[status] = stats.get(status, 0) + 1

            # Save result
            with open(RESULTS_FILE, "a", newline="") as f:
                csv.writer(f).writerow([phone, link, status, detail, time.strftime("%Y-%m-%d %H:%M:%S")])

            return status

    tasks = [asyncio.create_task(process_link(phone, link)) for phone, link in links_to_check]
    results = await asyncio.gather(*tasks)

    if "NEEDS_LOGIN" in results:
        print("\n🔒 Session expired! Log in again:")
        print("   python3 scripts/check_links.py --login\n")

    print(f"\n{'='*50}")
    print(f"📊 Results: ✅ {stats.get('VALID',0)} valid | ❌ {stats.get('USED',0)} used | ⚠️ {stats.get('ERROR',0)} errors | ❓ {stats.get('UNKNOWN',0)} unknown")
    print(f"   Saved to: {RESULTS_FILE}")

    await context.close()
    await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
