#!/usr/bin/env python3
"""Measure authorized Firebase database endpoints without storing responses."""

import argparse
import asyncio
import time

import aiohttp


async def check_url(session, firebase_url):
    base_url = firebase_url.rstrip("/")
    print(f"\nChecking: {base_url}")

    start = time.time()
    try:
        async with session.get(f"{base_url}/clients.json", timeout=15) as response:
            content = await response.read()
            elapsed = time.time() - start
            print(
                f"clients.json: HTTP {response.status}, "
                f"{len(content):,} bytes, {elapsed:.2f}s"
            )
    except Exception as exc:
        print(f"clients.json: {type(exc).__name__}")

    start = time.time()
    try:
        async with session.get(f"{base_url}/messages.json", timeout=15) as response:
            size = 0
            async for chunk in response.content.iter_chunked(1024 * 1024):
                size += len(chunk)
                if size > 5 * 1024 * 1024:
                    break
            elapsed = time.time() - start
            size_label = ">5,000,000" if size > 5 * 1024 * 1024 else f"{size:,}"
            print(
                f"messages.json: HTTP {response.status}, "
                f"{size_label} bytes, {elapsed:.2f}s"
            )
    except Exception as exc:
        print(f"messages.json: {type(exc).__name__}")


async def main(urls):
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(check_url(session, url) for url in urls))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "firebase_urls",
        nargs="+",
        help="Firebase base URLs you are authorized to inspect",
    )
    args = parser.parse_args()
    asyncio.run(main(args.firebase_urls))
