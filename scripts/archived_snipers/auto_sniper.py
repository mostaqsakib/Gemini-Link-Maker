#!/usr/bin/env python3
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
"""
Auto Sniper - Omni-Sniper + Playwright Web Automation
Snipes Jio numbers from multiple providers, then opens browser sessions
to automatically log into jio.com/selfcare with the OTPs.
"""
import asyncio
import aiohttp
import argparse
import re
import csv
import os
import shutil

# ─── Configuration ───────────────────────────────────────────────────────────
PROVIDERS = {
    "UOTP": {
        "url": "https://uotp.store/api/stubs/handler_api.php",
        "key": "qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU",
        "service": "jio", "country": "22", "delay": 2
    },
    "Grizzly": {
        "url": "https://api.grizzlysms.com/stubs/handler_api.php",
        "key": "c59504cdd271fe4a967257bba4b37ab6",
        "service": "jio", "country": "22", "delay": 3
    },
    "Tiger": {
        "url": "https://api.tiger-sms.com/stubs/handler_api.php",
        "key": "Ke24YmEU9RVCz5IGaQdvnhygEOJjBio6",
        "service": "mjo", "country": "22", "delay": 5
    },
    "MeowSMS": {
        "url": "https://meowsms.shop/stubs/handler_api.php",
        "key": "kO3gixH4F91AvJUC54wVHUlRIUg5X7V5",
        "service": "myjio", "country": "22", "delay": 3
    }
}

UOTP_SERVERS = ["5", "3", "4", "2", "1", "8"]

OMKAR_API_KEYS = [k.strip() for k in os.environ.get("OMKAR_API_KEYS", "").split(",") if k.strip()]
current_api_index = 0

BATCH_SIZE = 5
JIO_LOGIN_URL = "https://www.jio.com/selfcare/login/"
PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

# ─── Helpers & Analytics ─────────────────────────────────────────────────────
class C:
    RST = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
    GRN = "\033[92m"; RED = "\033[91m"; YEL = "\033[93m"
    CYN = "\033[96m"; MAG = "\033[95m"; BLU = "\033[94m"

