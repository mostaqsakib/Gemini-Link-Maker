#!/usr/bin/env python3
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
"""
UOTP Bulk Number Buyer
======================
Buys multiple virtual numbers from the UOTP API in one go.
Supports server selection and auto-buy (tries cheapest server first).

Usage:
    python3 uotp_buy_numbers.py                      # Buy 10 My JIO numbers, auto-pick server
    python3 uotp_buy_numbers.py --count 5             # Buy 5 numbers
    python3 uotp_buy_numbers.py --server 5            # Force Server 5 (₹10)
    python3 uotp_buy_numbers.py --server auto         # Auto-buy: cheapest server first (default)
    python3 uotp_buy_numbers.py --service wa          # Buy WhatsApp numbers
    python3 uotp_buy_numbers.py --country 0           # Any country
"""

import asyncio
import argparse
import time
import sys

try:
    import aiohttp
except ImportError:
    print("⚠️  aiohttp not installed. Installing now...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp"])
    import aiohttp


# ─── Configuration ───────────────────────────────────────────────────────────

API_KEY = os.environ.get("UOTP_API_KEY", "")
BASE_URL = "https://uotp.store/api/stubs/handler_api.php"

DEFAULT_SERVICE = "jio"   # My JIO — service code (matches id="svc-jio")
DEFAULT_COUNTRY = "22"    # India
DEFAULT_COUNT = 10        # Number of numbers to buy

