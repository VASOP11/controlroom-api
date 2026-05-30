import os
import uuid
import datetime
import re
import json
import asyncio
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, JSON, DateTime, func, select
import requests
from bs4 import BeautifulSoup
from openai import AzureOpenAI
import cloudscraper
import chardet
import ftfy

print("ENCODING FIX v3 loaded (ftfy mojibake repair)")

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# --- Azure OpenAI klient ---
openai_client = AzureOpenAI(
    azure_endpoint=os.getenv("OPENAI_ENDPOINT"),
    api_key=os.getenv("OPENAI_API_KEY"),
    api_version="2024-12-01-preview"
)
GPT_DEPLOYMENT = os.getenv("OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")

# --- ScrapingBee API kľúč (voliteľný) ---
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY")

# --- SQLAlchemy modely (nezmenené) ---
class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String, unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    org_id = Column(Integer, nullable=False, default=1)
    primary_identifier = Column(String, nullable=False)
    primary_url = Column(String, nullable=True)
    contact_channels = Column(JSON, default={})
    vertical = Column(String, nullable=True)
    platform_presence = Column(JSON, default={})
    value_indicators = Column(JSON, default={})
    engagement_signals = Column(JSON, default={})
    differentiation_signals = Column(JSON, default={})
    risk_signals = Column(JSON, default={})
    lead_metadata = Column(JSON, default={})
    raw_data = Column(JSON, default={})
    rule_score = Column(Integer, default=0)
    ai_adjustment = Column(Integer, nullable=True)
    final_score = Column(Integer, default=0)
    tier = Column(String, default="DEAD")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class OrganizationConfig(Base):
    __tablename__ = "organization_config"
    org_id = Column(Integer, primary_key=True)
    target_icp_description = Column(String, nullable=False)
    scoring_rules = Column(JSON, nullable=False)
    ai_prompt_template = Column(String, nullable=True)
    tier_thresholds = Column(JSON, nullable=False)
    custom_taxonomy = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body_template = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

# --- Inicializácia DB a seed ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def seed_orgs():
    async with async_session() as session:
        result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == 1))
        if not result.scalar_one_or_none():
            org1 = OrganizationConfig(
                org_id=1,
                target_icp_description="SK/CZ e-commerce sellers active on multiple marketplaces, monthly revenue €5-30k, categories: Home & Garden, Beauty, Pet, Sport. Avoid premium/luxury, electronics, dropshipping",
                scoring_rules={
                    "positive_signals": [
                        {"name": "active_on_2plus_platforms", "points": 25, "condition": "len(lead_data.get('platform_presence', {}).get('platforms', [])) >= 2"},
                        {"name": "in_target_value_band", "points": 20, "condition": "lead_data.get('value_indicators', {}).get('estimated_value', {}).get('amount', 0) >= 5000 and lead_data.get('value_indicators', {}).get('estimated_value', {}).get('amount', 0) <= 30000"},
                        {"name": "in_target_vertical", "points": 20, "condition": "lead_data.get('vertical') in ['Home & Garden', 'Beauty', 'Pet', 'Sport', 'Auto-moto']"},
                        {"name": "ceo_or_director_contact", "points": 20, "condition": "any(kw in (lead_data.get('lead_metadata', {}).get('contact_role') or '').lower() for kw in ['ceo', 'riaditeľ', 'riaditel', 'director', 'konateľ', 'konatel'])"},
                        {"name": "has_named_contact", "points": 10, "condition": "bool(lead_data.get('lead_metadata', {}).get('contact_name'))"}
                    ],
                    "negative_signals": [
                        {"name": "outside_target_vertical", "points": -25, "condition": "lead_data.get('vertical') not in ['Home & Garden', 'Beauty', 'Pet', 'Sport', 'Auto-moto'] and lead_data.get('vertical') is not None"}
                    ]
                },
                ai_prompt_template=None,
                tier_thresholds={"HOT": 80, "WARM": 60, "COOL": 40, "DEAD": 0},
                custom_taxonomy={"verticals": ["Home & Garden", "Beauty", "Pet", "Sport", "Auto-moto"], "platforms": ["Heureka", "Mall", "Allegro", "eMag"]}
            )
            session.add(org1)
        result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == 2))
        if not result.scalar_one_or_none():
            org2 = OrganizationConfig(
                org_id=2,
                target_icp_description="Senior software engineers (10+ years), based in EU/US, with experience at Series B+ startups. Active on LinkedIn, contributing to open source. Avoid junior, freelancers, agencies",
                scoring_rules={
                    "positive_signals": [
                        {"name": "open_source_contributor", "points": 30, "condition": "lead_data.get('differentiation_signals', {}).get('open_source', False)"},
                        {"name": "linkedin_active", "points": 20, "condition": "'linkedin' in lead_data.get('contact_channels', {})"}
                    ],
                    "negative_signals": [
                        {"name": "junior_title", "points": -20, "condition": "'junior' in lead_data.get('primary_identifier', '').lower()"}
                    ]
                },
                ai_prompt_template=None,
                tier_thresholds={"HOT": 80, "WARM": 60, "COOL": 40, "DEAD": 0},
                custom_taxonomy={"verticals": ["Engineering", "Product", "Design"], "platforms": ["LinkedIn", "GitHub"]}
            )
            session.add(org2)
        await session.commit()

