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
import time
import sys
import subprocess
import re
import csv
import os

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

DEFAULT_TARGET = 100

# ─── ADB Coordinates ─────────────────────────────────────────────────────────
COORD_PHONE_INPUT_X = 500
COORD_PHONE_INPUT_Y = 500
COORD_GENERATE_OTP_X = 500
COORD_GENERATE_OTP_Y = 800
COORD_OTP_INPUT_X = 500
COORD_OTP_INPUT_Y = 600
COORD_SUBMIT_OTP_X = 500
COORD_SUBMIT_OTP_Y = 900
ADB_ENABLED = False

# ─── Helpers & Analytics ─────────────────────────────────────────────────────
class C:
    RST = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
    GRN = "\033[92m"; RED = "\033[91m"; YEL = "\033[93m"
    CYN = "\033[96m"; MAG = "\033[95m"; BLU = "\033[94m"

class Analytics:
    def __init__(self, target):
        self.stats = {p: {"fetched": 0, "jio": 0, "otp": 0} for p in PROVIDERS}
        self.csv_file = "sniper_stats.csv"
        self.target = target
        self.total_accounts = 0
        self._init_csv()

    def _init_csv(self):
        with open(self.csv_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Provider", "Fetched_Numbers", "Jio_Numbers", "OTP_Received", "Jio_Hit_Rate", "OTP_Success_Rate"])

    def record(self, provider, metric):
        self.stats[provider][metric] += 1
        if metric == "otp":
            self.total_accounts += 1
        self._write_csv()

    def _write_csv(self):
        with open(self.csv_file, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Provider", "Fetched_Numbers", "Jio_Numbers", "OTP_Received", "Jio_Hit_Rate", "OTP_Success_Rate"])
            for p, s in self.stats.items():
                jio_rate = f"{(s['jio']/s['fetched']*100):.1f}%" if s['fetched'] > 0 else "0%"
                otp_rate = f"{(s['otp']/s['jio']*100):.1f}%" if s['jio'] > 0 else "0%"
                w.writerow([p, s['fetched'], s['jio'], s['otp'], jio_rate, otp_rate])

    def print_dashboard(self):
        print(f"\n{C.B}📊 OMNI-SNIPER REAL-TIME ANALYTICS 📊{C.RST}")
        print(f"{C.CYN}{C.B}🎯 TOTAL COMPLETED ACCOUNTS: {self.total_accounts}/{self.target}{C.RST}")
        print(f"{'Provider':<10} | {'Fetched':<7} | {'Jio':<5} | {'OTPs':<4} | {'Jio %':<7} | {'OTP %':<7}")
        print("-" * 55)
        for p, s in self.stats.items():
            jio_rate = f"{(s['jio']/s['fetched']*100):.1f}%" if s['fetched'] > 0 else "0%"
            otp_rate = f"{(s['otp']/s['jio']*100):.1f}%" if s['jio'] > 0 else "0%"
            print(f"{C.CYN}{p:<10}{C.RST} | {s['fetched']:<7} | {C.GRN}{s['jio']:<5}{C.RST} | {C.MAG}{s['otp']:<4}{C.RST} | {C.YEL}{jio_rate:<7}{C.RST} | {C.BLU}{otp_rate:<7}{C.RST}")
        print("-" * 55 + "\n")

    def is_finished(self):
        return self.total_accounts >= self.target

tracker = None

# ─── ADB Hardware Automation ─────────────────────────────────────────────────
def run_adb(cmd):
    if not ADB_ENABLED: return
    try:
        subprocess.run(f"adb {cmd}", shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def adb_type_phone(phone):
    if not ADB_ENABLED: return
    print(f"  {C.CYN}🤖 ADB: Typing number...{C.RST}")
    run_adb(f"shell input tap {COORD_PHONE_INPUT_X} {COORD_PHONE_INPUT_Y}")
    time.sleep(0.5)
    clean = phone.replace("+91", "").replace("+", "").strip()
    run_adb(f"shell input text {clean}")
    time.sleep(0.5)
    run_adb(f"shell input tap {COORD_GENERATE_OTP_X} {COORD_GENERATE_OTP_Y}")

def adb_type_otp(otp):
    if not ADB_ENABLED: return
    print(f"  {C.CYN}🤖 ADB: Typing OTP...{C.RST}")
    run_adb(f"shell input tap {COORD_OTP_INPUT_X} {COORD_OTP_INPUT_Y}")
    time.sleep(0.5)
    run_adb(f"shell input text {otp}")
    time.sleep(0.5)
    run_adb(f"shell input tap {COORD_SUBMIT_OTP_X} {COORD_SUBMIT_OTP_Y}")

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
                        current_api_index = (current_api_index + 1) % len(OMKAR_API_KEYS)
                        continue
                if resp.status == 200:
                    return (await resp.json()).get("carrier", "Unknown")
        except: pass
    return "Unknown"

async def buy_number(session, p_name):
    cfg = PROVIDERS[p_name]
    params = {"action": "getNumber", "api_key": cfg["key"], "service": cfg["service"], "country": cfg["country"]}
    
    # Special iteration for UOTP servers
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

# ─── Worker Tasks ────────────────────────────────────────────────────────────
global_tasks = []

async def process_number(session, num_info):
    aid = num_info["aid"]
    phone = num_info["phone"]
    p_name = num_info["provider"]
    
    carrier = await get_carrier(session, phone)
    
    if "jio" in carrier.lower() or "reliance" in carrier.lower():
        tracker.record(p_name, "jio")
        print(f"\n  {C.GRN}✓ [{p_name}] {phone} : {carrier}{C.RST}")
        print(f"  {C.B}★ TRUE JIO SECURED! Polling for OTP...{C.RST}")
        adb_type_phone(phone)
        
        while True:
            status = await get_otp_status(session, p_name, aid)
            if status.startswith("STATUS_OK:"):
                otp = status.split(":", 1)[1]
                match = re.search(r'\b(\d{6})\b', otp)
                clean_otp = match.group(1) if match else otp
                
                tracker.record(p_name, "otp")
                tracker.print_dashboard()
                
                print(f"\n  {C.GRN}{C.B}✅✅✅ [{p_name}] {phone} OTP RECEIVED: {clean_otp} ✅✅✅{C.RST}")
                adb_type_otp(clean_otp)
                break
            elif "CANCEL" in status:
                print(f"  {C.YEL}[{p_name}] {phone} cancelled by server (No OTP).{C.RST}")
                break
            elif "ERROR" in status: await asyncio.sleep(5)
            else: await asyncio.sleep(3)
            
    else:
        # Non-Jio, cancel it
        print(f"  {C.DIM}✗ [{p_name}] {phone} : {carrier} (Cancelling in 120s){C.RST}")
        await asyncio.sleep(120)
        while True:
            status = await cancel_number(session, p_name, aid)
            if "EARLY_CANCEL_DENIED" in status: await asyncio.sleep(10)
            elif "CANCEL" in status or "ACTIVATION" in status:
                print(f"  {C.RED}[{p_name}] {phone} Successfully Cancelled & Refunded.{C.RST}")
                break
            else:
                break

async def provider_worker(session, p_name):
    delay = PROVIDERS[p_name]["delay"]
    while True:
        if tracker and tracker.is_finished():
            break
            
        # Buy up to 2 numbers at a time per provider to avoid rate limits while being aggressive
        tasks = [buy_number(session, p_name) for _ in range(2)]
        results = await asyncio.gather(*tasks)
        
        for r in results:
            if r["status"] == "success":
                tracker.record(p_name, "fetched")
                # Fire and forget the processing task so the worker can keep sniping
                # We save this task to global background_tasks so we can await it later
                global_tasks.append(asyncio.create_task(process_number(session, r)))
                
        await asyncio.sleep(delay)

# ─── Main Omni Loop ──────────────────────────────────────────────────────────
async def main_flow(target):
    global ADB_ENABLED, tracker
    tracker = Analytics(target)
    
    try:
        output = subprocess.check_output("adb devices", shell=True, text=True)
        if "device\n" in output or "emulator" in output:
            ADB_ENABLED = True
            print(f"{C.CYN}🤖 ADB Device detected! Hardware Automation ENABLED.{C.RST}")
        else:
            print(f"{C.YEL}⚠️ No ADB device found. Running in Manual/Terminal Mode.{C.RST}")
    except:
        print(f"{C.YEL}⚠️ ADB not installed or failing. Running in Manual/Terminal Mode.{C.RST}")

    async with aiohttp.ClientSession() as session:
        print(f"{C.GRN}{C.B}🚀 OMNI-SNIPER STARTED! 🚀{C.RST}")
        print(f"{C.DIM}Aggressively draining UOTP, Grizzly, Tiger, and MeowSMS simultaneously...{C.RST}\n")
        
        workers = [asyncio.create_task(provider_worker(session, p)) for p in PROVIDERS]
        
        try:
            while not tracker.is_finished():
                await asyncio.sleep(1)
            
            print(f"\n{C.GRN}{C.B}🎯 Target of {target} accounts reached! Waiting for pending cancellations...{C.RST}")
            # Cancel all worker tasks so we stop buying numbers
            for w in workers:
                w.cancel()
                
            # Wait for remaining poll_tasks to finish
            if global_tasks:
                await asyncio.gather(*global_tasks, return_exceptions=True)
                
        except asyncio.CancelledError:
            print(f"\n{C.RED}Shutting down Omni-Sniper...{C.RST}")

def main():
    parser = argparse.ArgumentParser(description="Omni-Sniper for Jio")
    parser.add_argument("--count", "-n", type=int, default=DEFAULT_TARGET, help="Target number of accounts to complete")
    args = parser.parse_args()

    try:
        asyncio.run(main_flow(args.count))
    except KeyboardInterrupt:
        print("\nExiting Omni-Sniper. Final Stats saved to sniper_stats.csv!")
        if tracker: tracker.print_dashboard()

if __name__ == "__main__":
    main()
