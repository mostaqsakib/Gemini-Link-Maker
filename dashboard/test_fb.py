import asyncio
import aiohttp

async def test():
    async with aiohttp.ClientSession() as session:
        url = "https://u62751482-f5b46-default-rtdb.firebaseio.com/messages.json?shallow=true"
        async with session.get(url) as resp:
            data = await resp.json()
            if not data:
                print("no messages")
                return
            dev_id = list(data.keys())[0]
            
        url2 = f"https://u62751482-f5b46-default-rtdb.firebaseio.com/messages/{dev_id}.json?orderBy=%22$key%22&limitToLast=15"
        async with session.get(url2) as resp:
            data2 = await resp.json()
            print("limitToLast returned items:", len(data2) if isinstance(data2, dict) else type(data2))

asyncio.run(test())