# --- Rule-based scoring evaluator ---
def evaluate_lead(lead_data: dict, scoring_rules: dict) -> int:
    score = 0
    for sig in scoring_rules.get("positive_signals", []):
        try:
            if eval(sig["condition"], {"lead_data": lead_data}):
                score += sig["points"]
        except Exception:
            continue
    for sig in scoring_rules.get("negative_signals", []):
        try:
            if eval(sig["condition"], {"lead_data": lead_data}):
                score += sig["points"]
        except Exception:
            continue
    return max(0, min(100, score))

# --- FastAPI app ---
app = FastAPI(title="ControlRoom MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

def verify_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    if token == "test-token":
        return {"sub": "org_1"}
    raise HTTPException(status_code=403, detail="Invalid token")

@app.on_event("startup")
async def startup():
    await init_db()
    await seed_orgs()

@app.get("/health")
async def health():
    return {"status": "ok"}

# ---- CRUD pre leadov ----
class LeadCreate(BaseModel):
    lead_data: dict

@app.post("/api/leads")
async def create_lead(lead_in: LeadCreate, user=Depends(verify_jwt)):
    org_id = 1
    async with async_session() as session:
        result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == org_id))
        org_config = result.scalar_one_or_none()
        if not org_config:
            raise HTTPException(status_code=404, detail="Organization config not found")
    rule_score = evaluate_lead(lead_in.lead_data, org_config.scoring_rules)
    final_score = rule_score
    thresholds = org_config.tier_thresholds
    if final_score >= thresholds["HOT"]: tier = "HOT"
    elif final_score >= thresholds["WARM"]: tier = "WARM"
    elif final_score >= thresholds["COOL"]: tier = "COOL"
    else: tier = "DEAD"
    new_lead = Lead(
        lead_id=str(uuid.uuid4()),
        primary_identifier=lead_in.lead_data.get("primary_identifier", "Unknown"),
        vertical=lead_in.lead_data.get("vertical"),
        platform_presence=lead_in.lead_data.get("platform_presence", {}),
        value_indicators=lead_in.lead_data.get("value_indicators", {}),
        lead_metadata=lead_in.lead_data,
        rule_score=rule_score,
        final_score=final_score,
        tier=tier
    )
    async with async_session() as session:
        session.add(new_lead)
        await session.commit()
        await session.refresh(new_lead)
    return new_lead

@app.get("/api/leads")
async def get_leads(user=Depends(verify_jwt)):
    async with async_session() as session:
        result = await session.execute(select(Lead))
        leads = result.scalars().all()
        return leads

@app.get("/api/leads/{lead_id}")
async def get_lead(lead_id: int, user=Depends(verify_jwt)):
    async with async_session() as session:
        lead = await session.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return lead

