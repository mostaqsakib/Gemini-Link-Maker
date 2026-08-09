#!/usr/bin/env python3
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
import time
import argparse
import sys
try:
    import requests
except ImportError:
    print("⚠️  requests not installed. Installing now...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "--break-system-packages"])
    import requests

API_KEY = os.environ.get("UOTP_API_KEY", "")
BASE_URL = "https://uotp.store/api/stubs/handler_api.php"

def check_status(activation_id):
    params = {
        "action": "getStatus",
        "api_key": API_KEY,
        "id": activation_id
    }
    try:
        resp = requests.get(BASE_URL, params=params)
        text = resp.text.strip()
        return text
    except Exception as e:
        return f"ERROR: {e}"

def main():
    parser = argparse.ArgumentParser(description="Check OTP status for a UOTP activation ID.")
    parser.add_argument("activation_ids", nargs="+", help="One or more Activation IDs to check")
    parser.add_argument("--poll", action="store_true", help="Keep polling until an OTP is received")
    
    args = parser.parse_args()
    
    print("\n🔍 Checking OTP Status...\n")
    
    active_ids = args.activation_ids.copy()
    
    while active_ids:
        for aid in active_ids[:]:
            status = check_status(aid)
            
            if status.startswith("STATUS_OK:"):
                otp = status.split(":", 1)[1]
                print(f"✅ [ID: {aid}] OTP Received: {otp}")
                active_ids.remove(aid)
            elif status == "STATUS_WAIT_CODE":
                if not args.poll:
                    print(f"⏳ [ID: {aid}] Waiting for SMS...")
                    active_ids.remove(aid)
            elif status == "STATUS_CANCEL":
                print(f"❌ [ID: {aid}] Activation was canceled.")
                active_ids.remove(aid)
            else:
                print(f"⚠️ [ID: {aid}] Unexpected status: {status}")
                if not args.poll:
                    active_ids.remove(aid)
                    
        if args.poll and active_ids:
            time.sleep(5)  # Wait 5 seconds before polling again

    if args.poll:
        print("\nAll done!")

if __name__ == "__main__":
    main()
