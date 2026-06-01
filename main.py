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
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, JSON, DateTime, func, select
import random
import requests
import httpx
from bs4 import BeautifulSoup
from openai import AzureOpenAI
import cloudscraper
import chardet
import ftfy
from playwright.async_api import async_playwright

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
# Vlastná JSON odpoveď s explicitným charset=utf-8 v Content-Type hlavičke.
# Bez toho Windows PowerShell 5.1 dekóduje telo ako ISO-8859-1 → mojibake (Ä¾).
class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

app = FastAPI(title="ControlRoom MVP", default_response_class=UTF8JSONResponse)

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

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def fetch_html_httpx(url: str) -> bytes:
    """Získa HTML ako RAW BYTES pomocou httpx s rotáciou User-Agent headerov."""
    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "sk-SK,sk;q=0.9,cs;q=0.8,en-US;q=0.7,en;q=0.6",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code == 200 and resp.content:
            return resp.content
        print(f"httpx chyba {url}: status={resp.status_code}")
        return b""
    except Exception as e:
        print(f"httpx výnimka pre {url}: {e}")
        return b""

def fetch_html_scrapingbee(url: str, render_js: bool = True) -> bytes:
    """ScrapingBee – kredity vyčerpané. Kľúč ponechaný v env pre budúcnosť."""
    if not SCRAPINGBEE_API_KEY:
        return b""
    return b""

def fetch_raw_bytes_scrapingbee(url: str) -> bytes:
    """Alias pre diagnostiku – používa httpx."""
    return fetch_html_httpx(url)

def fetch_html_cloudscraper(url: str) -> bytes:
    """Pôvodný cloudscraper bez UA rotácie – zachovaný pre spätnú kompatibilitu."""
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, timeout=20)
        if resp.status_code == 200:
            return resp.content
        print(f"Cloudscraper chyba: status {resp.status_code}")
        return b""
    except Exception as e:
        print(f"Cloudscraper výnimka: {e}")
        return b""

def fetch_html_cloudscraper_with_ua(url: str) -> bytes:
    """Cloudscraper s rotáciou UA a retry 3x pri failure.
    Jeden scraper instance (šetrí RAM) — mení len User-Agent header medzi pokusmi.
    """
    ua_pool = _USER_AGENTS.copy()
    random.shuffle(ua_pool)
    try:
        scraper = cloudscraper.create_scraper()
    except Exception as e:
        print(f"CloudScraper init zlyhalo: {e}")
        return b""
    for attempt, ua in enumerate(ua_pool[:3], 1):
        try:
            scraper.headers.update({
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "sk-SK,sk;q=0.9,cs;q=0.8,en-US;q=0.7,en;q=0.6",
                "Referer": "https://www.google.com/",
            })
            resp = scraper.get(url, timeout=20)
            if resp.status_code == 200 and resp.content:
                print(f"✅ CloudScraper+UA (pokus {attempt}) OK pre {url}")
                return resp.content
            print(f"  CloudScraper+UA pokus {attempt}: status={resp.status_code}")
        except Exception as e:
            print(f"  CloudScraper+UA pokus {attempt} výnimka: {e}")
    print(f"❌ CloudScraper+UA všetky 3 pokusy zlyhali pre {url}")
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
    # Odstráň cookie/legal/GDPR boilerplate hneď tu – uvoľní miesto pre reálny obsah
    text = filter_boilerplate(text)
    prefix = ' '.join(contact_hints) + ' ' if contact_hints else ''
    # Limit 25 000 znakov – telefón na fgym.sk/kontakt je na pozícii ~21 800
    return (prefix + text)[:25000]

