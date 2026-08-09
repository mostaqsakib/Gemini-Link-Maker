import re
import csv
import os
import asyncio
import base64
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

PROJECT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_DIR / ".env")

# Firebase URL extraction patterns
FIREBASE_URL_REGEX = r"(https?://[a-zA-Z0-9._-]+-default-rtdb\.firebaseio\.com)"
# Base64 panel domains (profexpanel, xipher-panel, badxweb, etc.)
PANEL_REGEX = r"(?:profexpanel|xipher-panel|badxweb|panel\w*)\.(?:netlify\.app|vercel\.app)/\?s=([A-Za-z0-9+/=]+)"

TSV_FILE = 'data/telegram_scraped_data.tsv'

def load_existing_urls(tsv_path):
    """Load all existing Firebase URLs from TSV (including from ----New---- sections)."""
    seen = set()
    if not os.path.exists(tsv_path):
        return seen
    with open(tsv_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("----"):
                continue
            url = line.split("\t")[0].strip().rstrip("/")
            if "firebaseio.com" in url:
                seen.add(url)
    return seen

def extract_firebase_from_base64(b64_str):
    """Decode a base64 panel URL and extract Firebase URLs from it."""
    try:
        # Pad if necessary
        b64_str = b64_str.strip()
        b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        # Extract all Firebase URLs from decoded string
        urls = re.findall(FIREBASE_URL_REGEX, decoded)
        return [u.rstrip("/") for u in urls]
    except Exception:
        return []

async def main():
    api_id_raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    target_chat_raw = os.environ.get("TELEGRAM_TARGET_CHAT", "").strip()
    session_name = os.environ.get("TELEGRAM_SESSION_NAME", "session_name").strip()

    if not api_id_raw or not api_hash or not target_chat_raw:
        raise SystemExit(
            "Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and "
            "TELEGRAM_TARGET_CHAT before running this script."
        )

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise SystemExit("TELEGRAM_API_ID must be an integer.") from exc

    try:
        target_chat = int(target_chat_raw)
    except ValueError:
        target_chat = target_chat_raw

    message_limit_raw = os.environ.get("TELEGRAM_MESSAGE_LIMIT", "").strip()
    message_limit = int(message_limit_raw) if message_limit_raw else None

    print("Logging into Telegram...")
    async with TelegramClient(session_name, api_id, api_hash) as client:
        print("Successfully logged in!")

        # Load existing URLs for deduplication
        seen_urls = load_existing_urls(TSV_FILE)
        existing_count = len(seen_urls)
        print(f"Loaded {existing_count} existing URLs from {TSV_FILE} (will skip these)")

        new_entries = []

        print(f"Fetching messages from {target_chat} (Firebase links only)...")
        async for message in client.iter_messages(target_chat, limit=message_limit):
            if not message.text:
                continue

            text = message.text

            # Method 1: Base64 panel URLs (profexpanel, xipher-panel, badxweb, etc.)
            panel_matches = re.findall(PANEL_REGEX, text)
            for b64_str in panel_matches:
                firebase_urls = extract_firebase_from_base64(b64_str)
                for url in firebase_urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        new_entries.append(url)
                        print(f"  🔓 Base64: {url}")

            # Method 2: Direct Firebase URLs anywhere in the message
            direct_matches = re.findall(FIREBASE_URL_REGEX, text)
            for url in direct_matches:
                url = url.strip().rstrip("/")
                if url not in seen_urls:
                    seen_urls.add(url)
                    new_entries.append(url)
                    print(f"  🔗 Direct: {url}")

            # Method 3: Any other base64 strings that might contain Firebase URLs
            # (catch-all for new panel domains)
            other_b64 = re.findall(r'\?s=([A-Za-z0-9+/]{20,}={0,2})', text)
            for b64_str in other_b64:
                if b64_str in [m for m in panel_matches]:
                    continue  # Already processed
                firebase_urls = extract_firebase_from_base64(b64_str)
                for url in firebase_urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        new_entries.append(url)
                        print(f"  🔑 Base64 (other): {url}")

        if new_entries:
            # Append with ----New---- separator
            with open(TSV_FILE, 'a', encoding='utf-8') as f:
                from datetime import datetime
                f.write(f"----New ({datetime.now().strftime('%Y-%m-%d %H:%M')})----\n")
                for url in new_entries:
                    f.write(f"{url}\tUnknown\t\t\t\t\n")

            print(f"\n✅ Found {len(new_entries)} NEW Firebase URLs! (skipped {existing_count} existing)")
            print(f"📁 Appended to: {TSV_FILE}")
        else:
            print(f"\n❌ No NEW Firebase URLs found. ({existing_count} already known)")
            print("Try again later when new links are posted.")

if __name__ == '__main__':
    asyncio.run(main())