# Server list for My JIO (sorted by price ascending, then stock descending).
# The 'operator' field is what gets sent as the API operator param.
# Update these if the website shows different servers.
JIO_SERVERS = [
    {"id": 5, "price": 10.00, "stock": 932,  "operator": "5"},
    {"id": 3, "price": 10.00, "stock": 847,  "operator": "3"},
    {"id": 4, "price": 10.00, "stock": 475,  "operator": "4"},
    {"id": 2, "price": 10.00, "stock": 189,  "operator": "2"},
    {"id": 1, "price": 11.20, "stock": 932,  "operator": "1"},
    {"id": 8, "price": 14.00, "stock": 1748, "operator": "8"},
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

class C:
    """ANSI color codes for terminal output."""
    RST = "\033[0m"
    B   = "\033[1m"
    DIM = "\033[2m"
    GRN = "\033[92m"
    RED = "\033[91m"
    YEL = "\033[93m"
    CYN = "\033[96m"
    BLU = "\033[94m"
    MAG = "\033[95m"
    WHT = "\033[97m"


def banner():
    print(f"""
{C.CYN}{C.B}╔══════════════════════════════════════════════════╗
║           UOTP  ·  Bulk Number Buyer             ║
║          ── My JIO · India (22) ──               ║
╚══════════════════════════════════════════════════╝{C.RST}
""")


def print_server_table():
    """Print available servers."""
    print(f"  {C.B}Available Servers:{C.RST}")
    print(f"  {'─' * 42}")
    print(f"  {C.DIM}{'Server':<12}{'Price':>10}{'Stock':>12}{C.RST}")
    print(f"  {'─' * 42}")
    for s in JIO_SERVERS:
        price_color = C.GRN if s["price"] <= 10 else (C.YEL if s["price"] <= 12 else C.RED)
        print(f"  Server {s['id']:<4}{price_color}₹{s['price']:<9.2f}{C.RST}{s['stock']:>10}")
    print(f"  {'─' * 42}")
    print()


async def check_balance(session: aiohttp.ClientSession) -> str | None:
    """Fetch and display current wallet balance."""
    params = {"action": "getBalance", "api_key": API_KEY}
    try:
        async with session.get(BASE_URL, params=params) as resp:
            text = (await resp.text()).strip()
            if text.startswith("ACCESS_BALANCE:"):
                balance = text.split(":", 1)[1]
                print(f"  {C.GRN}💰 Balance:{C.RST} {C.B}₹{balance}{C.RST}")
                return balance
            else:
                print(f"  {C.RED}❌ Balance check failed:{C.RST} {text}")
                return None
    except Exception as e:
        print(f"  {C.RED}❌ Network error:{C.RST} {e}")
        return None


async def buy_number(
    session: aiohttp.ClientSession,
    index: int,
    service: str,
    country: str,
    operator: str | None = None,
) -> dict:
    """Buy a single number and return the result."""
    params = {
        "action": "getNumber",
        "api_key": API_KEY,
        "service": service,
        "country": country,
    }
    if operator:
        params["operator"] = operator

    try:
        async with session.get(BASE_URL, params=params) as resp:
            text = (await resp.text()).strip()

            if text.startswith("ACCESS_NUMBER:"):
                parts = text.split(":")
                activation_id = parts[1]
                phone_number = parts[2]
                return {
                    "index": index,
                    "status": "success",
                    "activation_id": activation_id,
                    "phone_number": phone_number,
                    "operator": operator or "auto",
                    "raw": text,
                }
            else:
                return {
                    "index": index,
                    "status": "error",
                    "activation_id": None,
                    "phone_number": None,
                    "operator": operator or "auto",
                    "raw": text,
                }
    except Exception as e:
        return {
            "index": index,
            "status": "error",
            "activation_id": None,
            "phone_number": None,
            "operator": operator or "auto",
            "raw": str(e),
        }


async def buy_from_server(
    session: aiohttp.ClientSession,
    count: int,
    service: str,
    country: str,
    operator: str | None,
    server_label: str,
) -> list[dict]:
    """Buy `count` numbers from a specific server concurrently."""
    print(f"  {C.CYN}▸ Buying {count} from {server_label}...{C.RST}")
    tasks = [
        buy_number(session, i + 1, service, country, operator)
        for i in range(count)
    ]
    return await asyncio.gather(*tasks)


async def auto_buy(
    session: aiohttp.ClientSession,
    count: int,
    service: str,
    country: str,
) -> list[dict]:
    """
    Auto-buy mode: try servers from cheapest to most expensive.
    If a server returns errors (NO_NUMBERS, etc.), move to the next one.
    """
    all_results: list[dict] = []
    remaining = count

    for server in JIO_SERVERS:
        if remaining <= 0:
            break

        label = f"Server {server['id']} (₹{server['price']:.2f})"
        results = await buy_from_server(
            session, remaining, service, country,
            server["operator"], label,
        )

        successes = [r for r in results if r["status"] == "success"]
        failures = [r for r in results if r["status"] == "error"]

        # Re-index successes relative to total
        for r in successes:
            r["index"] = count - remaining + successes.index(r) + 1
            r["server"] = server["id"]

        all_results.extend(successes)
        remaining -= len(successes)

        if successes:
            print(f"    {C.GRN}✓ Got {len(successes)} numbers{C.RST}")

        if failures:
            # Check if it's a stockout error
            error_types = set(r["raw"] for r in failures)
            print(f"    {C.YEL}⚠ {len(failures)} failed: {', '.join(error_types)}{C.RST}")

            if remaining > 0:
                print(f"    {C.DIM}→ Trying next server for remaining {remaining}...{C.RST}")

    return all_results


async def buy_numbers_bulk(
    count: int,
    service: str,
    country: str,
    server: str | None = None,
):
    """Buy multiple numbers — either from a specific server or auto-mode."""
    banner()

    # Resolve operator from server choice
    operator = None
    mode = "auto"
    if server and server != "auto":
        try:
            server_id = int(server)
            matched = [s for s in JIO_SERVERS if s["id"] == server_id]
            if matched:
                operator = matched[0]["operator"]
                mode = f"Server {server_id} (₹{matched[0]['price']:.2f})"
            else:
                print(f"  {C.RED}❌ Unknown server '{server}'. Available: {[s['id'] for s in JIO_SERVERS]}{C.RST}")
                return
        except ValueError:
            # Treat it as a raw operator string
            operator = server
            mode = f"operator={server}"

    print(f"  {C.DIM}Service :{C.RST} {C.B}{service}{C.RST}")
    print(f"  {C.DIM}Country :{C.RST} {C.B}{country}{C.RST}")
    print(f"  {C.DIM}Count   :{C.RST} {C.B}{count}{C.RST}")
    print(f"  {C.DIM}Mode    :{C.RST} {C.B}{mode}{C.RST}")
    print()

    if server is None or server == "auto":
        print_server_table()

    connector = aiohttp.TCPConnector(limit=10)
    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # ── Step 1: Check balance ──
        print(f"  {C.CYN}▸ Checking balance...{C.RST}")
        balance = await check_balance(session)
        if balance is None:
            print(f"\n  {C.RED}Aborting: Could not verify balance.{C.RST}\n")
            return
        print()

        # ── Step 2: Buy numbers ──
        start = time.perf_counter()

        if server is None or server == "auto":
            results = await auto_buy(session, count, service, country)
        else:
            raw_results = await buy_from_server(
                session, count, service, country, operator, mode,
            )
            results = []
            for r in raw_results:
                r["server"] = server
                results.append(r)

        elapsed = time.perf_counter() - start

        # ── Step 3: Display results ──
        print()
        successes = [r for r in results if r["status"] == "success"]
        total_bought = len(successes)

        if successes:
            print(f"  {C.GRN}{C.B}✅ Successfully purchased {total_bought}/{count} numbers{C.RST}")
            print()
            print(f"  {C.B}{'#':<4} {'Activation ID':<18} {'Phone Number':<18} {'Server':<8}{C.RST}")
            print(f"  {'─' * 50}")

            for r in sorted(successes, key=lambda x: x["index"]):
                idx = str(r["index"])
                aid = r["activation_id"]
                phone = r["phone_number"]
                srv = str(r.get("server", "?"))
                print(f"  {C.DIM}{idx:<4}{C.RST} {C.CYN}{aid:<18}{C.RST} {C.GRN}{phone:<18}{C.RST} {C.MAG}{srv:<8}{C.RST}")

            print(f"  {'─' * 50}")
        else:
            print(f"  {C.RED}{C.B}❌ No numbers purchased. All attempts failed.{C.RST}")

        # Show failed count
        failed = count - total_bought
        if failed > 0 and total_bought > 0:
            print(f"  {C.YEL}⚠  {failed} numbers could not be purchased (all servers exhausted){C.RST}")

        print()
        print(f"  {C.DIM}⏱  Completed in {elapsed:.2f}s{C.RST}")

        # ── Step 4: Remaining balance ──
        print(f"  {C.CYN}▸ Checking remaining balance...{C.RST}")
        await check_balance(session)
        print()


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UOTP Bulk Number Buyer — purchase multiple virtual numbers at once.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 uotp_buy_numbers.py                     # Auto-buy 10 JIO numbers (cheapest first)
  python3 uotp_buy_numbers.py -n 5 --server 5     # Buy 5 from Server 5
  python3 uotp_buy_numbers.py --server 8           # Force Server 8 (₹14)
  python3 uotp_buy_numbers.py --service wa         # WhatsApp instead of JIO
        """,
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=DEFAULT_COUNT,
        help=f"Number of phone numbers to buy (default: {DEFAULT_COUNT})",
    )
    parser.add_argument(
        "--service", "-s",
        type=str,
        default=DEFAULT_SERVICE,
        help=f"Service code, e.g. 'jio' for My JIO, 'wa' for WhatsApp (default: {DEFAULT_SERVICE})",
    )
    parser.add_argument(
        "--country", "-c",
        type=str,
        default=DEFAULT_COUNTRY,
        help=f"Country code, e.g. '22' for India, '0' for any (default: {DEFAULT_COUNTRY})",
    )
    parser.add_argument(
        "--server", "-S",
        type=str,
        default="auto",
        help="Server number (1-8) or 'auto' to try cheapest first (default: auto)",
    )
    args = parser.parse_args()

    asyncio.run(buy_numbers_bulk(
        count=args.count,
        service=args.service,
        country=args.country,
        server=args.server,
    ))


if __name__ == "__main__":
    main()
