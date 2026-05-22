import asyncio
from main import async_session, OrganizationConfig

async def update_rules():
    async with async_session() as session:
        org = await session.get(OrganizationConfig, 1)
        if not org:
            print("Organizácia neexistuje")
            return
        
        rules = org.scoring_rules
        # Odstráň staré pravidlo has_contact_name (ak existuje)
        new_pos = [p for p in rules.get('positive_signals', []) if p.get('name') != 'has_contact_name']
        # Pridaj nové pravidlo contact_level (body sa budú pridávať priamo v skripte, nie cez eval)
        # Ponecháme len ako placeholder – body sa budú počítať v Python kóde
        rules['positive_signals'] = new_pos
        org.scoring_rules = rules
        await session.commit()
        print("Pravidlá boli resetované (odstránené has_contact_name).")

asyncio.run(update_rules())