@app.put("/api/leads/{lead_id}")
async def update_lead(lead_id: int, lead_in: LeadCreate, user=Depends(verify_jwt)):
    async with async_session() as session:
        lead = await session.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        org_id = 1
        result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == org_id))
        org_config = result.scalar_one_or_none()
        if not org_config:
            raise HTTPException(status_code=404, detail="Organization config not found")
        rule_score = evaluate_lead(lead_in.lead_data, org_config.scoring_rules)
        final_score = rule_score + (lead.ai_adjustment if lead.ai_adjustment else 0)
        final_score = max(0, min(100, final_score))
        thresholds = org_config.tier_thresholds
        if final_score >= thresholds["HOT"]: tier = "HOT"
        elif final_score >= thresholds["WARM"]: tier = "WARM"
        elif final_score >= thresholds["COOL"]: tier = "COOL"
        else: tier = "DEAD"
        lead.primary_identifier = lead_in.lead_data.get("primary_identifier", lead.primary_identifier)
        lead.vertical = lead_in.lead_data.get("vertical", lead.vertical)
        lead.platform_presence = lead_in.lead_data.get("platform_presence", lead.platform_presence)
        lead.value_indicators = lead_in.lead_data.get("value_indicators", lead.value_indicators)
        lead.lead_metadata = lead_in.lead_data
        lead.rule_score = rule_score
        lead.final_score = final_score
        lead.tier = tier
        await session.commit()
        await session.refresh(lead)
        return lead

@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: int, user=Depends(verify_jwt)):
    async with async_session() as session:
        lead = await session.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        await session.delete(lead)
        await session.commit()
        return {"ok": True}

# ---- Bulk scoring ----
class BulkLeadItem(BaseModel):
    lead_id: str
    lead_data: dict

class BulkScoreRequest(BaseModel):
    leads: List[BulkLeadItem]

class BulkScoreResponseItem(BaseModel):
    lead_id: str
    rule_score: int
    ai_adjustment: Optional[int] = None
    final_score: int
    tier: str

@app.post("/api/leads/score/bulk")
async def bulk_score(request: BulkScoreRequest, user=Depends(verify_jwt)):
    org_id = 1
    async with async_session() as session:
        result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == org_id))
        org_config = result.scalar_one_or_none()
        if not org_config:
            raise HTTPException(status_code=404, detail="Organization config not found")
    results = []
    for item in request.leads:
        rule_score = evaluate_lead(item.lead_data, org_config.scoring_rules)
        final_score = rule_score
        thresholds = org_config.tier_thresholds
        if final_score >= thresholds["HOT"]: tier = "HOT"
        elif final_score >= thresholds["WARM"]: tier = "WARM"
        elif final_score >= thresholds["COOL"]: tier = "COOL"
        else: tier = "DEAD"
        results.append(BulkScoreResponseItem(
            lead_id=item.lead_id,
            rule_score=rule_score,
            final_score=final_score,
            tier=tier
        ))
    return {"results": results}

# ---- Manuálny AI adjustment ----
class AdjustRequest(BaseModel):
    ai_adjustment: int

@app.post("/api/leads/{lead_id}/adjust")
async def adjust_lead(lead_id: int, req: AdjustRequest, user=Depends(verify_jwt)):
    if req.ai_adjustment < -20 or req.ai_adjustment > 20:
        raise HTTPException(status_code=400, detail="Adjustment must be between -20 and 20")
    async with async_session() as session:
        lead = await session.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        lead.ai_adjustment = req.ai_adjustment
        new_final = lead.rule_score + req.ai_adjustment
        lead.final_score = max(0, min(100, new_final))
        org_result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == 1))
        org_config = org_result.scalar_one_or_none()
        if org_config:
            thresholds = org_config.tier_thresholds
            if lead.final_score >= thresholds["HOT"]: lead.tier = "HOT"
            elif lead.final_score >= thresholds["WARM"]: lead.tier = "WARM"
            elif lead.final_score >= thresholds["COOL"]: lead.tier = "COOL"
            else: lead.tier = "DEAD"
        await session.commit()
        await session.refresh(lead)
        return lead

# ---- Email templates ----
class EmailTemplateCreate(BaseModel):
    name: str
    subject: str
    body_template: str

@app.get("/api/email/templates")
async def list_templates(user=Depends(verify_jwt)):
    async with async_session() as session:
        result = await session.execute(select(EmailTemplate).where(EmailTemplate.org_id == 1))
        templates = result.scalars().all()
        return templates

@app.post("/api/email/templates")
async def create_template(tmpl: EmailTemplateCreate, user=Depends(verify_jwt)):
    new_tmpl = EmailTemplate(org_id=1, name=tmpl.name, subject=tmpl.subject, body_template=tmpl.body_template)
    async with async_session() as session:
        session.add(new_tmpl)
        await session.commit()
        await session.refresh(new_tmpl)
        return new_tmpl