async def fetch_html_playwright(url: str) -> bytes:
    """Headless Chromium cez Playwright — spustí JS, počká na sieťový idle.
    Použije sa len ako posledná možnosť (pomalší, ~5–10s per stránka).
    Vracia bytes (UTF-8 enkódovaný HTML string).
    """
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                ],
            )
            ctx = await browser.new_context(
                user_agent=random.choice(_USER_AGENTS),
                locale="sk-SK",
                extra_http_headers={
                    "Accept-Language": "sk-SK,sk;q=0.9,cs;q=0.8,en-US;q=0.7",
                    "Referer": "https://www.google.com/",
                },
            )
            page = await ctx.new_page()
            # Blokuj obrázky, fonty, média — nepotrebujeme ich, ušetríme RAM+čas
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3}",
                lambda r: r.abort()
            )
            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
            except Exception:
                # networkidle timeout — vezmeme čo máme
                pass
            content = await page.content()
            await browser.close()
            if content:
                print(f"✅ Playwright OK pre {url} ({len(content)} znakov)")
                return content.encode("utf-8", errors="replace")
            return b""
    except Exception as e:
        print(f"Playwright výnimka pre {url}: {e}")
        return b""

async def fetch_text_with_fallback(url: str) -> str:
    """Reťaz fallbackov: httpx → cloudscraper+UA → Playwright → prázdny string."""
    html = fetch_html_httpx(url)
    if html:
        print(f"✅ httpx OK pre {url}")
        return extract_text_from_html(html)

    print(f"⚠️ httpx zlyhalo, skúšam cloudscraper+UA pre {url}")
    html = fetch_html_cloudscraper_with_ua(url)
    if html:
        return extract_text_from_html(html)

    print(f"⚠️ cloudscraper zlyhalo, skúšam Playwright pre {url}")
    html = await fetch_html_playwright(url)
    if html:
        return extract_text_from_html(html)

    print(f"❌ Všetky fetch metódy zlyhali pre {url}")
    return ""

# --- Boilerplate filter (cookies, GDPR, obchodné podmienky atď.) ---
BOILERPLATE_KEYWORDS = [
    "cookies", "cookie", "súhlasím", "suhlasim", "prehliadač", "prehliadac",
    "gdpr", "obchodné podmienky", "obchodne podmienky", "vseobecne podmienky",
    "všeobecné podmienky", "reklamačný poriadok", "reklamacny poriadok",
    "ochrana osobných údajov", "ochrana osobnych udajov", "spracovanie osobných údajov",
    "spracovanie osobnych udajov",
]

def filter_boilerplate(text: str) -> str:
    """Zahodí vety obsahujúce cookie/GDPR/legal boilerplate.
    Uvoľní miesto v 8000-znakovom okne pre AI a v 25k limite extract_text_from_html.
    """
    if not text:
        return ""
    # Rozdeľ na "vety" podľa interpunkcie alebo nového riadku
    parts = re.split(r'(?<=[.!?])\s+|\n+', text)
    kept = [p for p in parts if not any(k in p.lower() for k in BOILERPLATE_KEYWORDS)]
    return ' '.join(kept)

# --- Validácia telefónnych čísel ---
def is_valid_phone(num: str) -> bool:
    """True ak ide o reálne SK/CZ telefónne číslo. Odmietne 0900000000, 0123456789,
    príliš krátke/dlhé čísla, čísla so všetkými rovnakými číslicami atď.
    """
    if not num:
        return False
    digits = re.sub(r'\D', '', num)
    if not digits:
        return False

    # Odmietni placeholdery: všetky rovnaké číslice (000..., 999...), sekvencie 12345...
    if len(set(digits)) <= 2:
        return False
    if digits in ('0123456789', '1234567890', '0987654321'):
        return False
    # Odmietni očividné fake čísla
    if digits.endswith('0000000') or digits.endswith('1234567'):
        return False

    # +421 / 421 + 9 SK
    if digits.startswith('421') and len(digits) == 12:
        return True
    # +420 / 420 + 9 CZ
    if digits.startswith('420') and len(digits) == 12:
        return True
    # SK mobil: 09XX XXX XXX (10 číslic, začína 09)
    if len(digits) == 10 and digits.startswith('09'):
        return True
    # SK pevná: 0[2-5]X... (10 číslic)
    if len(digits) == 10 and digits[0] == '0' and digits[1] in '2345':
        return True
    # CZ holých 9 číslic, mobil začína 6/7, pevná 2-5
    if len(digits) == 9 and digits[0] in '23456789':
        return True
    return False


