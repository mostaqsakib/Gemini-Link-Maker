#!/usr/bin/env python3
"""Send one authorized Jio OTP request and report its HTTP status.

This diagnostic intentionally performs one request only. It is not a load or
rate-limit bypass tool.
"""

import argparse
import asyncio
import re

import aiohttp


def normalize_phone(raw_phone):
    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10:
        raise ValueError("Expected a 10-digit Indian mobile number")
    return digits


async def check_once(phone):
    headers = {
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        "referer": "https://www.jio.com/selfcare/login/",
    }
    payload = {
        "mobileNumber": phone,
        "loginFlowType": "MOBILE",
        "alternateNumber": "",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            "https://www.jio.com/api/jio-login-service/login/sendOtp",
            json=payload,
            timeout=15,
        ) as response:
            print(f"Jio sendOtp returned HTTP {response.status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", required=True, help="A Jio number you own")
    parser.add_argument(
        "--i-own-this-number",
        action="store_true",
        help="Required confirmation that the number is yours",
    )
    args = parser.parse_args()
    if not args.i_own_this_number:
        raise SystemExit("Pass --i-own-this-number to confirm authorization.")
    asyncio.run(check_once(normalize_phone(args.phone)))
