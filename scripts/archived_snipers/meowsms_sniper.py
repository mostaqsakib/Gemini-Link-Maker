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
import re

# ─── Configuration ───────────────────────────────────────────────────────────
API_KEY = os.environ.get("MEOWSMS_API_KEY", "")
BASE_URL = "https://meowsms.shop/stubs/handler_api.php"

SERVICE = "myjio"  # MeowSMS code for MyJio
COUNTRY = "22"     # India

DEFAULT_TARGET = 1

# ─── API Key Rotation ────────────────────────────────────────────────────────
OMKAR_API_KEYS = [k.strip() for k in os.environ.get("OMKAR_API_KEYS", "").split(",") if k.strip()]
current_api_index = 0
omkar_keys_exhausted = False

# ─── Helpers ─────────────────────────────────────────────────────────────────
class C:
    RST = "\033[0m"
    B   = "\033[1m"
    DIM = "\033[2m"
    GRN = "\033[92m"
    RED = "\033[91m"
    YEL = "\033[93m"
    CYN = "\033[96m"
    MAG = "\033[95m"

# ─── API Functions ───────────────────────────────────────────────────────────
async def get_carrier(session, number_str):
    global current_api_index, omkar_keys_exhausted
    if not number_str.startswith('+'):
        number_str = '+' + number_str
        
    url = "https://carrier-lookup-api.omkar.cloud/lookup"
    
    for _ in range(len(OMKAR_API_KEYS)):
        current_key = OMKAR_API_KEYS[current_api_index]
        try:
            async with session.get(url, params={"phone": number_str}, headers={"API-Key": current_key}) as resp:
                if resp.status == 429 or resp.status == 400:
                    data = await resp.json()
                    if "exceeded" in data.get("message", "").lower():
                        print(f"  {C.YEL}[MNP] API Key {current_api_index+1} exhausted. Switching to next key...{C.RST}")
                        current_api_index = (current_api_index + 1) % len(OMKAR_API_KEYS)
                        continue
                
                if resp.status == 200:
                    data = await resp.json()
                    carrier = data.get("carrier", "")
                    return carrier if carrier else "Unknown"
        except Exception:
            pass
            
    print(f"  {C.RED}[MNP] ALL OMKAR API KEYS EXHAUSTED OR FAILED!{C.RST}")
    omkar_keys_exhausted = True
    return "Unknown"

async def check_balance(session):
    params = {"action": "getBalance", "api_key": API_KEY}
    try:
        async with session.get(BASE_URL, params=params) as resp:
            text = (await resp.text()).strip()
            if text.startswith("ACCESS_BALANCE:"):
                return float(text.split(":", 1)[1])
    except:
        pass
    return None

async def buy_number(session):
    params = {
        "action": "getNumber",
        "api_key": API_KEY,
        "service": SERVICE,
        "country": COUNTRY
    }
    try:
        async with session.get(BASE_URL, params=params) as resp:
            text = (await resp.text()).strip()
            if text.startswith("ACCESS_NUMBER:"):
                parts = text.split(":")
                return {
                    "status": "success",
                    "activation_id": parts[1],
                    "phone_number": parts[2]
                }
            else:
                return {"status": "error", "raw": text}
    except Exception as e:
        return {"status": "error", "raw": str(e)}

async def get_otp_status(session, activation_id):
    params = {"action": "getStatus", "api_key": API_KEY, "id": activation_id}
    try:
        async with session.get(BASE_URL, params=params) as resp:
            return (await resp.text()).strip()
    except Exception as e:
        return f"ERROR: {e}"

async def cancel_number(session, activation_id):
    params = {
        "action": "setStatus",
        "api_key": API_KEY,
        "status": "8",
        "id": activation_id
    }
    try:
        async with session.get(BASE_URL, params=params) as resp:
            return (await resp.text()).strip()
    except Exception as e:
        return f"ERROR: {e}"

# ─── Task Logic ──────────────────────────────────────────────────────────────
async def buy_batch(session, count):
    tasks = [buy_number(session) for _ in range(count)]
    batch_results = await asyncio.gather(*tasks)
    
    results = [r for r in batch_results if r["status"] == "success"]
    errors = [r for r in batch_results if r["status"] == "error"]
    
    if errors and not results:
        print(f"  {C.DIM}MeowSMS API Response: {errors[0]['raw']}{C.RST}")
        
    return results

async def cancel_task(session, num_info):
    aid = num_info["activation_id"]
    phone = num_info["phone_number"]
    print(f"  {C.DIM}[{phone}] Non-Jio detected. Waiting 120s to cancel & refund...{C.RST}")
    await asyncio.sleep(120)
    
    while True:
        status = await cancel_number(session, aid)
        if "EARLY_CANCEL_DENIED" in status:
            await asyncio.sleep(10)
        elif status == "ACCESS_CANCEL" or status == "ACCESS_ACTIVATION":
            print(f"  {C.RED}[{phone}] Successfully cancelled and refunded.{C.RST}")
            break
        else:
            print(f"  {C.YEL}[{phone}] Cancel response: {status}{C.RST}")
            break

