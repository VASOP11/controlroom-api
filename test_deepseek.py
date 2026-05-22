import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

async def test():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("No DEEPSEEK_API_KEY in .env")
        return
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "Return ONLY a number between -20 and 20, nothing else."}],
        "max_tokens": 10,
        "temperature": 0
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=30)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")

asyncio.run(test())