class Analytics:
    def __init__(self):
        self.stats = {p: {"fetched": 0, "jio": 0, "otp": 0, "login": 0} for p in PROVIDERS}
        self.csv_file = "sniper_stats.csv"
        self.total_accounts = 0
        self._init_csv()

    def _init_csv(self):
        with open(self.csv_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Provider", "Fetched", "Jio", "OTP", "Logins", "Jio%", "OTP%"])

    def record(self, provider, metric):
        self.stats[provider][metric] += 1
        if metric == "login":
            self.total_accounts += 1
        self._write_csv()

    def _write_csv(self):
        with open(self.csv_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Provider", "Fetched", "Jio", "OTP", "Logins", "Jio%", "OTP%"])
            for p, s in self.stats.items():
                jio_rate = f"{(s['jio']/s['fetched']*100):.1f}%" if s['fetched'] > 0 else "0%"
                otp_rate = f"{(s['otp']/s['jio']*100):.1f}%" if s['jio'] > 0 else "0%"
                w.writerow([p, s['fetched'], s['jio'], s['otp'], s['login'], jio_rate, otp_rate])

    def print_dashboard(self):
        print(f"\n{C.B}📊 AUTO-SNIPER ANALYTICS 📊{C.RST}")
        print(f"{C.CYN}{C.B}🎯 TOTAL COMPLETED LOGINS: {self.total_accounts}{C.RST}")
        print(f"{'Provider':<10} | {'Fetched':<7} | {'Jio':<5} | {'OTPs':<4} | {'Logins':<6} | {'Jio %':<7} | {'OTP %':<7}")
        print("-" * 65)
        for p, s in self.stats.items():
            jio_rate = f"{(s['jio']/s['fetched']*100):.1f}%" if s['fetched'] > 0 else "0%"
            otp_rate = f"{(s['otp']/s['jio']*100):.1f}%" if s['jio'] > 0 else "0%"
            print(f"{C.CYN}{p:<10}{C.RST} | {s['fetched']:<7} | {C.GRN}{s['jio']:<5}{C.RST} | {C.MAG}{s['otp']:<4}{C.RST} | {C.BLU}{s['login']:<6}{C.RST} | {C.YEL}{jio_rate:<7}{C.RST} | {C.BLU}{otp_rate:<7}{C.RST}")
        print("-" * 65 + "\n")

tracker = Analytics()

# ─── Universal API Functions ─────────────────────────────────────────────────
async def get_carrier(session, number_str):
    global current_api_index
    if not number_str.startswith('+'): number_str = '+' + number_str
    url = "https://carrier-lookup-api.omkar.cloud/lookup"
    
    for _ in range(len(OMKAR_API_KEYS)):
        current_key = OMKAR_API_KEYS[current_api_index]
        try:
            async with session.get(url, params={"phone": number_str}, headers={"API-Key": current_key}) as resp:
                if resp.status in [429, 400]:
                    data = await resp.json()
                    if "exceeded" in data.get("message", "").lower():
                        print(f"  {C.YEL}[MNP] API Key {current_api_index+1} exhausted. Switching...{C.RST}")
                        current_api_index = (current_api_index + 1) % len(OMKAR_API_KEYS)
                        continue
                if resp.status == 200:
                    return (await resp.json()).get("carrier", "Unknown")
        except: pass
    return "Unknown"

async def buy_number(session, p_name):
    cfg = PROVIDERS[p_name]
    params = {"action": "getNumber", "api_key": cfg["key"], "service": cfg["service"], "country": cfg["country"]}
    servers_to_try = UOTP_SERVERS if p_name == "UOTP" else [None]
    
    for srv in servers_to_try:
        if srv: params["operator"] = srv
        try:
            async with session.get(cfg["url"], params=params) as resp:
                text = (await resp.text()).strip()
                if text.startswith("ACCESS_NUMBER:"):
                    parts = text.split(":")
                    return {"status": "success", "aid": parts[1], "phone": parts[2], "provider": p_name}
        except: pass
    return {"status": "error"}

async def get_otp_status(session, p_name, aid):
    cfg = PROVIDERS[p_name]
    try:
        async with session.get(cfg["url"], params={"action": "getStatus", "api_key": cfg["key"], "id": aid}) as resp:
            return (await resp.text()).strip()
    except Exception as e: return f"ERROR: {e}"

async def cancel_number(session, p_name, aid):
    cfg = PROVIDERS[p_name]
    try:
        async with session.get(cfg["url"], params={"action": "setStatus", "api_key": cfg["key"], "status": "8", "id": aid}) as resp:
            return (await resp.text()).strip()
    except Exception as e: return f"ERROR: {e}"

async def cancel_with_retry(session, p_name, aid, phone):
    """Cancel a number with 120s wait and retry for EARLY_CANCEL_DENIED."""
    print(f"  {C.DIM}[{phone}] Waiting 120s to cancel & refund...{C.RST}")
    await asyncio.sleep(120)
    while True:
        status = await cancel_number(session, p_name, aid)
        if "EARLY_CANCEL_DENIED" in status:
            await asyncio.sleep(10)
        elif "CANCEL" in status or "ACTIVATION" in status:
            print(f"  {C.RED}[{phone}] Cancelled & Refunded.{C.RST}")
            break
        else:
            print(f"  {C.YEL}[{phone}] Cancel response: {status}{C.RST}")
            break

# ─── Browser Automation ──────────────────────────────────────────────────────
async def automate_login(browser, session, num_info, profile_idx):
    """Open a browser tab, type the number, generate OTP, wait for OTP, submit it."""
    aid = num_info["aid"]
    phone = num_info["phone"]
    p_name = num_info["provider"]
    
    # Clean phone number (remove country code prefix)
    clean_phone = phone
    if clean_phone.startswith("91") and len(clean_phone) > 10:
        clean_phone = clean_phone[2:]
    
    profile_path = os.path.join(PROFILES_DIR, f"session_{profile_idx}")
    os.makedirs(profile_path, exist_ok=True)
    
    print(f"\n  {C.CYN}🌐 [{p_name}] Opening browser for {phone}...{C.RST}")
    
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        storage_state=None
    )
    page = await context.new_page()
    
    try:
        # Step 1: Navigate to Jio login
        await page.goto(JIO_LOGIN_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
        
        # Step 2: Type phone number
        input_field = page.locator('[data-testid="numberField"]')
        await input_field.fill(clean_phone)
        print(f"  {C.DIM}[{phone}] Typed number into input field.{C.RST}")
        await asyncio.sleep(1)
        
        # Step 3: Click Generate OTP
        generate_btn = page.locator('[data-testid="generateOTPButton"]')
        await generate_btn.click()
        print(f"  {C.MAG}[{phone}] Clicked Generate OTP! Polling SMS API...{C.RST}")
        await asyncio.sleep(2)
        
        # Step 4: Poll for OTP from the SMS provider
        otp_code = None
        for attempt in range(60):  # Max ~3 minutes of polling
            status = await get_otp_status(session, p_name, aid)
            if status.startswith("STATUS_OK:"):
                otp_text = status.split(":", 1)[1]
                match = re.search(r'\b(\d{6})\b', otp_text)
                otp_code = match.group(1) if match else otp_text.strip()
                tracker.record(p_name, "otp")
                print(f"  {C.GRN}{C.B}✅ [{phone}] OTP RECEIVED: {otp_code}{C.RST}")
                break
            elif "CANCEL" in status:
                print(f"  {C.YEL}[{phone}] Cancelled by server (no OTP).{C.RST}")
                break
            await asyncio.sleep(3)
        
        if not otp_code:
            print(f"  {C.RED}[{phone}] No OTP received. Skipping.{C.RST}")
            await context.close()
            return None
        
        # Step 5: Type OTP digits into the 6 individual input boxes
        for i, digit in enumerate(otp_code[:6]):
            otp_input = page.locator(f'#basic-input-testInput-code-block-{i}')
            await otp_input.fill(digit)
            await asyncio.sleep(0.1)
        print(f"  {C.DIM}[{phone}] Typed OTP into fields.{C.RST}")
        await asyncio.sleep(1)
        
        # Step 6: Click Submit
        submit_btn = page.locator('button:has-text("Submit")')
        await submit_btn.click()
        print(f"  {C.GRN}{C.B}🎉 [{phone}] Login submitted!{C.RST}")
        tracker.record(p_name, "login")
        await asyncio.sleep(3)
        
        # Save session state for this profile
        state_path = os.path.join(profile_path, "state.json")
        await context.storage_state(path=state_path)
        
        return {"context": context, "page": page, "phone": phone, "aid": aid, "provider": p_name}
        
    except Exception as e:
        print(f"  {C.RED}[{phone}] Browser error: {e}{C.RST}")
        await context.close()
        return None

# ─── Provider Sniper Worker ──────────────────────────────────────────────────
async def provider_sniper(session, p_name, jio_queue, stop_event):
    """Continuously snipe numbers from a single provider, push Jio ones to the queue."""
    delay = PROVIDERS[p_name]["delay"]
    
    while not stop_event.is_set():
        try:
            result = await buy_number(session, p_name)
            
            if result["status"] == "success":
                tracker.record(p_name, "fetched")
                phone = result["phone"]
                carrier = await get_carrier(session, phone)
                
                if "jio" in carrier.lower() or "reliance" in carrier.lower():
                    tracker.record(p_name, "jio")
                    print(f"  {C.GRN}✓ [{p_name}] {phone}: {carrier}{C.RST}")
                    await jio_queue.put(result)
                else:
                    print(f"  {C.DIM}✗ [{p_name}] {phone}: {carrier}{C.RST}")
                    asyncio.create_task(cancel_with_retry(session, p_name, result["aid"], phone))
            
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(delay)

# ─── Main Flow ───────────────────────────────────────────────────────────────
async def main_flow(batch_size):
    from playwright.async_api import async_playwright
    
    os.makedirs(PROFILES_DIR, exist_ok=True)
    
    print(f"{C.GRN}{C.B}🚀 AUTO-SNIPER STARTED! 🚀{C.RST}")
    print(f"{C.DIM}Batch size: {batch_size} | Profiles stored in: {PROFILES_DIR}{C.RST}")
    print(f"{C.DIM}Providers: {', '.join(PROVIDERS.keys())}{C.RST}")
    print(f"{C.YEL}Numbers open in browser INSTANTLY when found!{C.RST}\n")
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        
        async with aiohttp.ClientSession() as session:
            batch_num = 0
            
            while True:
                batch_num += 1
                print(f"\n{'='*60}")
                print(f"{C.B}{C.CYN}  BATCH #{batch_num} — Sniping {batch_size} Jio Numbers{C.RST}")
                print(f"{'='*60}")
                
                # Queue to pipeline: sniper -> browser automation
                jio_queue = asyncio.Queue()
                stop_event = asyncio.Event()
                
                # Start sniper workers for all providers
                sniper_tasks = [
                    asyncio.create_task(provider_sniper(session, p, jio_queue, stop_event))
                    for p in PROVIDERS
                ]
                
                # Consume Jio numbers from queue and open browsers INSTANTLY
                active_sessions = []
                login_tasks = []
                jio_count = 0
                
                while jio_count < batch_size:
                    try:
                        # Wait for a Jio number (with a timeout to keep things responsive)
                        num_info = await asyncio.wait_for(jio_queue.get(), timeout=1.0)
                        jio_count += 1
                        print(f"\n  {C.GRN}{C.B}★ Jio #{jio_count}/{batch_size} found! Opening browser IMMEDIATELY...{C.RST}")
                        
                        # Fire off browser automation instantly — don't wait for it
                        task = asyncio.create_task(
                            automate_login(browser, session, num_info, jio_count - 1)
                        )
                        login_tasks.append(task)
                        
                    except asyncio.TimeoutError:
                        # No Jio number yet, snipers are still working
                        continue
                
                # Stop all sniper workers — we have enough Jio numbers
                stop_event.set()
                for t in sniper_tasks:
                    t.cancel()
                
                # Wait for all browser login tasks to finish
                print(f"\n{C.DIM}All {batch_size} Jio numbers found! Waiting for browser logins to complete...{C.RST}")
                login_results = await asyncio.gather(*login_tasks, return_exceptions=True)
                
                active_sessions = [r for r in login_results if r is not None and not isinstance(r, Exception)]
                
                tracker.print_dashboard()
                
                print(f"\n{C.GRN}{C.B}✅ Batch #{batch_num} complete! {len(active_sessions)} sessions logged in.{C.RST}")
                print(f"{C.YEL}{C.B}[?] Extract your links now. When done, press ENTER to close sessions and start next batch...{C.RST}")
                
                # Wait for user input
                await asyncio.get_event_loop().run_in_executor(None, input)
                
                # Close all browser sessions and cancel the numbers
                print(f"\n{C.DIM}Closing browser sessions and cancelling numbers...{C.RST}")
                for sess in active_sessions:
                    try:
                        await sess["context"].close()
                    except: pass
                    asyncio.create_task(
                        cancel_with_retry(session, sess["provider"], sess["aid"], sess["phone"])
                    )
                
                # Clean up profiles for next batch
                print(f"  {C.DIM}Cleaning up profiles...{C.RST}")
                for i in range(batch_size):
                    p = os.path.join(PROFILES_DIR, f"session_{i}")
                    if os.path.exists(p):
                        shutil.rmtree(p, ignore_errors=True)
                
                print(f"\n{C.GRN}Ready for next batch!{C.RST}")

def main():
    parser = argparse.ArgumentParser(description="Auto-Sniper: Omni + Web Automation")
    parser.add_argument("--batch", "-b", type=int, default=BATCH_SIZE, help="Number of Jio numbers per batch (default: 5)")
    args = parser.parse_args()
    
    try:
        asyncio.run(main_flow(args.batch))
    except KeyboardInterrupt:
        print(f"\n{C.RED}Exiting Auto-Sniper.{C.RST}")
        tracker.print_dashboard()

if __name__ == "__main__":
    main()

