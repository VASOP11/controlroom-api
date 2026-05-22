import asyncio
from sqlalchemy import text
from main import engine

async def add():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS rule_score INTEGER"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS ai_adjustment INTEGER"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS final_score INTEGER"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS tier VARCHAR"))
        print("OK")

asyncio.run(add())