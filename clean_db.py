import asyncio
from sqlalchemy import select
from main import async_session, Lead

async def clean():
    async with async_session() as s:
        result = await s.execute(select(Lead))
        leads = result.scalars().all()
        to_delete = []
        for l in leads:
            name = l.primary_identifier or ''
            url = l.lead_metadata.get('url') if l.lead_metadata else None
            if name.startswith('Neznáma firma') or not url:
                to_delete.append(l)
        for l in to_delete:
            await s.delete(l)
        await s.commit()
        print(f'Zmazaných {len(to_delete)} neplatných leadov')

asyncio.run(clean())