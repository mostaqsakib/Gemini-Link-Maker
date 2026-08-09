#!/usr/bin/env python3
"""Open an operator-supplied URL and save its rendered body text for debugging."""

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = PROJECT_DIR / "data" / "google_checker_profile"
DEFAULT_OUTPUT = PROJECT_DIR / "data" / "debug_page_text.txt"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Open an authorized URL and save its rendered page text."
    )
    parser.add_argument("url", help="URL you are authorized to inspect")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


async def capture_page_text(url, profile, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(5)
            output.write_text(await page.inner_text("body"), encoding="utf-8")
        finally:
            await context.close()


def main():
    args = build_parser().parse_args()
    asyncio.run(capture_page_text(args.url, args.profile, args.output))
    print(f"Saved rendered page text to: {args.output}")


if __name__ == "__main__":
    main()
