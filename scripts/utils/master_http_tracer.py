#!/usr/bin/env python3
"""Capture browser HTTP requests for manual login-flow debugging.

The tracer intentionally redacts credentials, cookies, tokens, passwords, and
OTP values before writing anything to disk.
"""

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROJECT_DIR = Path(__file__).resolve().parents[2]
TRACE_DIR = PROJECT_DIR / "data" / "http_traces"
CAPTURED_RESOURCE_TYPES = {"document", "fetch", "xhr"}
MAX_JSON_RESPONSE_CHARS = 500_000

PRESETS = {
    "jio": {
        "url": "https://www.jio.com/selfcare/login/",
        "domains": ["jio.com", "serviceactivation.google.com"],
    },
    "chatgpt": {
        "url": "https://chatgpt.com/auth/login",
        "domains": ["chatgpt.com", "openai.com"],
    },
    "flipkart": {
        "url": "https://www.flipkart.com/account/login",
        "domains": ["flipkart.com", "flipkart.net"],
    },
}

SENSITIVE_KEYS = {
    "access_token",
    "accesstoken",
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "code",
    "cookie",
    "credential",
    "id_token",
    "idtoken",
    "jwt",
    "login_id",
    "loginid",
    "mobile",
    "mobile_number",
    "mobilenumber",
    "otp",
    "pass",
    "password",
    "phone",
    "phone_number",
    "phonenumber",
    "refresh_token",
    "refreshtoken",
    "secret",
    "session",
    "session_id",
    "sessionid",
    "set-cookie",
    "token",
    "username",
}

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
INDIAN_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
OTP_IN_TEXT_PATTERN = re.compile(
    r"(?i)\b(otp|one[- ]time password)(\D{0,16})(\d{4,8})\b"
)


def redact_text(value):
    value = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
    value = INDIAN_PHONE_PATTERN.sub("[REDACTED_PHONE]", value)
    return OTP_IN_TEXT_PATTERN.sub(r"\1\2[REDACTED_OTP]", value)


def is_sensitive_key(key):
    normalized = re.sub(r"[^a-z0-9_-]", "", str(key).lower())
    return normalized in SENSITIVE_KEYS or any(
        marker in normalized
        for marker in (
            "api-key",
            "apikey",
            "authorization",
            "cookie",
            "email",
            "loginid",
            "mobile",
            "password",
            "passwd",
            "phone",
            "token",
            "secret",
            "credential",
            "username",
        )
    )


