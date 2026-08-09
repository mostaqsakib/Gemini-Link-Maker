#!/usr/bin/env python3
"""Inspect an authorized Firebase message tree with shallow reads."""

import argparse
import asyncio

import aiohttp


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "firebase_url",
        help="Authorized Firebase Realtime Database base URL",
    )
    return parser


async def inspect(firebase_url):
    base_url = firebase_url.rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base_url}/messages.json?shallow=true",
            timeout=15,
        ) as response:
            data = await response.json()
            if not data:
                print("No messages")
                return
            device_id = next(iter(data))

        async with session.get(
            f"{base_url}/messages/{device_id}.json"
            "?orderBy=%22$key%22&limitToLast=15",
            timeout=15,
        ) as response:
            messages = await response.json()
            count = len(messages) if isinstance(messages, dict) else 0
            print(f"limitToLast returned items: {count}")


if __name__ == "__main__":
    arguments = build_parser().parse_args()
    asyncio.run(inspect(arguments.firebase_url))
