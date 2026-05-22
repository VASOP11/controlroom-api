import asyncio
import csv
from sqlalchemy import select
from main import async_session, Lead

async def add_urls():
    # Najprv načítaj URL z CSV
    url_map = {}
    with open("leads.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nazov = row.get("nazov firmy", "").strip()
            url = row.get("url", "").strip()
            if nazov and url:
                url_map[nazov] = url
    
    async with async_session() as session:
        leads = await session.execute(select(Lead))
        leads = leads.scalars().all()
        updated = 0
        for lead in leads:
            if lead.primary_identifier in url_map:
                if not lead.lead_metadata:
                    lead.lead_metadata = {}
                lead.lead_metadata["url"] = url_map[lead.primary_identifier]
                lead.primary_url = url_map[lead.primary_identifier]
                updated += 1
                print(f"Pridaná URL pre {lead.primary_identifier}")
        await session.commit()
        print(f"Hotovo – aktualizovaných {updated} leadov")

asyncio.run(add_urls())