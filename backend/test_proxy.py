import asyncio
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("http://localhost:8000/api/v1/snapshot")
            print("8000:", r.status_code)
        except Exception as e:
            print("8000 failed")

asyncio.run(main())