class EmailDraftRequest(BaseModel):
    template_id: int

@app.post("/api/leads/{lead_id}/email-draft")
async def generate_email_draft(lead_id: int, req: EmailDraftRequest, user=Depends(verify_jwt)):
    async with async_session() as session:
        lead = await session.get(Lead, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        template = await session.get(EmailTemplate, req.template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        replacements = {
            "{company}": lead.primary_identifier,
            "{name}": lead.primary_identifier,
            "{id}": str(lead.id),
            "{score}": str(lead.final_score),
            "{tier}": lead.tier
        }
        subject = template.subject
        body = template.body_template
        for key, val in replacements.items():
            subject = subject.replace(key, val)
            body = body.replace(key, val)
        return {"subject": subject, "body": body}

# ---------- SCRAPING S SCRAPINGBEE A FALLBACKMI ----------
SUBPAGE_PATHS = [
    "kontakt", "contact", "kontakty", "tym", "team", "o-nas", "about-us", "onas",
    "impressum", "vedenie", "management", "organizacna-struktura", "obchodne-podmienky"
]

def fetch_html_scrapingbee(url: str) -> bytes:
    """Získa HTML ako RAW BYTES pomocou ScrapingBee API.
    Vracia bytes – BeautifulSoup ich dekóduje sám podľa <meta charset> v HTML.
    NIKDY nedekódujeme tu – to spôsobovalo double-encoding (Ä¾ namiesto ľ).
    """
    if not SCRAPINGBEE_API_KEY:
        return b""
    try:
        api_url = f"https://app.scrapingbee.com/api/v1?api_key={SCRAPINGBEE_API_KEY}&url={url}&render_js=true"
        resp = requests.get(api_url, timeout=30)
        if resp.status_code == 200:
            return resp.content          # <-- bytes, žiadny decode
        else:
            print(f"ScrapingBee chyba: status {resp.status_code}")
            return b""
    except Exception as e:
        print(f"ScrapingBee výnimka: {e}")
        return b""

def fetch_raw_bytes_scrapingbee(url: str) -> bytes:
    """Alias pre diagnostiku – rovnaké ako fetch_html_scrapingbee."""
    return fetch_html_scrapingbee(url)

def fetch_html_cloudscraper(url: str) -> bytes:
    """Fallback: získa HTML ako RAW BYTES pomocou cloudscraper.
    Vracia bytes z rovnakého dôvodu ako ScrapingBee varianta.
    """
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, timeout=30)
        if resp.status_code == 200:
            return resp.content          # <-- bytes, žiadny decode
        else:
            print(f"Cloudscraper chyba: status {resp.status_code}")
            return b""
    except Exception as e:
        print(f"Cloudscraper výnimka: {e}")
        return b""

def extract_text_from_html(html: bytes) -> str:
    """Prijíma bytes – explicitne dekódujeme UTF-8 pred BS4 aby sme obišli
    UnicodeDammit ktorý môže bytes misdetectovať a spôsobiť double-encoding."""
    if not html:
        return ""
    # Krok 1: bytes → str cez explicitný UTF-8 decode (ScrapingBee vždy vracia UTF-8)
    # Toto obíde UnicodeDammit v BS4 ktorý môže zle detekovať encoding z bytes
    html_str = html.decode('utf-8', errors='replace')
    # Krok 2: oprav double-encoded mojibake (Ä¾ -> ľ). ScrapingBee niekedy vracia
    # už dvojito zakódovaný UTF-8; ftfy to deterministicky opraví. Na čistom
    # texte je ftfy.fix_text bezpečné (no-op).
    html_str = ftfy.fix_text(html_str)
    soup = BeautifulSoup(html_str, 'html.parser')
    for script in soup(["script", "style"]):
        script.decompose()

    # Explicitne vytiahni tel: a mailto: linky – tieto sa stratia pri get_text()
    contact_hints = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("tel:"):
            number = href.replace("tel:", "").strip()
            contact_hints.append(f"Telefón: {number}")
        elif href.startswith("mailto:"):
            email = href.replace("mailto:", "").strip()
            contact_hints.append(f"Email: {email}")

    text = soup.get_text(separator=' ', strip=True)
    # Normalizuj non-breaking space na regular space
    text = text.replace('\xa0', ' ')
    prefix = ' '.join(contact_hints) + ' ' if contact_hints else ''
    # Limit 25 000 znakov – telefón na fgym.sk/kontakt je na pozícii ~21 800
    # Orezanie na 8 000 sa deje až v extract_with_ai (pre AI), nie tu
    return (prefix + text)[:25000]

async def fetch_text_with_fallback(url: str) -> str:
    """Najprv ScrapingBee, pri zlyhaní retry s trailing slash, potom cloudscraper."""
    html = fetch_html_scrapingbee(url)
    if html:
        print(f"✅ ScrapingBee OK pre {url}")
        return extract_text_from_html(html)

    # Retry s trailing slash (napr. /tym zlyhá ale /tym/ funguje)
    if not url.endswith('/'):
        url_slash = url + '/'
        print(f"⚠️ ScrapingBee zlyhal pre {url}, skúšam {url_slash}")
        html = fetch_html_scrapingbee(url_slash)
        if html:
            print(f"✅ ScrapingBee OK pre {url_slash}")
            return extract_text_from_html(html)

    print(f"⚠️ ScrapingBee zlyhal, skúšam cloudscraper pre {url}")
    html = fetch_html_cloudscraper(url)
    if html:
        print(f"✅ Cloudscraper OK pre {url}")
        return extract_text_from_html(html)
    return ""

def extract_with_ai(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    # Limit textu pre AI – prioritizuj začiatok (kontaktné údaje sú zvyčajne na začiatku agregátu)
    text_for_ai = text[:8000]
    prompt = f"""Si asistent pre extrakciu firemných kontaktných údajov z textu webovej stránky.

Z textu nižšie vyextrahuj:
- primary_identifier: názov firmy (string)
- contact_name: celé meno kontaktnej osoby, napr. "Ladislav Ferenci" (string alebo null)
- role: pozícia osoby – hľadaj CEO, Riaditeľ, Director, Konateľ, Obchod, Sales, Marketing, Info (string alebo null)
- email: emailová adresa (string alebo null)
- phone: telefónne číslo vrátane predvoľby, zachovaj pôvodný formát s medzerami (string alebo null)

DÔLEŽITÉ:
- Hľadaj telefóny aj vo formátoch: "0911 489 439", "+421 911 489 439", "0911/489439"
- Hľadaj mená pri slovách: riaditeľ, CEO, konateľ, director, manager, vedúci
- Vráť LEN čistý JSON objekt, žiadny iný text

{{"primary_identifier": "...", "contact_name": "...", "role": "...", "email": "...", "phone": "..."}}

Text:
{text_for_ai}"""
    try:
        response = openai_client.chat.completions.create(
            model=GPT_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"AI chyba: {e}")
        return {}

def regex_fallback(text: str) -> Dict[str, Any]:
    # Normalizuj non-breaking space na regular space pred hľadaním
    normalized = text.replace('\xa0', ' ')
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', normalized)
    # Telefónny regex – zachytáva všetky bežné slovenské/české formáty:
    #   0911 489 439  |  0911489439  |  0911/489-439
    #   +421 911 489 439  |  +421911489439
    # Pevná štruktúra: (predvoľba|0) + 2-3 číslice + sep? + 3 číslice + sep? + 3 číslice
    phone_match = re.search(
        r'(\+421\s?|\+420\s?|0)'   # medzinárodná predvoľba ALEBO národná nula
        r'\d{2,3}'                  # ďalšie 2–3 číslice (napr. 911)
        r'[\s\-\/]?'               # voliteľný oddeľovač
        r'\d{3}'                    # skupina 3 číslic
        r'[\s\-\/]?'               # voliteľný oddeľovač
        r'\d{3}',                   # skupina 3 číslic
        normalized
    )
    phone_raw = phone_match.group(0).strip() if phone_match else None
    return {
        "email": email_match.group(0) if email_match else None,
        "phone": phone_raw
    }

def role_to_points(role: str) -> int:
    if not role:
        return 0
    role_lower = role.lower()
    if "ceo" in role_lower or "riaditeľ" in role_lower or "director" in role_lower:
        return 50
    if "obchod" in role_lower or "sales" in role_lower:
        return 40
    if "marketing" in role_lower:
        return 30
    if "reklamácia" in role_lower or "claim" in role_lower:
        return 10
    if "info" in role_lower or "podpora" in role_lower:
        return 10
    return 5

class ScrapeRequest(BaseModel):
    url: str

@app.post("/api/leads/scrape")
async def scrape_lead(req: ScrapeRequest, user=Depends(verify_jwt)):
    try:
        base_url = req.url.strip()
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url
        base_url = base_url.rstrip('/')
        
        # Najprv scrapuj kontaktné podstránky (majú prioritu pre AI extrakciu)
        contact_priority_paths = ["kontakt", "contact", "kontakty", "tym", "team", "o-nas", "about-us", "onas", "vedenie", "management"]
        other_paths = [p for p in SUBPAGE_PATHS if p not in contact_priority_paths]

        contact_texts = []
        for path in contact_priority_paths:
            for url_variant in [f"{base_url}/{path}", f"{base_url}/{path}/"]:
                sub_text = await fetch_text_with_fallback(url_variant)
                if sub_text:
                    contact_texts.append(sub_text)
                    break
                await asyncio.sleep(0.3)

        main_text = await fetch_text_with_fallback(base_url)

        other_texts = []
        for path in other_paths:
            for url_variant in [f"{base_url}/{path}", f"{base_url}/{path}/"]:
                sub_text = await fetch_text_with_fallback(url_variant)
                if sub_text:
                    other_texts.append(sub_text)
                    break
                await asyncio.sleep(0.3)

        # Kontaktné podstránky idú ako prvé – AI ich dostane pred orezaním na 8000 znakov
        combined_text = "\n".join(contact_texts)
        if main_text:
            combined_text += "\n" + main_text
        if other_texts:
            combined_text += "\n" + "\n".join(other_texts)
        
        if not combined_text:
            raise HTTPException(status_code=400, detail="Nepodarilo sa načítať žiadny text.")
        
        # AI extrakcia
        extracted = extract_with_ai(combined_text)
        if not extracted:
            extracted = {}
        
        # Fallback regex
        fallback = regex_fallback(combined_text)
        email = extracted.get("email") or fallback["email"]
        phone = extracted.get("phone") or fallback["phone"]
        name = extracted.get("primary_identifier") or base_url.split("//")[-1].split("/")[0]
        contact_name = extracted.get("contact_name")
        role = extracted.get("role")
        # Fallback: ak máme meno kontaktu ale rola sa nevyextrahovala, priraď generickú rolu
        if contact_name and not role:
            role = "Obchodné oddelenie"

        contact_points = role_to_points(role) if role else (10 if (email or phone) else 0)
        
        # Vertikála (zjednodušená)
        body_lower = combined_text.lower()
        vertical = "Unknown"
        if any(w in body_lower for w in ["home garden", "zahrada", "nábytok"]):
            vertical = "Home & Garden"
        elif any(w in body_lower for w in ["beauty", "kozmetika"]):
            vertical = "Beauty & Personal Care"
        elif any(w in body_lower for w in ["pet", "zvieratá"]):
            vertical = "Pet Supplies"
        
        lead_data = {
            "primary_identifier": name,
            "vertical": vertical,
            "contact_channels": {},
            "lead_metadata": {
                "scraped_url": base_url,
                "scraped_at": datetime.datetime.utcnow().isoformat(),
                "contact_name": contact_name,
                "contact_role": role,
                "contact_points": contact_points,
                "scraped_email": email,
                "scraped_phone": phone,
                "ai_extracted": extracted,
                "regex_fallback": fallback
            }
        }
        if email:
            lead_data["contact_channels"]["email"] = email
        if phone:
            lead_data["contact_channels"]["phone"] = phone
        
        # Skóre
        org_id = 1
        async with async_session() as session:
            result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == org_id))
            org_config = result.scalar_one_or_none()
            if not org_config:
                raise HTTPException(status_code=404, detail="Organization config not found")
        
        rule_score = evaluate_lead(lead_data, org_config.scoring_rules)
        final_score = rule_score + contact_points
        final_score = max(0, min(100, final_score))
        thresholds = org_config.tier_thresholds
        if final_score >= thresholds["HOT"]: tier = "HOT"
        elif final_score >= thresholds["WARM"]: tier = "WARM"
        elif final_score >= thresholds["COOL"]: tier = "COOL"
        else: tier = "DEAD"
        
        # Uloženie alebo aktualizácia
        async with async_session() as session:
            stmt = select(Lead).where(Lead.primary_identifier == name)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.contact_channels = lead_data["contact_channels"]
                existing.vertical = vertical
                existing.lead_metadata = lead_data["lead_metadata"]
                existing.rule_score = rule_score
                existing.final_score = final_score
                existing.tier = tier
                await session.commit()
                await session.refresh(existing)
                return {
                    "action": "updated",
                    "lead_id": existing.lead_id,
                    "primary_identifier": name,
                    "score": final_score,
                    "tier": tier,
                    "extracted": {
                        "email": email,
                        "phone": phone,
                        "contact_name": contact_name,
                        "contact_role": role,
                        "contact_points": contact_points
                    }
                }
            else:
                new_lead = Lead(
                    lead_id=str(uuid.uuid4()),
                    primary_identifier=name,
                    vertical=vertical,
                    lead_metadata=lead_data,
                    contact_channels=lead_data.get("contact_channels", {}),
                    rule_score=rule_score,
                    final_score=final_score,
                    tier=tier
                )
                session.add(new_lead)
                await session.commit()
                await session.refresh(new_lead)
                return {
                    "action": "created",
                    "lead_id": new_lead.lead_id,
                    "primary_identifier": name,
                    "score": final_score,
                    "tier": tier,
                    "extracted": {
                        "email": email,
                        "phone": phone,
                        "contact_name": contact_name,
                        "contact_role": role,
                        "contact_points": contact_points
                    }
                }
    except Exception as e:
        import traceback
        error_detail = f"Scraping error: {str(e)}\n{traceback.format_exc()}"
        print(error_detail)
        raise HTTPException(status_code=500, detail=error_detail)
