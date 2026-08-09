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

# ─── Configuration ───────────────────────────────────────────────────────────
API_KEY = os.environ.get("GRIZZLY_API_KEY", "")
BASE_URL = "https://api.grizzlysms.com/stubs/handler_api.php"

# Omkar Cloud API Key for MNP Checking
OMKAR_API_KEY = os.environ.get("OMKAR_API_KEY", "")

SERVICE = "jio"
COUNTRY = "22"
DEFAULT_TARGET = 1

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

OMKAR_API_KEYS = [k.strip() for k in os.environ.get("OMKAR_API_KEYS", "").split(",") if k.strip()]
current_api_index = 0
omkar_keys_exhausted = False

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

# ─── API Functions ───────────────────────────────────────────────────────────
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
        "action": "getNumberV2",
        "api_key": API_KEY,
        "service": SERVICE,
        "country": COUNTRY
    }
    try:
        async with session.get(BASE_URL, params=params) as resp:
            data = await resp.json(content_type=None)
            
            if isinstance(data, dict) and "activationId" in data:
                return {
                    "status": "success",
                    "activation_id": str(data["activationId"]),
                    "phone_number": str(data["phoneNumber"])
                }
            elif isinstance(data, str):
                return {"status": "error", "raw": data}
            elif isinstance(data, dict) and "error" in data:
                 return {"status": "error", "raw": data.get("error")}
            else:
                return {"status": "error", "raw": str(data)}
    except Exception as e:
        try:
           text = (await resp.text()).strip()
           return {"status": "error", "raw": text}
        except:
           return {"status": "error", "raw": str(e)}

async def get_otp_status(session, activation_id):
    params = {"action": "getStatusV2", "api_key": API_KEY, "id": activation_id}
    try:
        async with session.get(BASE_URL, params=params) as resp:
            text = await resp.text()
            try:
                import json
                data = json.loads(text)
                if isinstance(data, dict) and "sms" in data:
                    return f"STATUS_OK:{data['sms']['code']}"
                elif isinstance(data, str):
                    return data
            except:
                pass
            return text.strip()
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
    results = []
    tasks = [buy_number(session) for _ in range(count)]
    batch_results = await asyncio.gather(*tasks)
    
    for r in batch_results:
        if r["status"] == "success":
            results.append(r)
            
    return results

async def cancel_task(session, num_info):
    aid = num_info["activation_id"]
    phone = num_info["phone_number"]
    
    print(f"  {C.DIM}[{phone}] Non-Jio detected. Cancelling to refund...{C.RST}")
    await asyncio.sleep(5) # Give it a few seconds before cancelling
    
    status = await cancel_number(session, aid)
    if "ACCESS_CANCEL" in status:
        print(f"  {C.RED}[{phone}] Successfully cancelled and refunded.{C.RST}")
    else:
        print(f"  {C.YEL}[{phone}] Cancel response: {status}{C.RST}")

async def poll_task(session, num_info):
    aid = num_info["activation_id"]
    phone = num_info["phone_number"]
    print(f"\n  {C.GRN}{C.B}★ [{phone}] TRUE JIO NUMBER SECURED! Polling for OTP...{C.RST}\n")
    
    while True:
        status = await get_otp_status(session, aid)
        if "STATUS_OK:" in status:
            otp = status.split(":", 1)[1]
            print(f"\n  {C.GRN}{C.B}✅✅✅ [{phone}] OTP RECEIVED: {otp} ✅✅✅{C.RST}\n")
            break
        elif "STATUS_CANCEL" in status:
            print(f"  {C.YEL}[{phone}] Number was cancelled.{C.RST}")
            break
        elif "STATUS_WAIT_CODE" in status:
             await asyncio.sleep(3)
        else:
             await asyncio.sleep(3)

# ─── Sniper Loop ──────────────────────────────────────────────────────────────
async def main_flow(target_jio_count):
    async with aiohttp.ClientSession() as session:
        bal = await check_balance(session)
        if bal is None:
            print(f"{C.RED}Failed to fetch balance. Check API key.{C.RST}")
            return
        print(f"{C.GRN}💰 Grizzly Sniper Started! Target: {target_jio_count} true Jio numbers. Balance: ${bal} USD{C.RST}")
        
        background_tasks = []
        true_jio_secured = 0
        consecutive_unknowns = 0
        
        try:
            batch_size = target_jio_count * 3
            if batch_size > 10: batch_size = 10
            
            while true_jio_secured < target_jio_count:
                sys.stdout.write(f"\r{C.DIM}▸ Sniping Grizzly SMS... Looking for stock...{C.RST}")
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
                            
                    print(f"\n{C.B}Progress: {true_jio_secured}/{target_jio_count} true Jio numbers secured.{C.RST}\n")
                
                if true_jio_secured < target_jio_count:
                    # Sleep 5 seconds before hitting the API again to avoid rate limits
                    await asyncio.sleep(5)
            
            print(f"\n{C.GRN}{C.B}🎯 Target reached! Waiting for OTPs and pending cancellations to finish...{C.RST}")
            if background_tasks:
                await asyncio.gather(*background_tasks)
                
        except asyncio.CancelledError:
            print(f"\n{C.RED}Sniper cancelled. Background tasks might still be running.{C.RST}")

def main():
    parser = argparse.ArgumentParser(description="Grizzly SMS Jio Infinite Sniper")
    parser.add_argument("--count", "-n", type=int, default=DEFAULT_TARGET, help="Target number of TRUE Jio numbers to secure")
    args = parser.parse_args()
    
    try:
        asyncio.run(main_flow(args.count))
    except KeyboardInterrupt:
        print("\nExiting Sniper...")

if __name__ == "__main__":
    main()
