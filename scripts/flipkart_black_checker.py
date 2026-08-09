#!/usr/bin/env python3
"""Check Flipkart Black membership for an account the operator controls.

The checker drives Flipkart's normal browser login, asks the operator for the
OTP without echoing it, reads the membership state returned by Flipkart's
post-login user-state request, and appends a sanitized CSV result.

It deliberately does not acquire phone numbers, scrape messages, bypass
challenges, or persist OTPs/cookies/session tokens.
"""

import argparse
import asyncio
import csv
import getpass
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_DIR / "data" / "flipkart_black_results.csv"

LOGIN_URL = "https://www.flipkart.com/account/login"
HOME_URL = "https://www.flipkart.com/"
OTP_GENERATE_PATH = "/api/7/user/otp/generate"
OTP_LOGIN_PATH = "/api/1/user/login/otp"
USER_STATE_PATH = "/4/user/state"
MEMBERSHIP_STATE_PATH = (
    "RESPONSE",
    "versionedData",
    "lockinResponse",
    "userMembershipState",
)

PHONE_INPUT_SELECTORS = (
    'input[autocomplete="tel"]',
    'input[type="tel"]',
    'input[name*="mobile" i]',
    'input[name*="phone" i]',
    'input[placeholder*="mobile" i]',
    'input[placeholder*="email" i]',
)
OTP_INPUT_SELECTORS = (
    'input[autocomplete="one-time-code"]',
    'input[name*="otp" i]',
    'input[placeholder*="otp" i]',
    'input[inputmode="numeric"]',
    'input[type="number"]',
)

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
INDIAN_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
OTP_IN_TEXT_PATTERN = re.compile(
    r"(?i)\b(otp|one[- ]time password)(\D{0,16})(\d{4,8})\b"
)


class OtpSource(Protocol):
    """Replaceable OTP source restricted to accounts the operator controls."""

    async def get_otp(self, phone: str) -> str:
        """Return the OTP for ``phone`` without persisting it."""


class PromptOtpSource:
    async def get_otp(self, phone: str) -> str:
        masked = mask_phone(phone)
        raw = await asyncio.to_thread(
            getpass.getpass,
            f"Enter the Flipkart OTP received by {masked}: ",
        )
        otp = re.sub(r"\D", "", raw)
        if not 4 <= len(otp) <= 8:
            raise ValueError("OTP must contain between 4 and 8 digits")
        return otp


@dataclass
class CheckResult:
    phone: str
    membership_state: str
    outcome: str
    error: str = ""

    @property
    def black_active(self) -> str:
        normalized = self.membership_state.upper()
        if normalized == "ACTIVE":
            return "yes"
        if normalized == "INACTIVE":
            return "no"
        return "unknown"


def normalize_indian_phone(raw_phone: str) -> str:
    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("Enter a valid 10-digit Indian mobile number")
    return digits


def mask_phone(phone: str) -> str:
    return f"+91******{phone[-4:]}"


def sanitize_text(value: str, phone: str = "", otp: str = "") -> str:
    sanitized = value
    if phone:
        sanitized = sanitized.replace(phone, "[REDACTED_PHONE]")
        sanitized = sanitized.replace(f"+91{phone}", "[REDACTED_PHONE]")
    if otp:
        sanitized = sanitized.replace(otp, "[REDACTED_OTP]")
    sanitized = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", sanitized)
    sanitized = INDIAN_PHONE_PATTERN.sub("[REDACTED_PHONE]", sanitized)
    return OTP_IN_TEXT_PATTERN.sub(r"\1\2[REDACTED_OTP]", sanitized)


def parse_membership_state(payload) -> str | None:
    current = payload
    for key in MEMBERSHIP_STATE_PATH:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]

    if not isinstance(current, str) or not current.strip():
        return None
    return current.strip().upper()


def append_csv_result(
    output: Path,
    result: CheckResult,
    *,
    include_full_phone: bool = False,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "checked_at_utc",
        "phone",
        "phone_masked",
        "membership_state",
        "black_active",
        "outcome",
        "error",
    )
    needs_header = not output.exists() or output.stat().st_size == 0

    with output.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if needs_header:
            writer.writeheader()
        writer.writerow(
            {
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "phone": f"+91{result.phone}" if include_full_phone else "",
                "phone_masked": mask_phone(result.phone),
                "membership_state": result.membership_state,
                "black_active": result.black_active,
                "outcome": result.outcome,
                "error": sanitize_text(result.error, result.phone),
            }
        )

    try:
        output.chmod(0o600)
    except OSError:
        pass


async def first_visible_locator(page, selectors, timeout_ms=1_500):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except Exception:
            continue
    return None


async def first_visible_button(page, names, timeout_ms=1_500):
    for name in names:
        locator = page.get_by_role("button", name=re.compile(name, re.I)).first
        try:
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except Exception:
            continue
    return None


