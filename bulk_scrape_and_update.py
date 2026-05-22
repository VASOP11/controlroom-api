import asyncio
import re
from scrapling.fetchers import StealthyFetcher
from sqlalchemy import select
from main import async_session, Lead, OrganizationConfig, evaluate_lead

def rate_contact(phone, email, name):
    """
    Vráti (body, úroveň) podľa zistených kontaktov.
    level 0: nič
    level 1: len email (aj generický) alebo len telefón
    level 2: telefón + meno (aspoň dve slová začínajúce veľkým písmenom)
    level 3: meno + priamy email (nie info@, obchod@) + telefón
    """
    has_phone = bool(phone)
    has_email = bool(email)
    has_name = bool(name and len(name.split()) >= 2)
    is_direct_email = False
    if has_email and email:
        local = email.split('@')[0].lower()
        if local not in ['info', 'obchod', 'sales', 'support', 'contact']:
            is_direct_email = True
    
    if has_name and has_phone and is_direct_email:
        return 45, 3
    elif has_name and has_phone:
        return 30, 2
    elif has_phone or has_email:
        return 15, 1
    else:
        return 0, 0

async def extract_contact_info(url):
    """Vráti (telefón, email, meno_osoby, level, body)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=30)
        text = page.css("body::text").get(default="")
        
        # Telefón
        phone = None
        phone_match = re.search(r'(\+421|\+420|0)\d{9,12}', text)
        if phone_match:
            phone = phone_match.group(0)
        
        # Email
        email = None
        mailto = page.css('a[href^="mailto:"]::attr(href)').get()
        if mailto:
            email = mailto.replace("mailto:", "")
        if not email:
            email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
            if email_match:
                email = email_match.group(0)
        
        # Meno osoby
        name = None
        if phone:
            phone_pos = text.find(phone)
            if phone_pos != -1:
                surrounding = text[max(0, phone_pos-80):min(len(text), phone_pos+80)]
                name_match = re.search(r'([A-Z][a-z]+ [A-Z][a-z]+)', surrounding)
                if name_match:
                    name = name_match.group(1)
        if not name:
            kontakt_section = page.find_by_text("Kontakt|Kontakty|Manažér|Ředitel", tag='div', case_insensitive=True)
            if kontakt_section:
                section_text = kontakt_section.text()
                name_match = re.search(r'([A-Z][a-z]+ [A-Z][a-z]+)', section_text)
                if name_match:
                    name = name_match.group(1)
        
        points, level = rate_contact(phone, email, name)
        return phone, email, name, level, points
    except Exception as e:
        print(f"Chyba pri scrapovaní {url}: {e}")
        return None, None, None, 0, 0

async def update_all_leads():
    async with async_session() as session:
        leads = await session.execute(select(Lead))
        leads = leads.scalars().all()
        
        org_result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == 1))
        org_config = org_result.scalar_one()
        thresholds = org_config.tier_thresholds
        
        for lead in leads:
            url = lead.lead_metadata.get("url") if lead.lead_metadata else None
            if not url:
                continue
            print(f"Spracúvam {lead.primary_identifier}: {url}")
            
            phone, email, name, level, points = await extract_contact_info(url)
            updated = False
            
            if phone and (not lead.contact_channels.get("phone")):
                lead.contact_channels["phone"] = phone
                updated = True
                print(f"  Telefón: {phone}")
            if email and (not lead.contact_channels.get("email")):
                lead.contact_channels["email"] = email
                updated = True
                print(f"  Email: {email}")
            if name:
                if not lead.lead_metadata:
                    lead.lead_metadata = {}
                lead.lead_metadata["contact_name"] = name
                lead.lead_metadata["contact_level"] = level
                updated = True
                print(f"  Meno: {name} (úroveň {level}, +{points} bodov)")
            
            if updated:
                # Priprav lead_data pre evaluate_lead
                lead_data = {
                    "primary_identifier": lead.primary_identifier,
                    "vertical": lead.vertical,
                    "platform_presence": lead.platform_presence,
                    "value_indicators": lead.value_indicators,
                    "contact_channels": lead.contact_channels,
                    "lead_metadata": lead.lead_metadata
                }
                base_score = evaluate_lead(lead_data, org_config.scoring_rules)
                final_score = base_score + points
                final_score = max(0, min(100, final_score))
                lead.rule_score = base_score
                lead.final_score = final_score
                # Tier
                if final_score >= thresholds["HOT"]:
                    lead.tier = "HOT"
                elif final_score >= thresholds["WARM"]:
                    lead.tier = "WARM"
                elif final_score >= thresholds["COOL"]:
                    lead.tier = "COOL"
                else:
                    lead.tier = "DEAD"
                print(f"  Základ: {base_score} + kontakt: {points} = {final_score} ({lead.tier})")
        
        await session.commit()
        print("Hotovo – všetci leadi boli aktualizovaní.")

if __name__ == "__main__":
    asyncio.run(update_all_leads())