@app.post("/api/debug/scrape")
async def debug_scrape(req: ScrapeRequest, user=Depends(verify_jwt)):
    """
    Diagnostický endpoint – vráti surový text, encoding diagnostiku a AI extrakciu bez ukladania.
    """
    base_url = req.url.strip()
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    base_url = base_url.rstrip('/')

    # --- Encoding diagnostika: stiahni raw bytes z kontaktnej stránky ---
    kontakt_url = f"{base_url}/kontakt"
    raw_bytes = fetch_raw_bytes_scrapingbee(kontakt_url)
    if not raw_bytes:
        raw_bytes = fetch_raw_bytes_scrapingbee(base_url)

    chardet_result = chardet.detect(raw_bytes[:4000]) if raw_bytes else {}
    # repr() prvých 500 bajtov – ukazuje skutočné bajty vrátane \xc4\xbe atď.
    raw_bytes_preview = repr(raw_bytes[:500])

    # --- Bežné scrapovanie ---
    contact_priority_paths = ["kontakt", "contact", "kontakty", "tym", "team", "o-nas", "about-us", "onas", "vedenie", "management"]
    other_paths = [p for p in SUBPAGE_PATHS if p not in contact_priority_paths]

    contact_texts = []
    for path in contact_priority_paths:
        for url_variant in [f"{base_url}/{path}", f"{base_url}/{path}/"]:
            sub_text = await fetch_text_with_fallback(url_variant)
            if sub_text:
                contact_texts.append(sub_text)
                break
            await asyncio.sleep(0.3)

    main_text = await fetch_text_with_fallback(base_url)

    other_texts = []
    for path in other_paths:
        for url_variant in [f"{base_url}/{path}", f"{base_url}/{path}/"]:
            sub_text = await fetch_text_with_fallback(url_variant)
            if sub_text:
                other_texts.append(sub_text)
                break
            await asyncio.sleep(0.3)

    combined_text = "\n".join(contact_texts)
    if main_text:
        combined_text += "\n" + main_text
    if other_texts:
        combined_text += "\n" + "\n".join(other_texts)

    # AI extrakcia
    extracted = extract_with_ai(combined_text)

    # Fallback: ak máme meno kontaktu ale rola sa nevyextrahovala, priraď generickú rolu
    if extracted and extracted.get("contact_name") and not extracted.get("role"):
        extracted["role"] = "Obchodné oddelenie"

    # Regex fallback
    fallback = regex_fallback(combined_text)

    return {
        "url": base_url,
        # Encoding diagnostika
        "detected_encoding": chardet_result,
        "raw_bytes_preview": raw_bytes_preview,
        # Text výstup
        "text_length": len(combined_text),
        "text_preview": combined_text[:2000],
        "ai_extracted": extracted,
        "regex_fallback": fallback
    }