# --- Role keywords (SK / CZ / EN) ---
ROLE_KEYWORDS = [
    "riaditeľ", "riaditel", "ředitel", "reditel", "director", "ceo",
    "konateľ", "konatel", "jednatel",
    "obchodný", "obchodny", "obchodní", "obchodni", "obchod", "sales",
    "vedúci", "veduci", "vedoucí", "vedouci", "head",
    "manažér", "manazer", "manažer", "manager",
    "kontaktná osoba", "kontaktna osoba", "kontaktní osoba", "kontaktni osoba",
    "majiteľ", "majitel",
]

# Explicitné rozsahy SK/CZ veľkých a malých písmen.
# Nesmieme použiť [A-ZÁ-Ž] – ten rozsah obsahuje aj malé Unicode písmená (é, í, ...)
# a pattern by zachytával `ér` z `manažér` ako začiatok mena.
_UPPER = "A-ZÁČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ"
_LOWER = "a-záčďéíľĺňóôŕšťúýž"
# Titul + 2-3 Capitalized slová oddelené iba medzerou/tabom (NIE newline – meno sa nezalamuje cez riadky)
_NAME_PATTERN = re.compile(
    rf'(?:Mgr\.|Ing\.|Bc\.|JUDr\.|MUDr\.|PhDr\.|prof\.|doc\.|MVDr\.|RNDr\.)?[ \t]*'
    rf'[{_UPPER}][{_LOWER}]+(?:[ \t]+[{_UPPER}][{_LOWER}]+){{1,2}}'
)
# Slová ktoré nie sú meno – vyhodíme ich keď ich pattern zachytí ako "druhé slovo"
_NOT_A_NAME_WORD = {
    "Email", "Mail", "Telefón", "Telefon", "Mobil", "Phone", "Tel",
    "Web", "Adresa", "Address", "Sídlo", "Sidlo", "Kontakt", "Contact",
    "Firma", "Spoločnosť", "Spolocnost", "Company", "Office", "Info",
    "Pondelok", "Utorok", "Streda", "Štvrtok", "Piatok", "Sobota", "Nedeľa",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
}

def _context(text: str, start: int, end: int, width: int = 150) -> str:
    """Vráti text okolo [start:end] s ±width znakov."""
    s = max(0, start - width)
    e = min(len(text), end + width)
    return text[s:e].strip()