async def poll_task(session, num_info):
    aid = num_info["activation_id"]
    phone = num_info["phone_number"]
    print(f"\n  {C.GRN}{C.B}★ [{phone}] TRUE JIO SECURED! Polling for OTP...{C.RST}")
    
    while True:
        status = await get_otp_status(session, aid)
        if status.startswith("STATUS_OK:"):
            otp = status.split(":", 1)[1]
            match = re.search(r'\b(\d{6})\b', otp)
            clean_otp = match.group(1) if match else otp
            
            print(f"\n  {C.GRN}{C.B}✅✅✅ [{phone}] OTP RECEIVED: {clean_otp} ✅✅✅{C.RST}")
            break
        elif status == "STATUS_CANCEL" or status == "ACCESS_CANCEL":
            print(f"  {C.YEL}[{phone}] Number was cancelled by server.{C.RST}")
            break
        elif "ERROR" in status:
            await asyncio.sleep(5)
        else:
            await asyncio.sleep(3)

# ─── Sniper Loop ──────────────────────────────────────────────────────────────
async def main_flow(target_jio_count):
    async with aiohttp.ClientSession() as session:
        bal = await check_balance(session)
        if bal is None:
            print(f"{C.RED}Failed to fetch MeowSMS balance. Check API key.{C.RST}")
            return
        print(f"{C.GRN}💰 MeowSMS Auto-Sniper Started! Target: {target_jio_count} true Jio accounts. Current Balance: ₹{bal}{C.RST}")
        
        background_tasks = []
        true_jio_secured = 0
        consecutive_unknowns = 0
        
        try:
            batch_size = target_jio_count * 3
            if batch_size > 5: batch_size = 5
            
            while true_jio_secured < target_jio_count:
                sys.stdout.write(f"\r{C.DIM}▸ Sniping MeowSMS... Looking for stock...{C.RST}")
                sys.stdout.flush()
                
                purchased = await buy_batch(session, batch_size)
                
                if purchased:
                    print(f"\n{C.CYN}▸ Caught {len(purchased)} numbers! Checking MNP for true Jio...{C.RST}")
                    carrier_tasks = [get_carrier(session, p["phone_number"]) for p in purchased]
                    carriers = await asyncio.gather(*carrier_tasks)
                    
                    for p, carrier_name in zip(purchased, carriers):
                        if carrier_name == "Unknown":
                            consecutive_unknowns += 1
                        else:
                            consecutive_unknowns = 0
                            
                        if omkar_keys_exhausted and consecutive_unknowns > 10:
                            if true_jio_secured < target_jio_count:
                                print(f"\n{C.RED}{C.B}Omkar API keys exhausted and 10 consecutive unknowns. Stopping gracefully.{C.RST}")
                                true_jio_secured = target_jio_count # Force stop loop and cancel remaining
                        if true_jio_secured >= target_jio_count:
                            background_tasks.append(asyncio.create_task(cancel_task(session, p)))
                            continue
                            
                        phone = p["phone_number"]
                        if "jio" in carrier_name.lower() or "reliance" in carrier_name.lower():
                            print(f"  {C.GRN}✓ {phone}: {carrier_name}{C.RST}")
                            true_jio_secured += 1
                            background_tasks.append(asyncio.create_task(poll_task(session, p)))
                        else:
                            print(f"  {C.YEL}✗ {phone}: {carrier_name}{C.RST}")
                            background_tasks.append(asyncio.create_task(cancel_task(session, p)))
                            
                    print(f"\n{C.B}Progress: {true_jio_secured}/{target_jio_count} true Jio accounts processed.{C.RST}\n")
                
                if true_jio_secured < target_jio_count:
                    await asyncio.sleep(3)
            
            print(f"\n{C.GRN}{C.B}🎯 Target reached! Waiting for any remaining OTPs and pending cancellations to finish...{C.RST}")
            if background_tasks:
                await asyncio.gather(*background_tasks)
                
        except asyncio.CancelledError:
            print(f"\n{C.RED}Sniper cancelled. Background tasks might still be running.{C.RST}")

def main():
    parser = argparse.ArgumentParser(description="MeowSMS Jio Infinite Sniper")
    parser.add_argument("--count", "-n", type=int, default=DEFAULT_TARGET, help="Target number of TRUE Jio numbers to secure")
    args = parser.parse_args()
    
    try:
        asyncio.run(main_flow(args.count))
    except KeyboardInterrupt:
        print("\nExiting Sniper...")

if __name__ == "__main__":
    main()
