#!/usr/bin/env python3
"""
APK Firebase URL Extractor
Scans a folder of APKs, extracts Firebase Realtime Database URLs,
and auto-adds new ones to telegram_scraped_data.tsv (skipping duplicates).
"""
import os
import subprocess
import re
import csv
import sys

TSV_FILE = "data/telegram_scraped_data.tsv"

def extract_firebase_urls_from_apk(apk_path):
    """Extract firebaseio.com URLs from an APK binary using 'strings'."""
    try:
        result = subprocess.run(
            ["strings", apk_path],
            capture_output=True, text=True, timeout=30
        )
        urls = set()
        for line in result.stdout.splitlines():
            matches = re.findall(r"https?://[a-zA-Z0-9._-]+-default-rtdb\.firebaseio\.com", line)
            for url in matches:
                urls.add(url.rstrip("/"))
        return urls
    except Exception as e:
        print(f"  ⚠️ Error processing {os.path.basename(apk_path)}: {e}")
        return set()

def load_existing_urls(tsv_path):
    """Load already-known URLs from the TSV file."""
    seen = set()
    if not os.path.exists(tsv_path):
        return seen
    with open(tsv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("----"):
                continue
            url = line.split("\t")[0].strip().rstrip("/")
            if "firebaseio.com" in url:
                seen.add(url)
    return seen

def main():
    apk_folder = sys.argv[1] if len(sys.argv) > 1 else "FIREBASE APKs"

    if not os.path.isdir(apk_folder):
        print(f"❌ Folder not found: {apk_folder}")
        sys.exit(1)

    apk_files = [f for f in os.listdir(apk_folder) if f.lower().endswith(".apk")]
    if not apk_files:
        print(f"❌ No .apk files found in {apk_folder}")
        sys.exit(1)

    print(f"📦 Scanning {len(apk_files)} APKs in '{apk_folder}'...\n")

    # Extract URLs from all APKs
    all_extracted = {}
    for apk_file in sorted(apk_files):
        apk_path = os.path.join(apk_folder, apk_file)
        urls = extract_firebase_urls_from_apk(apk_path)
        if urls:
            for url in urls:
                all_extracted[url] = apk_file
            print(f"  ✅ {apk_file}: {', '.join(u.split('//')[1].split('.')[0] for u in urls)}")
        else:
            print(f"  ❌ {apk_file}: No Firebase URL found")

    print(f"\n📊 Found {len(all_extracted)} total Firebase URLs from APKs")

    # Load existing and find new ones
    existing = load_existing_urls(TSV_FILE)
    new_urls = {url: apk for url, apk in all_extracted.items() if url not in existing}

    if not new_urls:
        print(f"✅ All {len(all_extracted)} URLs already in TSV. Nothing to add.")
        return

    # Append new URLs to TSV
    with open(TSV_FILE, "a", encoding="utf-8") as f:
        for url in sorted(new_urls.keys()):
            f.write(f"{url}\tUnknown\t\t\t\t\n")

    print(f"\n🆕 Added {len(new_urls)} new URLs to {TSV_FILE}:")
    for url, apk in sorted(new_urls.items()):
        print(f"  + {url}  (from {apk})")

if __name__ == "__main__":
    main()
