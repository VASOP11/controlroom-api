import asyncio
from main import async_session, EmailTemplate

async def add():
    async with async_session() as s:
        s.add(EmailTemplate(
            org_id=1,
            name="Prvý kontakt",
            subject="Spolupráca s {company}",
            body_template="Dobrý deň, videl som vašu firmu {company}..."
        ))
        await s.commit()
        print("Šablóna pridaná")

asyncio.run(add())