def redact_mapping(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            safe_key = redact_text(str(key))
            redacted[safe_key] = (
                "[REDACTED]" if is_sensitive_key(key) else redact_mapping(item)
            )
        return redacted
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_url(url):
    try:
        parts = urlsplit(url)
        query = urlencode(
            [
                (key, "[REDACTED]" if is_sensitive_key(key) else value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
            ],
            doseq=True,
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except ValueError:
        return url


def redact_post_data(post_data):
    if not post_data:
        return None

    try:
        return json.dumps(redact_mapping(json.loads(post_data)), ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        fields = parse_qsl(post_data, keep_blank_values=True, strict_parsing=True)
        return urlencode(
            [
                (key, "[REDACTED]" if is_sensitive_key(key) else value)
                for key, value in fields
            ]
        )
    except ValueError:
        # Best-effort redaction for non-JSON/non-form request bodies.
        pattern = re.compile(
            r'(?i)(password|passwd|otp|token|secret|credential)(["\']?\s*[:=]\s*["\']?)([^&,\s"\']+)'
        )
        return pattern.sub(r"\1\2[REDACTED]", post_data)


def redact_headers(headers):
    return {
        key: "[REDACTED]" if is_sensitive_key(key) else value
        for key, value in headers.items()
    }


def hostname_matches(url, domains):
    try:
        hostname = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False

    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in domains
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Capture and safely redact HTTP requests from a manual browser flow."
    )
    parser.add_argument(
        "preset",
        nargs="?",
        default="custom",
        choices=[*PRESETS, "custom"],
        help="Known login flow to trace (default: custom).",
    )
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        help="Starting URL. Repeat to open multiple tabs.",
    )
    parser.add_argument(
        "--domain",
        action="append",
        dest="domains",
        help="Domain to capture, including subdomains. Repeat as needed.",
    )
    parser.add_argument(
        "--all-domains",
        action="store_true",
        help="Capture requests to every domain (third-party traffic included).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path. Defaults to data/http_traces/<preset>_<time>.json.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Stop automatically after this many seconds (default: wait until browser closes).",
    )
    parser.add_argument(
        "--include-json-responses",
        action="store_true",
        help=(
            "Also capture redacted JSON response bodies up to 500 KB. "
            "Useful for locating account-state fields."
        ),
    )
    return parser


def resolve_config(args, parser):
    preset = PRESETS.get(args.preset, {})
    urls = args.urls or ([preset["url"]] if preset else [])
    configured_domains = [*preset.get("domains", []), *(args.domains or [])]
    domains = list(
        dict.fromkeys(domain.lower().lstrip("*.") for domain in configured_domains)
    )

    if not urls:
        parser.error("custom mode requires at least one --url")
    if not args.all_domains and not domains:
        parser.error("custom mode requires at least one --domain or --all-domains")
    if args.timeout < 0:
        parser.error("--timeout must be zero or greater")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or TRACE_DIR / f"{args.preset}_{timestamp}.json"
    if not output.is_absolute():
        output = PROJECT_DIR / output
    return urls, domains, output


async def trace(args, urls, domains, output):
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Playwright is not installed for this Python environment.\n"
            "Install it with:\n"
            "  python3 -m pip install playwright\n"
            "  python3 -m playwright install chromium"
        ) from exc

    records = []
    write_lock = asyncio.Lock()
    stopped = asyncio.Event()

    output.parent.mkdir(parents=True, exist_ok=True)

    async def save_trace():
        async with write_lock:
            temporary = output.with_suffix(f"{output.suffix}.tmp")
            temporary.write_text(
                json.dumps(records, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(output)

    async def capture_request(request):
        if request.resource_type not in CAPTURED_RESOURCE_TYPES:
            return
        if not args.all_domains and not hostname_matches(request.url, domains):
            return

        try:
            headers = await request.all_headers()
            record = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "direction": "request",
                "url": redact_url(request.url),
                "method": request.method,
                "resource_type": request.resource_type,
                "headers": redact_headers(headers),
                "post_data": redact_post_data(request.post_data),
            }
        except PlaywrightError as exc:
            # Normal shutdown race: Chromium can close while Playwright is
            # resolving the final request's raw headers.
            if "closed" not in str(exc).lower():
                print(f"Skipped request metadata: {type(exc).__name__}")
            return

        records.append(record)
        await save_trace()
        print(f"Captured: {record['method']} {record['url']}")

    async def capture_response(response):
        if not args.include_json_responses:
            return

        request = response.request
        if request.resource_type not in CAPTURED_RESOURCE_TYPES:
            return
        if not args.all_domains and not hostname_matches(response.url, domains):
            return

        try:
            headers = await response.all_headers()
            content_type = headers.get("content-type", "").lower()
            if "json" not in content_type:
                return

            body_text = await response.text()
            if len(body_text) > MAX_JSON_RESPONSE_CHARS:
                body = "[OMITTED: JSON response exceeds 500 KB]"
            else:
                try:
                    body = redact_mapping(json.loads(body_text))
                except json.JSONDecodeError:
                    body = redact_text(body_text)

            record = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "direction": "response",
                "url": redact_url(response.url),
                "status": response.status,
                "resource_type": request.resource_type,
                "headers": redact_headers(headers),
                "body": body,
            }
        except PlaywrightError as exc:
            if "closed" not in str(exc).lower():
                print(f"Skipped response metadata: {type(exc).__name__}")
            return

        records.append(record)
        await save_trace()
        print(f"Captured response: {record['status']} {record['url']}")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        context.on("request", capture_request)
        context.on("response", capture_response)
        browser.on("disconnected", lambda: stopped.set())

        for url in urls:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        print("\nMaster HTTP Tracer is running.")
        print(f"Preset: {args.preset}")
        print("Domains:", "ALL" if args.all_domains else ", ".join(domains))
        print(f"Trace file: {output}")
        print("Complete the flow manually, then close the browser window.")
        print("Sensitive headers and body fields are redacted before saving.\n")

        try:
            if args.timeout:
                await asyncio.wait_for(stopped.wait(), timeout=args.timeout)
            else:
                await stopped.wait()
        except asyncio.TimeoutError:
            print(f"Stopping after {args.timeout} seconds.")
        except KeyboardInterrupt:
            print("\nStopping tracer.")
        finally:
            await save_trace()
            if browser.is_connected():
                await browser.close()

    print(f"Saved {len(records)} requests to: {output}")


def main():
    parser = build_parser()
    args = parser.parse_args()
    urls, domains, output = resolve_config(args, parser)
    try:
        asyncio.run(trace(args, urls, domains, output))
    except KeyboardInterrupt:
        print("\nTracer stopped.")


if __name__ == "__main__":
    main()
