import asyncio
from main import async_session, OrganizationConfig

async def update():
    async with async_session() as session:
        org = await session.get(OrganizationConfig, 1)
        if not org:
            print("Organizácia neexistuje")
            return
        rules = org.scoring_rules
        # Odstrán staré pravidlo has_contact_name (ak existuje)
        new_pos = [p for p in rules.get("positive_signals", []) if p.get("name") != "has_contact_name"]
        # Pridaj nové pravidlo contact_level (body sa budú počítať v skripte)
        new_pos.append({"name": "contact_level", "points": 0, "condition": "True"})
        rules["positive_signals"] = new_pos
        org.scoring_rules = rules
        await session.commit()
        print("Pravidlá aktualizované – has_contact_name odstránené, contact_level pridané.")

asyncio.run(update())