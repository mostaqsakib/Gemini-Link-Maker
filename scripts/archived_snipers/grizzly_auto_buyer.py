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
DEFAULT_COUNT = 5

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

async def get_carrier(session, number_str):
    if not number_str.startswith('+'):
        number_str = '+' + number_str
        
    url = "https://carrier-lookup-api.omkar.cloud/lookup"
    try:
        async with session.get(url, params={"phone": number_str}, headers={"API-Key": OMKAR_API_KEY}) as resp:
            data = await resp.json()
            carrier = data.get("carrier", "")
            return carrier if carrier else "Unknown"
    except Exception as e:
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
            data = await resp.json(content_type=None) # Sometimes Grizzly returns text instead of proper application/json header
            
            # Grizzly returns dict on success, but plain string on error
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
        # Fallback if the response is completely flat text
        try:
           text = (await resp.text()).strip()
           return {"status": "error", "raw": text}
        except:
           return {"status": "error", "raw": str(e)}

async def get_otp_status(session, activation_id):
    params = {"action": "getStatusV2", "api_key": API_KEY, "id": activation_id}
    try:
        async with session.get(BASE_URL, params=params) as resp:
             # V2 returns JSON on success
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

# ─── Main Logic ──────────────────────────────────────────────────────────────
async def buy_batch(session, count):
    print(f"\n{C.CYN}{C.B}▸ Attempting to buy {count} numbers from Grizzly SMS...{C.RST}")
    results = []
    
    # We will buy them concurrently to be as fast as possible
    tasks = [buy_number(session) for _ in range(count)]
    batch_results = await asyncio.gather(*tasks)
    
    for r in batch_results:
        if r["status"] == "success":
            results.append(r)
        else:
            print(f"  {C.RED}Failed to buy: {r['raw']}{C.RST}")
            
    return results

async def cancel_task(session, num_info):
    aid = num_info["activation_id"]
    phone = num_info["phone_number"]
    
    # Grizzly allows immediate cancellation (no 120s wait needed usually), but we will wait 10s just to be safe
    print(f"  {C.DIM}[{phone}] Cancelling non-Jio number...{C.RST}")
    await asyncio.sleep(5)
    
    # Try cancelling
    status = await cancel_number(session, aid)
    if "ACCESS_CANCEL" in status:
        print(f"  {C.RED}[{phone}] Successfully cancelled non-Jio number. (Refunded){C.RST}")
    else:
        print(f"  {C.YEL}[{phone}] Cancel response: {status}{C.RST}")


async def poll_task(session, num_info):
    aid = num_info["activation_id"]
    phone = num_info["phone_number"]
    print(f"  {C.CYN}[{phone}] Polling for OTP...{C.RST}")
    
    while True:
        status = await get_otp_status(session, aid)
        if "STATUS_OK:" in status:
            otp = status.split(":", 1)[1]
            print(f"\n  {C.GRN}{C.B}✅ [{phone}] OTP RECEIVED: {otp}{C.RST}\n")
            break
        elif "STATUS_CANCEL" in status:
            print(f"  {C.YEL}[{phone}] Number was cancelled.{C.RST}")
            break
        elif "STATUS_WAIT_CODE" in status:
             await asyncio.sleep(3) # Grizzly allows fast polling
        else:
             print(f"  {C.DIM}[{phone}] Polling: {status}{C.RST}")
             await asyncio.sleep(3)

async def main_flow(count):
    async with aiohttp.ClientSession() as session:
        bal = await check_balance(session)
        if bal is None:
            print(f"{C.RED}Failed to fetch balance. Check API key.{C.RST}")
            return
        print(f"{C.GRN}💰 Current Balance: ₽{bal} RUB{C.RST}")
        
        # 1. Buy numbers
        purchased = await buy_batch(session, count)
        if not purchased:
            print(f"{C.RED}❌ Could not purchase any numbers. Out of stock or error.{C.RST}")
            return
            
        print(f"\n{C.GRN}✅ Purchased {len(purchased)} numbers. Live MNP Checking (Omkar Cloud)...{C.RST}")
        
        jio_numbers = []
        non_jio_numbers = []
        
        # 2. Check Carrier
        print(f"\n{C.B}Carrier Results:{C.RST}")
        
        # Parallel MNP checking
        carrier_tasks = [get_carrier(session, p["phone_number"]) for p in purchased]
        carriers = await asyncio.gather(*carrier_tasks)
        
        for p, carrier_name in zip(purchased, carriers):
            phone = p["phone_number"]
            # Check for Jio or Reliance
            if "jio" in carrier_name.lower() or "reliance" in carrier_name.lower():
                jio_numbers.append(p)
                print(f"  {C.GRN}📱 {phone}: {carrier_name} (KEEP){C.RST}")
            else:
                non_jio_numbers.append(p)
                print(f"  {C.YEL}📱 {phone}: {carrier_name} (CANCEL){C.RST}")
                
        # 3. Create async tasks for cancelling and polling
        tasks = []
        
        print(f"\n{C.CYN}{C.B}▸ Starting background tasks...{C.RST}")
        for num in non_jio_numbers:
            tasks.append(asyncio.create_task(cancel_task(session, num)))
            
        for num in jio_numbers:
            tasks.append(asyncio.create_task(poll_task(session, num)))
            
        if tasks:
            await asyncio.gather(*tasks)
            
        print(f"\n{C.GRN}✅ All tasks completed.{C.RST}")

def main():
    parser = argparse.ArgumentParser(description="Grizzly SMS Jio Auto-Buyer with Live MNP")
    parser.add_argument("--count", "-n", type=int, default=DEFAULT_COUNT, help="Number of numbers to buy")
    args = parser.parse_args()
    
    try:
        asyncio.run(main_flow(args.count))
    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
