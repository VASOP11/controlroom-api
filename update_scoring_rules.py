import asyncio
import json
from main import async_session, OrganizationConfig

async def update():
    async with async_session() as session:
        org = await session.get(OrganizationConfig, 1)
        if not org:
            print("Organizácia s org_id=1 neexistuje")
            return
        
        rules = {
            "positive_signals": [
                {"name": "has_phone", "points": 30, "condition": "bool(lead_data.get('lead_metadata', {}).get('phone') or lead_data.get('contact_channels', {}).get('phone))"},
                {"name": "has_email", "points": 15, "condition": "bool(lead_data.get('lead_metadata', {}).get('email') or lead_data.get('contact_channels', {}).get('email'))"},
                {"name": "good_role", "points": 20, "condition": "any(word in str(lead_data.get('lead_metadata', {}).get('role', '')).lower() for word in ['ceo', 'obchod', 'riaditeľ', 'konateľ', 'jednateľ'])"},
                {"name": "positive_note", "points": 25, "condition": "any(word in str(lead_data.get('lead_metadata', {}).get('notes', '')).lower() for word in ['záujem', 'pacilo', 'registrovať', 'ok', 'dobre', 'áno'])"},
                {"name": "has_platform", "points": 10, "condition": "len(lead_data.get('platform_presence', {}).get('platforms', [])) >= 1"},
                {"name": "good_vertical", "points": 5, "condition": "lead_data.get('vertical') in ['Home & Garden', 'Beauty', 'Pet', 'Sport', 'Auto-moto', 'Beauty & Personal Care', 'Pet Supplies']"},
                {"name": "extra_platform", "points": 10, "condition": "len(lead_data.get('platform_presence', {}).get('platforms', [])) >= 2"}
            ],
            "negative_signals": [
                {"name": "negative_note", "points": -30, "condition": "any(word in str(lead_data.get('lead_metadata', {}).get('notes', '')).lower() for word in ['nechce', 'nezáujem', 'nezdviha', 'nedostupný'])"},
                {"name": "no_role", "points": -10, "condition": "not lead_data.get('lead_metadata', {}).get('role')"},
                {"name": "no_phone_no_email", "points": -20, "condition": "not (lead_data.get('lead_metadata', {}).get('phone') or lead_data.get('lead_metadata', {}).get('email'))"}
            ]
        }
        
        org.scoring_rules = rules
        await session.commit()
        print("Scoring pravidlá boli úspešne aktualizované.")

asyncio.run(update())