async def fill_otp(page, otp: str) -> None:
    for selector in OTP_INPUT_SELECTORS:
        candidates = page.locator(selector)
        try:
            count = await candidates.count()
        except Exception:
            continue

        visible = []
        for index in range(count):
            candidate = candidates.nth(index)
            try:
                if await candidate.is_visible():
                    visible.append(candidate)
            except Exception:
                continue

        if not visible:
            continue

        if len(visible) >= len(otp):
            for candidate, digit in zip(visible, otp):
                await candidate.fill(digit)
            return

        await visible[0].fill(otp)
        return

    # Last-resort fallback for login layouts whose OTP input has no semantic
    # attributes. Avoid search and phone/email fields.
    candidates = page.locator("input")
    for index in range(await candidates.count()):
        candidate = candidates.nth(index)
        try:
            if not await candidate.is_visible():
                continue
            placeholder = (await candidate.get_attribute("placeholder") or "").lower()
            input_type = (await candidate.get_attribute("type") or "text").lower()
            if "search" in placeholder or "mobile" in placeholder or "email" in placeholder:
                continue
            if input_type in {"hidden", "search", "tel", "email"}:
                continue
            await candidate.fill(otp)
            return
        except Exception:
            continue

    raise RuntimeError("Could not locate the Flipkart OTP input")


async def wait_for_future(future, timeout_seconds):
    return await asyncio.wait_for(asyncio.shield(future), timeout=timeout_seconds)


async def check_membership(
    phone: str,
    otp_source: OtpSource,
    *,
    headless: bool = False,
) -> CheckResult:
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: "
            "venv/bin/python -m pip install playwright"
        ) from exc

    otp = ""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        loop = asyncio.get_running_loop()
        otp_generated = loop.create_future()
        login_completed = loop.create_future()
        membership_detected = loop.create_future()

        async def capture_response(response):
            try:
                if OTP_GENERATE_PATH in response.url and not otp_generated.done():
                    otp_generated.set_result(response.status)
                elif OTP_LOGIN_PATH in response.url and not login_completed.done():
                    login_completed.set_result(response.status)
                elif USER_STATE_PATH in response.url and response.status == 200:
                    payload = await response.json()
                    state = parse_membership_state(payload)
                    if state and not membership_detected.done():
                        membership_detected.set_result(state)
            except PlaywrightError:
                return
            except Exception:
                return

        page.on("response", capture_response)

        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

            phone_input = await first_visible_locator(page, PHONE_INPUT_SELECTORS)
            if phone_input is None:
                raise RuntimeError("Could not locate the Flipkart phone-number input")
            await phone_input.fill(phone)

            request_button = await first_visible_button(
                page,
                (r"request\s*otp", r"continue", r"next"),
            )
            if request_button is None:
                raise RuntimeError("Could not locate the Flipkart Request OTP button")
            await request_button.click()

            generate_status = await wait_for_future(otp_generated, 30)
            if generate_status != 200:
                raise RuntimeError(f"Flipkart OTP request failed with HTTP {generate_status}")

            otp = await otp_source.get_otp(phone)
            await fill_otp(page, otp)

            # Some Flipkart layouts submit automatically after the final OTP
            # digit; others show a Verify/Login button.
            await asyncio.sleep(1)
            if not login_completed.done():
                verify_button = await first_visible_button(
                    page,
                    (r"verify", r"log\s*in", r"continue", r"submit"),
                    timeout_ms=1_000,
                )
                if verify_button is not None:
                    await verify_button.click()

            login_status = await wait_for_future(login_completed, 30)
            if login_status != 200:
                raise RuntimeError(f"Flipkart rejected the OTP with HTTP {login_status}")

            try:
                membership_state = await wait_for_future(membership_detected, 30)
            except asyncio.TimeoutError:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
                membership_state = await wait_for_future(membership_detected, 30)

            return CheckResult(
                phone=phone,
                membership_state=membership_state,
                outcome="classified",
            )
        except Exception as exc:
            return CheckResult(
                phone=phone,
                membership_state="UNKNOWN",
                outcome="error",
                error=sanitize_text(str(exc), phone, otp),
            )
        finally:
            try:
                page.remove_listener("response", capture_response)
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check Flipkart Black membership for a phone/account you are "
            "authorized to access."
        )
    )
    parser.add_argument(
        "--phone",
        help=(
            "Authorized Indian mobile number. Omit to enter it interactively "
            "and keep it out of shell history."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"CSV output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium without a visible window.",
    )
    parser.add_argument(
        "--include-full-phone",
        action="store_true",
        help="Store the full phone number in CSV instead of only its masked form.",
    )
    return parser


async def async_main(args) -> int:
    raw_phone = args.phone
    if not raw_phone:
        raw_phone = await asyncio.to_thread(input, "Authorized Indian mobile number: ")

    try:
        phone = normalize_indian_phone(raw_phone)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    result = await check_membership(
        phone,
        PromptOtpSource(),
        headless=args.headless,
    )
    output = args.output
    if not output.is_absolute():
        output = PROJECT_DIR / output
    append_csv_result(
        output,
        result,
        include_full_phone=args.include_full_phone,
    )

    print(f"Phone: {mask_phone(phone)}")
    print(f"Membership state: {result.membership_state}")
    print(f"Black active: {result.black_active}")
    print(f"Result saved to: {output}")
    if result.error:
        print(f"Error: {result.error}")
        return 1
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(async_main(args)))
    except KeyboardInterrupt:
        raise SystemExit("\nCancelled by operator")


if __name__ == "__main__":
    main()