def extract_all_candidates(text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Zozbiera VŠETKÝCH kandidátov (emails, validné telefóny, mená pri role keywords)
    s ~150-znakovým kontextom okolo každého výskytu. AI dostane tento štruktúrovaný
    zoznam namiesto surového textu.
    """
    result: Dict[str, List[Dict[str, Any]]] = {"emails": [], "phones": [], "names": []}
    if not text:
        return result
    normalized = text.replace('\xa0', ' ')

    # === EMAILS ===
    seen_emails = set()
    for m in re.finditer(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', normalized):
        addr = m.group(0)
        key = addr.lower()
        if key in seen_emails:
            continue
        seen_emails.add(key)
        result["emails"].append({
            "value": addr,
            "context": _context(normalized, m.start(), m.end())
        })

    # === PHONES === (regex + validácia)
    phone_pattern = re.compile(
        r'(\+421\s?|\+420\s?|0)\d{2,3}[\s\-\/]?\d{3}[\s\-\/]?\d{3}'
    )
    seen_phones = set()
    for m in phone_pattern.finditer(normalized):
        raw = m.group(0).strip()
        norm = re.sub(r'\D', '', raw)
        if norm in seen_phones:
            continue
        if not is_valid_phone(raw):
            continue
        seen_phones.add(norm)
        result["phones"].append({
            "value": raw,
            "context": _context(normalized, m.start(), m.end())
        })

    # === NAMES === blízko role kľúčových slov
    seen_names = set()
    for kw in ROLE_KEYWORDS:
        for m in re.finditer(re.escape(kw), normalized, re.IGNORECASE):
            window_start = max(0, m.start() - 120)
            window_end = min(len(normalized), m.end() + 120)
            window = normalized[window_start:window_end]
            for nm in _NAME_PATTERN.finditer(window):
                name_val = nm.group(0).strip()
                # Filter: musí mať aspoň 2 slová (krstné + priezvisko, akademický titul sa neráta)
                tokens = [t for t in name_val.split() if not t.endswith('.')]
                if len(tokens) < 2:
                    continue
                # Filter: žiadne tokeny zo zoznamu nenázvov (Email, Telefón, Adresa...)
                if any(t in _NOT_A_NAME_WORD for t in tokens):
                    continue
                if name_val in seen_names:
                    continue
                seen_names.add(name_val)
                abs_start = window_start + nm.start()
                abs_end = window_start + nm.end()
                result["names"].append({
                    "value": name_val,
                    "near_role": kw,
                    "context": _context(normalized, abs_start, abs_end)
                })
                if len(result["names"]) >= 15:
                    return result

    # === NAMES === blízko emailov (±200 znakov okolo každého emailu)
    for email_entry in result["emails"]:
        email_val = email_entry["value"]
        for em in re.finditer(re.escape(email_val), normalized, re.IGNORECASE):
            window_start = max(0, em.start() - 200)
            window_end = min(len(normalized), em.end() + 200)
            window = normalized[window_start:window_end]
            for nm in _NAME_PATTERN.finditer(window):
                name_val = nm.group(0).strip()
                tokens = [t for t in name_val.split() if not t.endswith('.')]
                if len(tokens) < 2:
                    continue
                if any(t in _NOT_A_NAME_WORD for t in tokens):
                    continue
                if name_val in seen_names:
                    continue
                seen_names.add(name_val)
                abs_start = window_start + nm.start()
                abs_end = window_start + nm.end()
                result["names"].append({
                    "value": name_val,
                    "near_role": f"email:{email_val}",
                    "context": _context(normalized, abs_start, abs_end)
                })
                if len(result["names"]) >= 15:
                    return result

    # WARNING keď všetky kandidáty prázdne
    if not result["emails"] and not result["phones"] and not result["names"]:
        print(f"WARNING: 0 candidates found — možný JS-only render alebo blokácia")

    return result

def extract_with_ai(text: str, company_name_hint: str = "") -> Dict[str, Any]:
    """AI vyberie JEDEN najlepší obchodný kontakt zo zoznamu kandidátov.
    Namiesto 8000 znakov surového textu pošle AI štruktúrovaných kandidátov."""
    if not text:
        return {}
    candidates = extract_all_candidates(text)
    cleaned_preview = filter_boilerplate(text)[:3000]

    payload = {
        "company_name_hint": company_name_hint or "",
        "emails": candidates["emails"][:10],
        "phones": candidates["phones"][:10],
        "names": candidates["names"][:10],
    }

    prompt = f"""Si asistent pre výber NAJLEPŠIEHO obchodného kontaktu firmy z extrahovaných kandidátov.

KANDIDÁTI (z webu, deduplikovaní, telefóny už validované):
{json.dumps(payload, ensure_ascii=False, indent=2)}

VYČISTENÝ TEXT z kontaktnej stránky (prvých 3000 znakov, bez cookies/GDPR):
{cleaned_preview}

PRIORITA výberu (vyber JEDEN kontakt):
1. menovaná osoba s rolou riaditeľ/ředitel/director/CEO/konateľ/jednatel/majiteľ
2. menovaná osoba v obchode (obchod/obchodní/sales) alebo manažér/vedúci
3. menný email (formát meno.priezvisko@firma alebo priezvisko@firma)
4. generický email (info@, podpora@, office@)

DÔLEŽITÉ:
- Roly podporuj v SK/CZ/EN: riaditeľ/ředitel/director, konateľ/jednatel, obchod/obchodní/sales, vedúci/vedoucí/head.
- Ak je MENO uvedené v kontexte BLÍZKO telefónu alebo blízko slova "obchod/sales/obchodní", priraď rolu "Obchodné oddelenie" a spáruj toto meno s tým telefónom (z poľa phones).
- Ak rolu NEMÔŽEŠ jednoznačne určiť, vráť null – nehádaj.
- contact_name musí pochádzať z poľa names, alebo z local-part menného emailu. Neguruj.
- Ak je contact_name null ale emails[].value má menný formát (napr. meno.priezvisko@domena, jan.novak@, ladislav.ferenci@), vytiahni meno z local-part emailu sám: rozdeľ podľa "." alebo "-", každú časť daj s veľkým začiatočným písmenom (napr. "ferenci.ladislav" → "Ferenci Ladislav"). Použi tento postup len keď names[] je prázdne alebo neobsahuje reálne meno.

Vráť LEN čistý JSON v tomto tvare (nič iné):
{{
  "primary_identifier": "názov firmy",
  "contact_name": "meno priezvisko alebo null",
  "role": "rola alebo null",
  "email": "email alebo null",
  "phone": "telefón v pôvodnom formáte z phones[].value, alebo null",
  "reasoning": "1-2 vety prečo si vybral práve tento kontakt"
}}
"""
    try:
        response = openai_client.chat.completions.create(
            model=GPT_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        # priložíme kandidátov do výsledku pre debug a fallbacky vyššie
        result["_candidates"] = candidates
        return result
    except Exception as e:
        print(f"AI chyba: {e}")
        return {"_candidates": candidates}

def regex_fallback(text: str) -> Dict[str, Any]:
    """Spätná kompatibilita – vráti prvý platný email a telefón z kandidátov."""
    cand = extract_all_candidates(text or "")
    return {
        "email": cand["emails"][0]["value"] if cand["emails"] else None,
        "phone": cand["phones"][0]["value"] if cand["phones"] else None,
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

# Generické emailové prefixy (oddelenie/schránka, nie konkrétna osoba)
GENERIC_EMAIL_PREFIXES = [
    "info", "podpora", "support", "office", "kontakt", "contact",
    "sales", "obchod", "reklamacia", "reklamácia", "admin", "hello",
    "ahoj", "objednavky", "objednávky", "eshop", "shop", "mail", "post", "noreply"
]

def _domain_of(value: str) -> str:
    """Vytiahne holú doménu z URL alebo emailu (bez www., bez cesty)."""
    if not value:
        return ""
    v = value.lower().strip()
    v = v.replace("https://", "").replace("http://", "")
    v = v.split("@")[-1]          # ak je to email, vezmi časť za @
    v = v.split("/")[0]            # odstráň cestu
    if v.startswith("www."):
        v = v[4:]
    return v

def is_generic_email(email: str) -> bool:
    """True ak je email generická schránka (info@, podpora@, office@ ...)."""
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    return any(local == g or local.startswith(g) for g in GENERIC_EMAIL_PREFIXES)

def is_personal_email(email: str, contact_name: Optional[str], website: Optional[str]) -> bool:
    """True ak je email priamy menný/firemný:
    - časť pred @ obsahuje časť mena/priezviska (napr. ferenci.ladislav), ALEBO
    - doména emailu sedí s doménou webu (meno@firma.sk).
    """
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    # 1. lokálna časť obsahuje meno alebo priezvisko
    if contact_name:
        for token in re.split(r'[\s.,]+', contact_name.lower()):
            if len(token) >= 3 and token in local:
                return True
    # 2. doména emailu sedí s doménou webu
    email_domain = _domain_of(email)
    web_domain = _domain_of(website or "")
    if email_domain and web_domain and email_domain == web_domain:
        return True
    return False

def score_contact(email: Optional[str], phone: Optional[str], contact_name: Optional[str],
                  role: Optional[str], website: Optional[str]) -> Dict[str, Any]:
    """Bodovanie kontaktu podľa priority:
      - priamy menný/firemný email = 45 (aj bez telefónu)
      - generický email (info@, podpora@, office@) = 10
      - len telefón bez mena = 20
    Ak AI našla rolu, berie sa max(role_to_points, email/phone body) – rolu nehádame.
    """
    direct_personal_email = bool(email) and not is_generic_email(email) and \
        is_personal_email(email, contact_name, website)

    if direct_personal_email:
        contact_points = 45
    elif email and is_generic_email(email):
        contact_points = 10
    elif email:
        contact_points = 10          # neznámy email bez zhody mena/domény
    elif phone:
        contact_points = 20          # len telefón bez mena
    else:
        contact_points = 0

    # Rolu nehádame – ak ju AI našla, môže body iba zvýšiť
    role_points = role_to_points(role) if role else 0
    contact_points = max(contact_points, role_points)

    return {"contact_points": contact_points, "direct_personal_email": direct_personal_email}

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
        
        # AI extrakcia s hint názvom firmy z domény
        domain_hint = _domain_of(base_url)
        extracted = extract_with_ai(combined_text, company_name_hint=domain_hint)
        if not extracted:
            extracted = {}

        # Kandidáti z extract_with_ai (regex) – fallback pre prípad zlyhania AI
        candidates = extracted.get("_candidates") or extract_all_candidates(combined_text)
        first_email = candidates["emails"][0]["value"] if candidates["emails"] else None
        first_phone = candidates["phones"][0]["value"] if candidates["phones"] else None

        email = extracted.get("email") or first_email
        phone = extracted.get("phone") or first_phone
        name = extracted.get("primary_identifier") or base_url.split("//")[-1].split("/")[0]
        contact_name = extracted.get("contact_name")
        role = extracted.get("role")  # rolu nehádame – ak ju AI nenašla, ostáva null
        reasoning = extracted.get("reasoning")

        contact_eval = score_contact(email, phone, contact_name, role, base_url)
        contact_points = contact_eval["contact_points"]
        direct_personal_email = contact_eval["direct_personal_email"]
        # spätná kompatibilita pre staré polia v lead_metadata
        fallback = {"email": first_email, "phone": first_phone}
        
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
                "direct_personal_email": direct_personal_email,
                "scraped_email": email,
                "scraped_phone": phone,
                "ai_reasoning": reasoning,
                "candidates_count": {
                    "emails": len(candidates.get("emails", [])),
                    "phones": len(candidates.get("phones", [])),
                    "names": len(candidates.get("names", [])),
                },
                "ai_extracted": {k: v for k, v in extracted.items() if k != "_candidates"},
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

    # AI extrakcia (s hint názvom firmy z domény)
    domain_hint = _domain_of(base_url)
    extracted = extract_with_ai(combined_text, company_name_hint=domain_hint) or {}
    candidates = extracted.pop("_candidates", None) or extract_all_candidates(combined_text)

    # Fallback hodnoty z kandidátov
    first_email = candidates["emails"][0]["value"] if candidates["emails"] else None
    first_phone = candidates["phones"][0]["value"] if candidates["phones"] else None
    fallback = {"email": first_email, "phone": first_phone}

    # Diagnostika kontaktného skóre (rolu nehádame – ostáva tak ako ju vrátila AI)
    email = extracted.get("email") or first_email
    phone = extracted.get("phone") or first_phone
    contact_name = extracted.get("contact_name")
    role = extracted.get("role")
    contact_eval = score_contact(email, phone, contact_name, role, base_url)

    return {
        "url": base_url,
        # Encoding diagnostika
        "detected_encoding": chardet_result,
        "raw_bytes_preview": raw_bytes_preview,
        # Text výstup
        "text_length": len(combined_text),
        "text_preview": combined_text[:2000],
        # AI výber + reasoning
        "ai_extracted": extracted,
        # Všetci kandidáti (regex)
        "candidates": candidates,
        # Spätná kompatibilita pre starý klient
        "regex_fallback": fallback,
        # Kontaktné skóre
        "contact_scoring": contact_eval
    }