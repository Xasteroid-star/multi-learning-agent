"""Test all possible DeepSeek endpoints."""
import asyncio, time
from openai import OpenAI

KEY = "sk-590ade8ba27a479ba4da6b540c86da46"
MODEL = "deepseek-v4-pro[1m]"

urls = [
    "https://api.deepseek.com",
    "https://api.deepseek.com/v1",
    "https://api.openai.com/v1",
]

async def test():
    for url in urls:
        print(f"\nTesting: {url} ...", end=" ", flush=True)
        try:
            client = OpenAI(api_key=KEY, base_url=url)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "say hi"}],
                timeout=5.0,
            )
            print(f"OK: {response.choices[0].message.content} (model used: {response.model})")
        except Exception as e:
            print(f"FAIL: {type(e).__name__}: {str(e)[:100]}")

    # Try with the actual model
    print(f"\nTesting with model={MODEL} at https://api.deepseek.com ...", end=" ", flush=True)
    try:
        client = OpenAI(api_key=KEY, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "你好，1+1等于几？"}],
            timeout=10.0,
        )
        print(f"OK: {response.choices[0].message.content}")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {str(e)[:150]}")

asyncio.run(test())
