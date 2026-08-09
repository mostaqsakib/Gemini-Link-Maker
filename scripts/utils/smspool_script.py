import os

import requests

API_KEY = os.environ.get("SMSPOOL_API_KEY", "")

def check_smspool():
    if not API_KEY:
        raise SystemExit("Set SMSPOOL_API_KEY before running this script.")

    try:
        # Get countries
        countries_resp = requests.get(
            "https://api.smspool.net/country/retrieve_all",
            timeout=30,
        ).json()
        countries = {str(c['ID']): c['name'] for c in countries_resp}
        
        # Get all services
        services_resp = requests.get(
            "https://api.smspool.net/service/retrieve_all",
            timeout=30,
        ).json()
        twitter_id = None
        for svc in services_resp:
            if "twitter" in svc['name'].lower() or "x" in svc['name'].lower():
                print(f"Found service: {svc['name']}, ID: {svc['ID']}")
                twitter_id = svc['ID']
        
        if twitter_id:
            # We want to find the cheapest country for this service.
            # Unfortunately, there isn't a single endpoint to list prices for all countries.
            # But there is a prices endpoint? Let's check documentation by making some guesses or check the request/price endpoint for all countries.
            print("Checking prices for all countries...")
            cheapest = []
            for cid in countries.keys():
                try:
                    price_resp = requests.post("https://api.smspool.net/request/price", data={
                        "key": API_KEY,
                        "country": cid,
                        "service": twitter_id
                    }, timeout=30).json()
                    
                    if price_resp.get("success") == 1:
                        price = float(price_resp.get("price", 999))
                        success_rate = price_resp.get("success_rate", "0")
                        cheapest.append((price, countries[cid], success_rate))
                except Exception:
                    pass
            
            cheapest.sort(key=lambda x: x[0])
            for i, (price, name, sr) in enumerate(cheapest[:10]):
                print(f"{i+1}. {name}: ${price:.2f} (Success rate: {sr}%)")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    check_smspool()
