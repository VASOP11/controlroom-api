import os
import uuid
import datetime
import re
import json
import asyncio
import unicodedata
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
import gc
import requests
import httpx
from bs4 import BeautifulSoup
from openai import AzureOpenAI
import cloudscraper
import chardet
import ftfy
from playwright.async_api import async_playwright
from scrapling.fetchers import StealthyFetcher, AsyncFetcher
try:
    import whois as _whois_lib  # python-whois
except Exception:
    _whois_lib = None

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
    "impressum", "vedenie", "management", "organizacna-struktura", "obchodne-podmienky",
    "kontaktne-informacie", "kontaktne-udaje", "kontaktne-info",
    "vseobecne-obchodne-podmienky", "vop",
    "o-spolocnosti", "o-firme", "prevadzka",
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
        with httpx.Client(follow_redirects=True, timeout=8) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code == 200 and resp.content:
            return resp.content
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
        resp = scraper.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.content
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
    for attempt, ua in enumerate(ua_pool[:2], 1):  # 2 pokusy stačia
        try:
            scraper.headers.update({
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "sk-SK,sk;q=0.9,cs;q=0.8,en-US;q=0.7,en;q=0.6",
                "Referer": "https://www.google.com/",
            })
            resp = scraper.get(url, timeout=10)
            if resp.status_code == 200 and resp.content:
                return resp.content
        except Exception:
            pass
    return b""

def is_garbled_content(text: str) -> bool:
    """Vráti True ak je text binárny garbage (Cloudflare blokoval request).
    Prah: viac ako 20% znakov je unicode replacement char \\ufffd alebo non-printable bytes.
    """
    if not text:
        return False
    total = len(text)
    if total < 50:
        return False
    bad = sum(
        1 for ch in text
        if ch == '�' or (ord(ch) < 32 and ch not in '\t\n\r')
    )
    return (bad / total) > 0.20


async def fetch_html_scrapling(url: str) -> bytes:
    """Stealth fetch cez ScraplingFetcher (camoufox/patchright backend).
    Použij ako fallback keď httpx/cloudscraper vrátia garbled binary content
    (typicky Cloudflare JS challenge).
    Vracia bytes kompatibilné s extract_text_from_html().
    """
    try:
        print(f"🕵️ Scrapling StealthyFetcher pre {url}")
        page = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=30000,
        )
        if page and page.body:
            return page.body
    except Exception as e:
        print(f"⚠️ StealthyFetcher zlyhalo pre {url}: {e}")
    # Fallback na AsyncFetcher (bez browsera, ale s lepšou hlavičkou ako httpx)
    try:
        print(f"🔄 Scrapling AsyncFetcher fallback pre {url}")
        page = await AsyncFetcher.get(url)
        if page and page.body:
            return page.body
    except Exception as e:
        print(f"⚠️ AsyncFetcher zlyhalo pre {url}: {e}")
    return b""


def extract_jsonld_contacts(html: bytes) -> Dict[str, Any]:
    """Vytiahne kontaktné info z <script type=\"application/ld+json\">.
    Väčšina e-shopov má Organization / LocalBusiness schema s contactPoint
    obsahujúcim telephone, email, name. ZADARMO, žiadny JS render nepotrebný.
    Vracia {'name','email','phone','contact_name','role'} alebo prázdny dict.
    """
    out: Dict[str, Any] = {}
    if not html:
        return out
    try:
        soup = BeautifulSoup(html.decode("utf-8", errors="replace"), "html.parser")
        for s in soup.find_all("script", type="application/ld+json"):
            txt = s.string or s.get_text() or ""
            if not txt.strip():
                continue
            try:
                data = json.loads(txt)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for it in items:
                if not isinstance(it, dict):
                    continue
                graph = it.get("@graph") if "@graph" in it else [it]
                if not isinstance(graph, list):
                    graph = [graph]
                for node in graph:
                    if not isinstance(node, dict):
                        continue
                    t = node.get("@type", "")
                    if isinstance(t, list):
                        t = ",".join(t)
                    if not any(k in str(t).lower() for k in ("organization", "localbusiness", "store", "corporation")):
                        continue
                    if not out.get("name") and node.get("name"):
                        out["name"] = node["name"]
                    if not out.get("email") and node.get("email"):
                        out["email"] = str(node["email"]).replace("mailto:", "")
                    if not out.get("phone") and node.get("telephone"):
                        out["phone"] = str(node["telephone"])
                    cp = node.get("contactPoint")
                    if cp:
                        if isinstance(cp, dict):
                            cp = [cp]
                        for c in cp:
                            if not isinstance(c, dict):
                                continue
                            if not out.get("email") and c.get("email"):
                                out["email"] = str(c["email"]).replace("mailto:", "")
                            if not out.get("phone") and c.get("telephone"):
                                out["phone"] = str(c["telephone"])
                            if not out.get("role") and c.get("contactType"):
                                out["role"] = str(c["contactType"])
                            if not out.get("contact_name") and c.get("name"):
                                out["contact_name"] = str(c["name"])
        if out:
            print(f"📦 JSON-LD extrahované: {list(out.keys())}")
    except Exception as e:
        print(f"JSON-LD parser výnimka: {e}")
    return out

def whois_contacts(domain: str) -> Dict[str, Any]:
    """WHOIS lookup pre fallback. Pre .sk/.cz commercial domains väčšinou
    skryté GDPR-om, ale občas vráti registrant email/name. ZADARMO."""
    if not _whois_lib or not domain:
        return {}
    try:
        bare = _domain_of(domain)
        if not bare:
            return {}
        w = _whois_lib.whois(bare)
        out: Dict[str, Any] = {}
        email = getattr(w, "emails", None)
        if isinstance(email, list) and email:
            email = next((e for e in email if "@" in str(e)), None)
        if email and "@" in str(email):
            out["email"] = str(email)
        name = getattr(w, "name", None) or getattr(w, "registrant_name", None)
        if name and isinstance(name, str) and len(name.split()) >= 2:
            out["contact_name"] = name
        if out:
            print(f"🌐 WHOIS pre {bare}: {list(out.keys())}")
        return out
    except Exception as e:
        print(f"WHOIS výnimka pre {domain}: {e}")
        return {}

def has_good_contacts(text: str) -> bool:
    """Heuristika: vrátime True ak v texte už máme dobrý kontakt
    (email + telefón ALEBO email + meno blízko role). Vtedy Playwright netreba."""
    if not text:
        return False
    cand = extract_all_candidates(text)
    has_email = bool(cand.get("emails"))
    has_phone = bool(cand.get("phones"))
    has_name = bool(cand.get("names"))
    return has_email and (has_phone or has_name)

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

    # Explicitne vytiahni tel:, mailto: a WhatsApp linky – tieto sa stratia pri get_text()
    contact_hints = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("tel:"):
            number = href.replace("tel:", "").strip()
            contact_hints.append(f"Telefón: {number}")
        elif href.startswith("mailto:"):
            email = href.replace("mailto:", "").strip()
            contact_hints.append(f"Email: {email}")
        elif "wa.me/" in href or "whatsapp.com/send" in href:
            # WhatsApp linky obsahujú číslo vo formáte 00421XXXXXXXXX alebo 421XXXXXXXXX
            # Prevedieme na +421 formát aby ho phone regex zachytil
            import urllib.parse
            wa_num = ""
            if "wa.me/" in href:
                wa_num = href.split("wa.me/")[-1].split("?")[0].strip()
            elif "phone=" in href:
                wa_num = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("phone", [""])[0]
            wa_num = re.sub(r'\D', '', wa_num)
            if wa_num.startswith("00421") or wa_num.startswith("00420"):
                wa_num = "+" + wa_num[2:]  # 00421 → +421
            elif wa_num.startswith("421") and len(wa_num) == 12:
                wa_num = "+" + wa_num
            elif wa_num.startswith("420") and len(wa_num) == 12:
                wa_num = "+" + wa_num
            if wa_num.startswith("+"):
                contact_hints.append(f"Telefón: {wa_num}")

    text = soup.get_text(separator=' ', strip=True)
    # Normalizuj non-breaking space na regular space
    text = text.replace('\xa0', ' ')
    # Odstráň cookie/legal/GDPR boilerplate hneď tu – uvoľní miesto pre reálny obsah
    text = filter_boilerplate(text)
    prefix = ' '.join(contact_hints) + ' ' if contact_hints else ''
    # Limit 25 000 znakov – telefón na fgym.sk/kontakt je na pozícii ~21 800
    full = prefix + text
    if len(full) <= 25000:
        return full
    # Ber prvých 10k (JSON-LD, kontakty v hlavičke) + posledných 15k (podmienky, footer)
    return full[:15000] + " ... " + full[-35000:]

async def fetch_html_playwright(url: str, browser_ctx=None) -> bytes:
    """Headless Chromium cez Playwright — spustí JS, počká na sieťový idle.
    Použije sa len ako posledná možnosť (pomalší, ~5–10s per stránka).
    Vracia bytes (UTF-8 enkódovaný HTML string).
    Ak je browser_ctx (playwright BrowserContext) poskytnutý, použije ho
    namiesto spúšťania nového Chromia — ušetrí ~3–5s na každej URL.
    """
    try:
        if browser_ctx is not None:
            page = await browser_ctx.new_page()
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3}",
                lambda r: r.abort()
            )
            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(1500)
            except Exception:
                pass
            await page.evaluate("document.querySelectorAll('[style*=\"display:none\"],[style*=\"visibility:hidden\"]').forEach(el => { el.style.display='block'; el.style.visibility='visible'; })")
            content = await page.content()
            await page.close()
            if content:
                print(f"✅ Playwright (shared ctx) OK pre {url} ({len(content)} znakov)")
                return content.encode("utf-8", errors="replace")
            return b""

        # Standalone režim — spustí vlastný browser (pomalší, pre debug endpoint)
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
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3}",
                lambda r: r.abort()
            )
            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(1500)
            except Exception:
                pass
            await page.evaluate("document.querySelectorAll('[style*=\"display:none\"],[style*=\"visibility:hidden\"]').forEach(el => { el.style.display='block'; el.style.visibility='visible'; })")
            content = await page.content()
            await browser.close()
            if content:
                print(f"✅ Playwright OK pre {url} ({len(content)} znakov)")
                return content.encode("utf-8", errors="replace")
            return b""
    except Exception as e:
        print(f"Playwright výnimka pre {url}: {e}")
        return b""

async def fetch_text_with_fallback(url: str, browser_ctx=None) -> str:
    """Reťaz fallbackov: httpx → cloudscraper+UA → Playwright → prázdny string.
    browser_ctx: voliteľný playwright BrowserContext — ak je poskytnutý,
    Playwright ho použije namiesto spúšťania nového Chromia.
    """
    html = fetch_html_httpx(url)
    if html:
        print(f"✅ httpx OK pre {url}")
        return extract_text_from_html(html)

    print(f"⚠️ httpx zlyhalo, skúšam cloudscraper+UA pre {url}")
    html = fetch_html_cloudscraper_with_ua(url)
    if html:
        return extract_text_from_html(html)

    print(f"⚠️ cloudscraper zlyhalo, skúšam Playwright pre {url}")
    html = await fetch_html_playwright(url, browser_ctx=browser_ctx)
    if html:
        text = extract_text_from_html(html)
        if not is_garbled_content(text):
            return text
        print(f"⚠️ Playwright vrátil garbled content pre {url}, skúšam Scrapling")

    print(f"🕵️ Scrapling ako finálny fallback pre {url}")
    scrapling_bytes = await fetch_html_scrapling(url)
    if scrapling_bytes:
        text = extract_text_from_html(scrapling_bytes)
        if not is_garbled_content(text):
            return text

    print(f"❌ Všetky fetch metódy zlyhali pre {url}")
    return ""

# --- Boilerplate filter (len cookie/GDPR clutter, NIE obchodné podmienky kde sú kontakty) ---
BOILERPLATE_KEYWORDS = [
    "cookies", "cookie", "súhlasím", "suhlasim", "prehliadač", "prehliadac",
    "gdpr",
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
    # Odmietni produktové kódy a čísla s písmenami (napr. 26051717BX)
    if re.search(r'[A-Za-z]', re.sub(r'^\+', '', num)):
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

    # 00421 / +421 / 421 + 9 SK  (00421XXXXXXXXX = 14 digits, 421XXXXXXXXX = 12)
    if digits.startswith('00421') and len(digits) == 14:
        return True
    if digits.startswith('421') and len(digits) == 12:
        return True
    # 00420 / +420 / 420 + 9 CZ
    if digits.startswith('00420') and len(digits) == 14:
        return True
    if digits.startswith('420') and len(digits) == 12:
        return True
    # SK mobil: 09XX XXX XXX (10 číslic, začína 09)
    if len(digits) == 10 and digits.startswith('09'):
        return True
    # SK pevná: 0[2-5]X... (10 číslic)
    if len(digits) == 10 and digits[0] == '0' and digits[1] in '2345':
        return True
    # CZ holých 9 číslic, mobil začína 6/7, pevná 2-5; SK mobil bez 0 (9XX...)
    if len(digits) == 9 and digits[0] in '23456789':
        return True
    # SK/CZ pevná linka bez leading 0 (napr. 33774800 = oblasť 033) — len predvoľby 2x-5x
    if len(digits) == 8 and digits[0] in '2345':
        return True
    return False


# --- Role keywords (SK / CZ / EN) ---
ROLE_KEYWORDS = [
    "riaditeľ", "riaditel", "ředitel", "reditel", "director", "ceo",
    "konateľ", "konatel", "jednatel", "jednateľ",
    "obchodný", "obchodny", "obchodní", "obchodni", "obchod", "sales",
    "vedúci", "veduci", "vedoucí", "vedouci", "head",
    "manažér", "manazer", "manažer", "manager",
    "kontaktná osoba", "kontaktna osoba", "kontaktní osoba", "kontaktni osoba",
    "majiteľ", "majitel", "majitel'",
    "prevádzkovateľ", "prevadzkovatel", "provozovatel",
    "zodpovedný vedúci", "zodpovedny veduci",
    "zodpovedná osoba", "zodpovedna osoba",
    "zastúpený", "zastupeny",
]

# Ignorované domény (dopravcovia, štátne inštitúcie, banky, Heureka)
IGNORED_CONTACT_DOMAINS: set = {
    "soi.sk", "coi.cz",
    "dpd.com", "dpd.sk", "dpd.cz", "dpdgroup.com",
    "gls-group.com", "gls-parcelshop.sk", "glsgroup.eu", "gls.sk", "gls.cz",
    "ups.com", "ups.sk", "ups.cz",
    "sps-sro.sk", "sps.sk",
    "packeta.com", "packeta.sk", "packeta.cz", "packetery.com",
    "zasilkovna.cz", "zasilkovna.sk",
    "heureka.sk", "heureka.cz",
    "slsp.sk", "vub.sk", "tatrabanka.sk",
    "csas.cz", "csob.sk", "csob.cz",
    "sberbank.sk", "unicreditbank.sk", "unicreditbank.cz",
    "raiffeisen.sk", "rb.cz", "postovabanka.sk",
    "kb.cz", "moneta.cz", "airbank.cz",
}

_IGNORED_CTX_RE = re.compile(
    r'\bsoi\b|obchodn[aá] in[sš]pekcia|česká obchodní inspekce'
    r'|\bdpd\b|\bgls\b|\bups\b|\bpacketa\b|zásilkovna|zasilkovna'
    r'|\bsps\b|heureka|\bbanka\b|\bbank\b'
    r'|štátna|statna|statni|státní',
    re.IGNORECASE,
)

def _email_is_ignored(addr: str, context: str = "") -> bool:
    """True ak email patrí dopravcovi, SOI, banke, Heureke."""
    if addr and "@" in addr:
        domain = addr.split("@")[-1].lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain in IGNORED_CONTACT_DOMAINS:
            return True
        for ign in IGNORED_CONTACT_DOMAINS:
            if domain.endswith("." + ign):
                return True
    if context and _IGNORED_CTX_RE.search(context):
        return True
    return False

# Explicitné rozsahy SK/CZ veľkých a malých písmen.
# Nesmieme použiť [A-ZÁ-Ž] – ten rozsah obsahuje aj malé Unicode písmená (é, í, ...)
# a pattern by zachytával `ér` z `manažér` ako začiatok mena.
_UPPER = "A-ZÁČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ"
_LOWER = "a-záčďéíľĺňóôŕšťúýž"
# Titul + 2-3 Capitalized slová oddelené iba medzerou/tabom (NIE newline – meno sa nezalamuje cez riadky)
_NAME_PATTERN = re.compile(
    rf'(?:Mgr\.|Ing\.|Bc\.|JUDr\.|MUDr\.|PhDr\.|prof\.|doc\.|MVDr\.|RNDr\.)?[ \t]*'
    rf'[{_UPPER}][{_LOWER}]{{2,}}(?:[ \t]+[{_UPPER}][{_LOWER}]{{2,}}){{1,2}}'
)
# Slová ktoré nie sú meno – vyhodíme ich keď ich pattern zachytí ako "druhé slovo"
_NOT_A_NAME_WORD = {
    "Email", "Mail", "Telefón", "Telefon", "Mobil", "Phone", "Tel",
    "Web", "Adresa", "Address", "Sídlo", "Sidlo", "Kontakt", "Contact",
    "Firma", "Spoločnosť", "Spolocnost", "Company", "Office", "Info",
    "Pondelok", "Utorok", "Streda", "Štvrtok", "Piatok", "Sobota", "Nedeľa",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Wi", "Sk", "Cz", "Eu", "Id", "Ok", "Sr",
    "Kvatro", "Comp", "Sro", "Ltd", "Inc", "As", "Zs",
    # E-shop navigácia, UI elementy, kategórie — nesmú byť meno osoby
    "Prihlásenie", "Hľadať", "Darčeky", "Darček", "Nákupný", "Košík",
    "Novinky", "Zákaznícka", "Zákaznícky", "Podpora", "Doprava", "Platba",
    "Reklamácia", "Vrátenie", "Podmienky", "Ochrana", "Údajov",
    "Program", "Veľkoobchodný", "Informácie", "Kontaktné",
    "Horúce", "Prázdny", "Tovar", "Zľavy", "Akcia", "Nový", "Výpredaj",
    "Kategória", "Produkt", "Objednávka", "Dopravné", "Platobné",
    "Faktúra", "Doklad", "Záručný", "Servis", "Technická",
    "Slovensko", "Česko", "Praha", "Bratislava", "Žilina", "Košice",
    "Január", "Február", "Marec", "Apríl", "Máj", "Jún", "Júl", "August",
    "September", "Október", "November", "December",
    "Registrácia", "Odhlásenie", "Nastavenia", "Profil",
}

def _de_accent(s: str) -> str:
    """Odstráni diakritiku — 'Nákupný' → 'Nakupny'. Umožní porovnanie blacklistu
    aj s textom ktorý prišiel bez diakritiky (terminál, niektoré web-stránky)."""
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

# Pre-normalizovaný (bez diakritiky, lowercase) blacklist pre rýchle porovnanie.
_NOT_A_NAME_WORD_PLAIN: frozenset = frozenset(_de_accent(w).lower() for w in _NOT_A_NAME_WORD)

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
    normalized = re.sub(r'\n+', ' ', normalized)

    # === EMAILS ===
    seen_emails = set()
    for m in re.finditer(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', normalized):
        addr = m.group(0)
        key = addr.lower()
        if key in seen_emails:
            continue
        ctx = _context(normalized, m.start(), m.end())
        if _email_is_ignored(addr, ctx):
            continue
        seen_emails.add(key)
        result["emails"].append({
            "value": addr,
            "context": ctx
        })

    # === PHONES === (regex + validácia)
    # Normalizuj ďalšie Unicode medzery ktoré \xa0 replace nezachytí
    for _sp in [' ', ' ', ' ', ' ', '­']:
        normalized = normalized.replace(_sp, ' ')
    # Odstráň tel:/phone:/mobil:/telephone: prefixes aby regex zachytil číslo za nimi
    # (napr. "tel:+421948028999" → "+421948028999")
    stripped_for_phones = normalized
    stripped_for_phones = re.sub(r'\btel:\s*', '', stripped_for_phones, flags=re.IGNORECASE)
    stripped_for_phones = re.sub(r'\bphone:\s*', '', stripped_for_phones, flags=re.IGNORECASE)
    stripped_for_phones = re.sub(r'\bmobil:\s*', '', stripped_for_phones, flags=re.IGNORECASE)
    stripped_for_phones = re.sub(r'\btelephone:\s*', '', stripped_for_phones, flags=re.IGNORECASE)
    phone_pattern = re.compile(
        r'(?:'
        # International prefix (+421, +420, 00421, 00420)
        r'(?:00421|00420|\+421|\+420)\s?(?:\d[\s\-]?){8}\d'
        r'|'
        # SK landline 0X / XXXX XXXX — predvoľba + separator (aj "02 / 1234 5678", "02/58272 172") + číslo
        r'0[1-9][\s\/\-]{1,3}\d{3,5}[\s\/\-]?\d{3,4}'
        r'|'
        # SK mobile 09XX XXX XXX (10 číslic)
        r'0[689]\d{2}[\s\-\/]?\d{3}[\s\-\/]?\d{3}'
        r'|'
        # Ostatné 0XX XXX XXX (SK/CZ s leading 0, 10 číslic) — posledná skupina 3 ALEBO 4 číslice
        r'0\d{2}[\s\-\/]?\d{3}[\s\-\/]?\d{3,4}'
        r'|'
        # Bare 9 číslic bez predvoľby (CZ/SK mobil/pevná): 317804046, 777592979 ...
        r'(?<!\d)[2-9]\d{2}[\s\-\/]?\d{3}[\s\-\/]?\d{3}(?!\d)'
        r'|'
        # Bare 8 číslic (SK/CZ pevná bez leading 0): 33774800 — len oblastné predvoľby 2x-5x
        r'(?<!\d)[2-5]\d[\s\-\/]?\d{3}[\s\-\/]?\d{3}(?!\d)'
        r')'
    )
    seen_phones = set()
    for m in phone_pattern.finditer(stripped_for_phones):
        raw = m.group(0).strip()
        norm = re.sub(r'\D', '', raw)
        if norm in seen_phones:
            continue
        if not is_valid_phone(raw):
            continue
        seen_phones.add(norm)
        # Kontext ber z pôvodného norm_text (pred odstránením tel: prefixov)
        orig_idx = normalized.find(raw)
        if orig_idx >= 0:
            ctx_start, ctx_end = orig_idx, orig_idx + len(raw)
        else:
            ctx_start, ctx_end = m.start(), m.end()
        result["phones"].append({
            "value": raw,
            "context": _context(normalized, ctx_start, ctx_end)
        })

    # === NAMES === blízko role kľúčových slov
    seen_names = set()
    for kw in ROLE_KEYWORDS:
        for m in re.finditer(re.escape(kw), normalized, re.IGNORECASE):
            window_start = max(0, m.start() - 250)
            window_end = min(len(normalized), m.end() + 250)
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
            window_start = max(0, em.start() - 250)
            window_end = min(len(normalized), em.end() + 250)
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
                if len(result["names"]) >= 20:
                    return result

    # === NAMES === blízko telefónov (špeciálne pravidlo 4: meno + telefón → "Obchodné oddelenie")
    for phone_entry in result["phones"]:
        phone_val = phone_entry["value"]
        phone_norm = re.sub(r'\s+', r'\\s*', re.escape(phone_val.strip()))
        try:
            phone_re = re.compile(phone_norm)
        except Exception:
            continue
        for pm in phone_re.finditer(normalized):
            window_start = max(0, pm.start() - 200)
            window_end = min(len(normalized), pm.end() + 200)
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
                    "near_role": f"phone:{phone_val}",
                    "context": _context(normalized, abs_start, abs_end)
                })
                if len(result["names"]) >= 20:
                    return result

    # WARNING keď všetky kandidáty prázdne
    if not result["emails"] and not result["phones"] and not result["names"]:
        print(f"WARNING: 0 candidates found — možný JS-only render alebo blokácia")

    return result

def extract_with_ai(text: str, company_name_hint: str = "") -> Dict[str, Any]:
    """AI vyberie JEDEN najlepší obchodný kontakt zo zoznamu kandidátov (B2B sales researcher)."""
    if not text:
        return {}
    candidates = extract_all_candidates(text)
    cleaned_preview = filter_boilerplate(text)[:3000]

    all_phones_list = [p["value"] for p in candidates["phones"][:15]]
    all_phones_str = ", ".join(all_phones_list) if all_phones_list else "žiadne"

    payload = {
        "company_name_hint": company_name_hint or "",
        "emails": candidates["emails"][:15],
        "phones": candidates["phones"][:15],
        "names": candidates["names"][:15],
    }

    prompt = f"""Si B2B sales researcher. Nájdi JEDEN najlepší obchodný kontakt spoločnosti.

KANDIDÁTI (deduplikovaní, telefóny validované):
{json.dumps(payload, ensure_ascii=False, indent=2)}

Celkový počet nájdených telefónov: {len(candidates["phones"])}
Všetky nájdené telefóny: {all_phones_str}

VYČISTENÝ TEXT (prvých 3000 znakov):
{cleaned_preview}

PRIORITA KONTAKTU (vyber JEDEN kontakt s najvyšším skóre):
1. jednateľ/konateľ/jednatel/CEO/majiteľ/owner — meno+email+tel = 100b → role_category="CEO"
2. obchodný riaditeľ/obchodní ředitel/sales director = 85b → role_category="obchodne"
3. obchodné oddelenie/prodejní oddělenie s menom osoby = 70b → role_category="obchodne"
4. ŠPECIÁLNE — KONTAKTNÝ BLOK: ak na kontaktnej stránke existuje blok kde je meno osoby v rovnakom oddiele (do 400 znakov) ako email alebo telefón — aj keď sú oddelené adresou, IČO, DIČ alebo PSČ — SPOJ ich do jedného kontaktu. Typická štruktúra SK/CZ e-shopov: 'Prevádzkovateľ: [MENO] [adresa] [IČO] [DIČ] Email: [email] Telefón: [tel]' 'Zodpovedný vedúci: [MENO] E-mail: [email]' 'Konateľ: [MENO] [adresa] Tel: [tel]' V týchto prípadoch: contact_name=[MENO], role=nadpis bloku (Prevádzkovateľ/Zodpovedný vedúci/Konateľ), role_category='CEO', email a phone z toho istého bloku. IGNORUJ IČO/DIČ/PSČ/IBAN ako 'čísla' — nie sú to telefóny.
5. menný email (meno.priezvisko@ alebo meno@firma) bez roly = 55b → role_category podľa kontextu
6. objednavky@/orders@/objednávky@/prodej@/marketing@/reklama@ = 40b → role_category="obchodne" (objednávkové/marketingové oddelenie = priamy biznis kontakt)
7. eshop@/shop@/obchod@/svietidla@/e-shop@ = 35b → role_category="eshop"
8. info@/kontakt@/hello@/podpora@ + 2+ RÔZNYCH telefónov (all_phones má 2+ čiarkou oddelených čísiel) + ŽIADNA konkrétna osoba → role_category="infolinka"
9. info@/kontakt@/hello@ s 0-1 telefónmi alebo keď je len 1 unikátne číslo → role_category="info", 20b
10. len telefóny (3+) bez akéhokoľvek emailu a mena → role_category="infolinka", 15b
POZNÁMKA k pravidlu 8: rovnaké číslo viackrát sa počíta ako 1 (niet infolinka); rôzne čísla (mobil + pevná linka) = 2 → infolinka

ŠPECIÁLNE PRAVIDLÁ:
- all_phones = VŠETKY validné telefóny z celej stránky (všetky z poľa phones[])
- Viac telefónov pri jednom kontakte → ulož VŠETKY do all_phones
- Meno v emaile (iva.absolonova@) → contact_name="Iva Absolonová"
- Ignoruj: bankové účty, PSČ, IČO, DIČ, čísla kratšie ako 8 číslic
- Ignoruj kontakty SOI, ČOI, Heureka, dopravcov (DPD/GLS/UPS/SPS/Packeta/Zásilkovna), bánk
- Roly SK/CZ/EN: riaditeľ/ředitel/director, konateľ/jednatel, obchod/obchodní/sales, vedúci/vedoucí, prevádzkovateľ/provozovatel, majiteľ/majitel
- Ak je meno blízko "zodpovedný vedúci" alebo "prevádzkovateľ" → role="konateľ", role_category="CEO"
- PREFERUJ email blízko mena pred generickým emailom
- contact_name z poľa names[], alebo vytiahni z local-part menného emailu (ferenci.ladislav → Ferenci Ladislav)
- contact_name MUSÍ byť reálne meno osoby: každé slovo min. 3 znaky, žiadne skratky (Wi, Sk, Cz, OK), nie produktové kódy
- phone MUSÍ byť JEDNO číslo z phones[].value, nie celá veta — ak phones[] je prázdny, daj null

Vráť LEN čistý JSON:
{{
  "primary_identifier": "názov firmy alebo doména",
  "contact_name": "meno priezvisko alebo null",
  "role": "konkrétna rola alebo null",
  "role_category": "CEO|obchodne|eshop|info|infolinka",
  "email": "email alebo null",
  "phone": "hlavný telefón z phones[].value alebo null",
  "all_phones": "všetky telefóny zo stránky čiarkou, alebo null",
  "priority_score": číslo,
  "reasoning": "1-2 vety"
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
        result["_candidates"] = candidates
        # Ak AI nevyplnila all_phones, doplníme zo všetkých kandidátov
        if not result.get("all_phones") and all_phones_list:
            result["all_phones"] = ", ".join(all_phones_list)
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

def role_category_to_points(role_category: str, all_phones: str = "") -> int:
    """Bodovanie podľa role_category z AI výstupu (nová logika)."""
    if not role_category:
        return 0
    rc = role_category.lower().strip()
    if rc == "ceo":
        return 50
    if rc == "obchodne":
        return 40
    if rc == "eshop":
        return 25
    if rc == "infolinka":
        phones = [p.strip() for p in (all_phones or "").split(",") if p.strip()]
        return 20 if len(phones) >= 3 else 15
    if rc == "info":
        return 10
    return 10

# Generické emailové prefixy (oddelenie/schránka, nie konkrétna osoba)
GENERIC_EMAIL_PREFIXES = [
    "info", "podpora", "support", "office", "kontakt", "contact",
    "sales", "obchod", "reklamacia", "reklamácia", "admin", "hello",
    "ahoj", "objednavky", "objednávky", "eshop", "shop", "mail", "post", "noreply",
    "marketing", "reklama", "helpdesk", "dotazy", "servis", "info2",
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

def is_ignored_contact(email: str = "", context: str = "") -> bool:
    """True ak email patrí dopravcovi, SOI, banke, Heureke (použitie v API layer)."""
    return _email_is_ignored(email, context)

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
                  role: Optional[str], website: Optional[str],
                  role_category: Optional[str] = None,
                  all_phones: Optional[str] = None) -> Dict[str, Any]:
    """Bodovanie kontaktu. Ak AI vrátila role_category, použije novú logiku (Fáza 3)."""
    direct_personal_email = bool(email) and not is_generic_email(email) and \
        is_personal_email(email, contact_name, website)

    if role_category:
        contact_points = role_category_to_points(role_category, all_phones or "")
    else:
        # Starý fallback scoring
        if direct_personal_email:
            contact_points = 45
        elif email and is_generic_email(email):
            contact_points = 10
        elif email:
            contact_points = 10
        elif phone:
            contact_points = 20
        else:
            contact_points = 0
        role_points = role_to_points(role) if role else 0
        contact_points = max(contact_points, role_points)

    return {
        "contact_points": contact_points,
        "direct_personal_email": direct_personal_email,
        "role_category": role_category or "",
    }

class ScrapeRequest(BaseModel):
    url: str

def extract_nav_links(html: bytes, base_url: str) -> List[str]:
    """Extracts all internal links from navigation, footer, and header elements.
    Returns list of absolute URLs. Prioritizes contact/about pages."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html.decode("utf-8", errors="replace"), "html.parser")

        # Look in nav, footer, header first — then full page
        search_areas = (
            soup.find_all(["nav", "footer", "header"]) or
            [soup]
        )

        contact_keywords = [
            "kontakt", "contact", "o-nas", "o firme", "about", "team", "tym",
            "vedenie", "management", "impressum", "napiste", "napíšte"
        ]

        found_urls = []
        seen = set()

        # Priority pass: contact/about links
        for area in search_areas:
            for a in area.find_all("a", href=True):
                href = a["href"].strip()
                text = a.get_text(strip=True).lower()

                # Skip external, mailto, tel, anchors
                if href.startswith(("mailto:", "tel:", "#", "javascript:")):
                    continue
                if href.startswith("http") and not href.startswith(base_url):
                    continue

                # Build absolute URL
                if href.startswith("http"):
                    abs_url = href.rstrip("/")
                elif href.startswith("/"):
                    abs_url = base_url + href.rstrip("/")
                else:
                    abs_url = base_url + "/" + href.rstrip("/")

                if abs_url in seen or abs_url == base_url:
                    continue
                seen.add(abs_url)

                # Prioritize contact/about pages by link text or URL
                is_priority = any(kw in text or kw in href.lower() for kw in contact_keywords)
                if is_priority:
                    found_urls.insert(0, abs_url)  # prepend priority links
                else:
                    found_urls.append(abs_url)

        return found_urls[:20]  # cap at 20 to avoid scraping entire site
    except Exception as e:
        print(f"extract_nav_links výnimka: {e}")
        return []

async def _scrape_all_pages(base_url: str) -> Dict[str, Any]:
    """Optimalizované scrapovanie pre Render free tier.

    Stratégia (poradí kroky):
      1. Stiahni homepage cez httpx → vytiahni JSON-LD kontakty (zadarmo, žiadny JS)
      2. Paralelne (asyncio.gather, Semaphore=5) stiahni VŠETKY subpages cez
         httpx → cloudscraper. Toto je rýchle a nepotrebuje Playwright.
      3. Heuristika has_good_contacts(): ak máme email + (telefón alebo meno),
         Playwright vôbec nespúšťame.
      4. Ak nemáme dosť kontaktov, spusti Playwright (1 browser instance) pre
         max 3 stránky: homepage + /kontakt + /o-nas (prvé existujúce).
      5. Po každej Playwright stránke: page.close() + context.clear_cookies()
         + gc.collect() pre RAM management.
      6. Ak všetko zlyhalo: WHOIS lookup ako absolútny posledný fallback.

    Vracia dict: {'text': str, 'jsonld': dict, 'whois': dict}
    """
    contact_priority_paths = [
        "obchodne-podmienky", "vseobecne-obchodne-podmienky", "vop",
        "obchodni-podminky", "vseobecne-obchodni-podminky",
        "kontaktne-informacie", "kontaktne-udaje", "kontaktne-info",
        "kontakt", "contact", "kontakty",
        "o-nas", "o-firme", "o-spolocnosti", "about-us", "onas",
        "tym", "team", "vedenie", "management",
        "impressum", "prevadzka", "organizacna-struktura",
    ]
    other_paths = [p for p in SUBPAGE_PATHS if p not in contact_priority_paths]
    all_paths = contact_priority_paths + other_paths

    jsonld_data: Dict[str, Any] = {}
    whois_data: Dict[str, Any] = {}

    # === KROK 1: homepage cez httpx + JSON-LD ===
    home_bytes = fetch_html_httpx(base_url)
    if home_bytes:
        jsonld_data = extract_jsonld_contacts(home_bytes)

    home_text = extract_text_from_html(home_bytes) if home_bytes else ""

    # Detekuj Cloudflare garbled content — ak httpx dostal zablokovanú odpoveď
    if is_garbled_content(home_text):
        print(f"⚠️ Garbled content na homepage {base_url} — skúšam Scrapling StealthyFetcher")
        scrapling_bytes = await fetch_html_scrapling(base_url)
        if scrapling_bytes:
            scrapling_text = extract_text_from_html(scrapling_bytes)
            if not is_garbled_content(scrapling_text):
                print(f"✅ Scrapling vrátil čistý obsah pre {base_url}")
                home_bytes = scrapling_bytes
                home_text = scrapling_text
                jsonld_data = extract_jsonld_contacts(home_bytes)
            else:
                print(f"❌ Scrapling tiež vrátil garbled content pre {base_url}")

    # Discover actual navigation links from homepage HTML
    nav_links = extract_nav_links(home_bytes, base_url) if home_bytes else []
    print(f"🔗 Nav links objavené: {len(nav_links)} — {nav_links[:5]}")

    # === KROK 2: paralelný httpx + cloudscraper na všetky subpages ===
    sem = asyncio.Semaphore(5)  # max 5 concurrent fetches pre Render free tier (0.5 CPU)

    async def _fetch_fast(url: str) -> str:
        """Skúsi httpx, potom cloudscraper, potom retry s trailing slash. Bez Playwright.
        Garbled/binary obsah (Cloudflare block) sa nezaráta — vracia prázdny string."""
        async with sem:
            loop = asyncio.get_event_loop()
            html = await loop.run_in_executor(None, fetch_html_httpx, url)
            if not html:
                html = await loop.run_in_executor(None, fetch_html_cloudscraper_with_ua, url)
            if not html and not url.endswith("/"):
                # Retry s trailing slash — niektoré servery redirectujú /path → /path/
                url2 = url + "/"
                html = await loop.run_in_executor(None, fetch_html_httpx, url2)
                if not html:
                    html = await loop.run_in_executor(None, fetch_html_cloudscraper_with_ua, url2)
            text = extract_text_from_html(html) if html else ""
            # Odfiltruj Cloudflare-zablokovaný garbled obsah
            if text and is_garbled_content(text):
                print(f"⚠️ Garbled subpage (Cloudflare?): {url}")
                text = ""
            if text and len(text) > 100:
                print(f"✅ Subpage OK: {url} ({len(text)} znakov)")
            else:
                print(f"❌ Subpage prázdna: {url}")
            return text

    # Use discovered nav links first, fall back to hardcoded paths
    if nav_links:
        # Merge: nav_links (real) + classic paths (fallback), deduplicated
        classic_urls = [f"{base_url}/{p}" for p in all_paths]
        combined_urls = nav_links.copy()
        for u in classic_urls:
            if u not in combined_urls:
                combined_urls.append(u)
        subpage_urls = combined_urls[:30]  # cap total
    else:
        subpage_urls = [f"{base_url}/{p}" for p in all_paths]
    results = await asyncio.gather(*[_fetch_fast(u) for u in subpage_urls], return_exceptions=True)

    sub_texts: List[str] = []
    for r in results:
        if isinstance(r, str) and r:
            sub_texts.append(r)

    combined = ("\n".join(sub_texts) + "\n" + home_text).strip()

    # === KROK 3: Podmienky/kontaktne-inf stránky fetchuj cez Playwright VŽDY ===
    # Tieto stránky obsahujú zodpovedný vedúci / konateľ ale httpx ich nedostane
    # (JS-rendered alebo Cloudflare) — preto ich fetchujeme bez ohľadu na has_good_contacts.
    _ALWAYS_PW_KW = [
        "podmienk", "podminky", "vop", "kontaktne-inf",
        "kontaktne-ud", "o-firme", "o-spolocnosti", "impressum",
    ]
    always_pw_urls: List[str] = []
    for nav_url in nav_links:
        if any(kw in nav_url.lower() for kw in _ALWAYS_PW_KW):
            if nav_url not in always_pw_urls:
                always_pw_urls.append(nav_url)
        if len(always_pw_urls) >= 3:
            break
    # Fallback na hardcoded ak nav_links neobsahuje žiadnu podmienky/kontaktne-inf URL
    if not always_pw_urls:
        for p in ["obchodne-podmienky", "vseobecne-obchodne-podmienky", "vop", "kontaktne-informacie"]:
            always_pw_urls.append(f"{base_url}/{p}")
    always_pw_urls = always_pw_urls[:3]

    # === KROK 4: has_good_contacts + role keyword — určuje či fetchujeme AJ general stránky ===
    _ROLE_KW_RE = re.compile(
        r'zodpoved|konateľ|konatel|majiteľ|majitel|prevadzkov|prevádzkov|'
        r'jednateľ|jednatel|riaditeľ|riaditel|odpoved|\bceo\b|\bowner\b|\bfounder\b',
        re.IGNORECASE
    )
    has_role_kw = bool(_ROLE_KW_RE.search(combined))
    need_general_pw = not (has_good_contacts(combined) and has_role_kw)

    if need_general_pw:
        reason = "nedali dosť kontaktov" if not has_good_contacts(combined) else "chýba role keyword"
        print(f"⚡ {reason} — Playwright pre podmienky + general stránky")
        pw_urls = [base_url] + [u for u in always_pw_urls]
        # Pridaj ďalšie kontaktné stránky z nav_links
        pw_general_kw = ["kontakt", "contact", "o-nas", "about", "napiste"]
        for nav_url in nav_links:
            if any(kw in nav_url.lower() for kw in pw_general_kw):
                if nav_url not in pw_urls:
                    pw_urls.append(nav_url)
            if len(pw_urls) >= 5:
                break
        # Hardcoded fallback
        if len(pw_urls) < 2:
            for p in ["kontakt", "contact", "kontakty"]:
                c = f"{base_url}/{p}"
                if c not in pw_urls:
                    pw_urls.append(c)
                    break
    else:
        print(f"✅ httpx stačili (email+tel+role). Playwright len pre podmienky: {always_pw_urls}")
        pw_urls = list(always_pw_urls)

    pw_urls = pw_urls[:5]

    pw_instance = None
    pw_browser = None
    browser_ctx = None
    pw_texts: List[str] = []
    try:
        pw_instance = await async_playwright().start()
        pw_browser = await pw_instance.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-gpu", "--single-process"],
        )
        browser_ctx = await pw_browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            locale="sk-SK",
            extra_http_headers={
                "Accept-Language": "sk-SK,sk;q=0.9,cs;q=0.8,en-US;q=0.7",
                "Referer": "https://www.google.com/",
            },
        )
        for url in pw_urls:
            html = await fetch_html_playwright(url, browser_ctx=browser_ctx)
            if html:
                # Vytiahni JSON-LD ak sme ho ešte nemali
                if not jsonld_data:
                    jsonld_data = extract_jsonld_contacts(html)
                # Vlastný extract pre Playwright stránky — obíde 25k limit extract_text_from_html.
                # Odstraňujeme nav/header (boilerplate) a berieme posledných 30k znakov
                # kde sú obchodné podmienky a kontaktné info (Martin Zachar, zodpovedný vedúci).
                _html_str = html.decode('utf-8', errors='replace')
                _html_str = ftfy.fix_text(_html_str)
                _soup = BeautifulSoup(_html_str, 'html.parser')
                for _tag in _soup(["script", "style", "nav", "header"]):
                    _tag.decompose()
                _full_text = _soup.get_text(separator=' ', strip=True)
                _full_text = _full_text.replace('\xa0', ' ')
                page_text = _full_text[-50000:] if len(_full_text) > 50000 else _full_text
                pw_texts.append(page_text)
            # Memory cleanup po každej stránke
            try:
                await browser_ctx.clear_cookies()
            except Exception:
                pass
            gc.collect()
    except Exception as e:
        print(f"Playwright loop výnimka: {e}")
    finally:
        if pw_browser:
            try:
                await pw_browser.close()
            except Exception:
                pass
        if pw_instance:
            try:
                await pw_instance.stop()
            except Exception:
                pass
        gc.collect()

    combined = (combined + "\n" + "\n".join(pw_texts)).strip()

    # === KROK 5: WHOIS ako absolútny fallback ===
    if not has_good_contacts(combined) and not jsonld_data.get("email"):
        whois_data = whois_contacts(base_url)

    return {"text": combined, "jsonld": jsonld_data, "whois": whois_data}


@app.post("/api/leads/scrape")
async def scrape_lead(req: ScrapeRequest, user=Depends(verify_jwt)):
    try:
        base_url = req.url.strip()
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url
        base_url = base_url.rstrip('/')

        scrape_out = await _scrape_all_pages(base_url)
        combined_text = scrape_out["text"]
        jsonld_data = scrape_out.get("jsonld", {})
        whois_data = scrape_out.get("whois", {})

        if not combined_text and not jsonld_data and not whois_data:
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

        # JSON-LD a WHOIS dopĺňajú údaje keď AI/regex zlyhali
        email = extracted.get("email") or first_email or jsonld_data.get("email") or whois_data.get("email")
        phone = extracted.get("phone") or first_phone or jsonld_data.get("phone")
        name = extracted.get("primary_identifier") or jsonld_data.get("name") or base_url.split("//")[-1].split("/")[0]
        contact_name = extracted.get("contact_name") or jsonld_data.get("contact_name") or whois_data.get("contact_name")
        role = extracted.get("role") or jsonld_data.get("role")
        role_category = extracted.get("role_category") or ""
        all_phones = extracted.get("all_phones") or ""
        priority_score = extracted.get("priority_score")
        reasoning = extracted.get("reasoning")

        contact_eval = score_contact(email, phone, contact_name, role, base_url,
                                     role_category=role_category, all_phones=all_phones)
        contact_points = contact_eval["contact_points"]
        direct_personal_email = contact_eval["direct_personal_email"]
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
                "role_category": role_category,
                "all_phones": all_phones,
                "priority_score": priority_score,
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
                        "all_phones": all_phones,
                        "contact_name": contact_name,
                        "contact_role": role,
                        "role_category": role_category,
                        "priority_score": priority_score,
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
                        "all_phones": all_phones,
                        "contact_name": contact_name,
                        "contact_role": role,
                        "role_category": role_category,
                        "priority_score": priority_score,
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
    scrape_out = await _scrape_all_pages(base_url)
    combined_text = scrape_out["text"]
    jsonld_data = scrape_out.get("jsonld", {})
    whois_data = scrape_out.get("whois", {})

    # AI extrakcia (s hint názvom firmy z domény)
    domain_hint = _domain_of(base_url)
    extracted = extract_with_ai(combined_text, company_name_hint=domain_hint) or {}
    candidates = extracted.pop("_candidates", None) or extract_all_candidates(combined_text)

    # Fallback hodnoty z kandidátov
    first_email = candidates["emails"][0]["value"] if candidates["emails"] else None
    first_phone = candidates["phones"][0]["value"] if candidates["phones"] else None
    fallback = {"email": first_email, "phone": first_phone}

    # JSON-LD a WHOIS doplňujú hodnoty pre kontaktné skóre
    email = extracted.get("email") or first_email or jsonld_data.get("email") or whois_data.get("email")
    phone = extracted.get("phone") or first_phone or jsonld_data.get("phone")
    contact_name = extracted.get("contact_name") or jsonld_data.get("contact_name") or whois_data.get("contact_name")
    role = extracted.get("role") or jsonld_data.get("role")
    role_category = extracted.get("role_category") or ""
    all_phones = extracted.get("all_phones") or ""
    priority_score = extracted.get("priority_score")

    # Ak AI nedala primary_identifier (combined_text bol prázdny), použijeme JSON-LD/doménu
    if not extracted.get("primary_identifier"):
        extracted["primary_identifier"] = jsonld_data.get("name") or domain_hint
    if email and not extracted.get("email"):
        extracted["email"] = email
    if phone and not extracted.get("phone"):
        extracted["phone"] = phone
    if contact_name and not extracted.get("contact_name"):
        extracted["contact_name"] = contact_name
    if role and not extracted.get("role"):
        extracted["role"] = role

    contact_eval = score_contact(email, phone, contact_name, role, base_url,
                                 role_category=role_category, all_phones=all_phones)

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
        # Kľúčové polia pre rýchle porovnanie (expected vs actual)
        "contact_name": contact_name,
        "role_category": role_category,
        "email": email,
        "phone": phone,
        "all_phones": all_phones,
        "priority_score": priority_score,
        # Všetci kandidáti (regex)
        "candidates": candidates,
        # Spätná kompatibilita pre starý klient
        "regex_fallback": fallback,
        # Kontaktné skóre
        "contact_scoring": contact_eval,
        # Free fallbacky
        "jsonld": jsonld_data,
        "whois": whois_data,
    }


def _is_ico_context(context: str) -> bool:
    """Vráti True ak kontext okolo čísla naznačuje že ide o IČO/DIČ/IBAN, nie telefón."""
    if not context:
        return False
    ctx_lower = context.lower()
    return bool(re.search(
        r'ičo|ico|ič dph|ic dph|dič|dic|dič dph'
        r'|iban|č\.\s*účtu|cislo uctu|číslo účtu'
        r'|vložka|vlozka|oddiel|obch\.\s*reg|obchodný register|obchodny register'
        r'|bankové|bankove|banka',
        ctx_lower
    ))


# Kľúčové slová ktoré hľadáme v kontexte telefónu (pattern, ľudský label)
_RAW_KW_PATTERNS: List[tuple] = [
    (re.compile(r'zodpovedný\s+vedúci|zodpovedny\s+veduci|zodpovedn[áa]\s+osoba', re.IGNORECASE), None),
    (re.compile(r'konateľ(?:ka)?|konatel(?:ka)?', re.IGNORECASE), None),
    (re.compile(r'jednateľ(?:ka)?|jednatel(?:ka)?', re.IGNORECASE), None),
    (re.compile(r'majiteľ(?:ka)?|majitel(?:ka)?', re.IGNORECASE), None),
    (re.compile(r'prevádzkovateľ(?:ka)?|prevadzkovatel(?:ka)?|provozovatel(?:ka)?', re.IGNORECASE), None),
    (re.compile(r'riaditeľ(?:ka)?|riaditel(?:ka)?|ředitel(?:ka)?', re.IGNORECASE), None),
    (re.compile(r'\bCEO\b|\bCTO\b|\bCFO\b|\bCOO\b', re.IGNORECASE), None),
    (re.compile(r'\bowner\b|\bfounder\b', re.IGNORECASE), None),
    (re.compile(r'obchodn[eéí]\s+oddeleni[ee]|obchodní\s+oddělení', re.IGNORECASE), None),
    (re.compile(r'\bobchod(?:ný|ny|ní|ni)?\b', re.IGNORECASE), None),
    (re.compile(r'\bpredaj\b|\bsales\b', re.IGNORECASE), None),
    (re.compile(r'odpovědn[aá]\s+osoba|odpovedna\s+osoba|odpovědná\s+osoba', re.IGNORECASE), None),
    (re.compile(r'zodpovedn[áa]\s+osoba|zodpovědná\s+osoba', re.IGNORECASE), None),
    (re.compile(r'zodpovedn[yý]\s+zástupca|zodpovedny\s+zastupca', re.IGNORECASE), None),
    (re.compile(r'kontaktn[eé]\s+údaje|kontaktne\s+udaje', re.IGNORECASE), None),
]
# Pattern pre meno osoby (2 veľké slová, každé min 4 znaky = 1 veľké + 3 malé)
_RAW_NAME_PAT = re.compile(
    rf'(?:Mgr\.|Ing\.|Bc\.|JUDr\.|MUDr\.|PhDr\.|prof\.|doc\.|MVDr\.|RNDr\.)?\s*'
    rf'([{_UPPER}][{_LOWER}]{{3,}}\s+[{_UPPER}][{_LOWER}]{{3,}})'
)


def _extract_klucove_slova(context: str) -> List[str]:
    """Vráti zoznam kľúčových slov a mien nájdených v kontexte telefónneho čísla.

    Pravidlá:
    - Mená hľadá LEN v ±200-znakovom okruhu okolo nájdeného role keyword.
    - Ak kontext neobsahuje žiadny role keyword → žiadne mená (ochrana pred navigáciou).
    - Meno match ktorý sa PREKRÝVA so samotným role keyword spanom je preskočený
      (zabraňuje 'Prihlasenie Zodpovedny' keď 'Zodpovedny' je súčasť role keywordu).
    - Blacklist sa porovnáva BEZ diakritiky: 'Nakupny' == 'Nákupný'.
    """
    found: List[str] = []
    seen_lower: set = set()

    # Rola keywords — zbieraj aj ich pozície pre hľadanie mien
    role_spans: List[tuple] = []
    for pat, _ in _RAW_KW_PATTERNS:
        for m in pat.finditer(context):
            val = m.group(0).strip()
            if val.lower() not in seen_lower:
                seen_lower.add(val.lower())
                found.append(val)
            role_spans.append((m.start(), m.end()))

    # Mená osôb — iba v ±200-znakovom okruhu okolo každého role keyword
    if not role_spans:
        return found  # žiadny role keyword → žiadne mená

    for (rs, re_end) in role_spans:
        win_s = max(0, rs - 200)
        win_e = min(len(context), re_end + 200)
        window = context[win_s:win_e]
        for nm in _RAW_NAME_PAT.finditer(window):
            # Preskočiť match ktorý sa prekrýva so samotným role keyword spanom
            abs_nm_start = win_s + nm.start()
            abs_nm_end = win_s + nm.end()
            if abs_nm_start < re_end and abs_nm_end > rs:
                continue
            name = nm.group(1).strip()
            tokens = name.split()
            if len(tokens) < 2:
                continue
            # Blacklist porovnanie bez diakritiky (Nakupny == Nákupný)
            if any(_de_accent(t).lower() in _NOT_A_NAME_WORD_PLAIN for t in tokens):
                continue
            if name.lower() not in seen_lower:
                seen_lower.add(name.lower())
                found.append(name)

    return found


@app.post("/api/leads/raw-extract")
async def raw_extract(req: ScrapeRequest, user=Depends(verify_jwt)):
    """
    Vráti všetky nájdené kontakty (emaily, telefóny s 800-znakovým kontextom a kľúčovými slovami,
    IČO) bez AI tieringu. Určené pre manuálnu kontrolu.
    """
    base_url = req.url.strip()
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    base_url = base_url.rstrip("/")

    firma = _domain_of(base_url)

    scrape_out = await _scrape_all_pages(base_url)
    combined_text = scrape_out.get("text", "")
    jsonld_data = scrape_out.get("jsonld", {})

    # Normalizovaný text (newlines → medzery) pre hľadanie 400-znakového okna
    norm_text = combined_text.replace('\xa0', ' ')
    norm_text = re.sub(r'\n+', ' ', norm_text)
    norm_text = re.sub(r' {2,}', ' ', norm_text)

    candidates = extract_all_candidates(combined_text)

    # === EMAILY ===
    emails_out: List[str] = []
    seen_emails: set = set()
    if jsonld_data.get("email"):
        e = jsonld_data["email"].strip().lower()
        if e and e not in seen_emails:
            seen_emails.add(e)
            emails_out.append(jsonld_data["email"].strip())
    for entry in candidates["emails"]:
        key = entry["value"].lower()
        if key not in seen_emails:
            seen_emails.add(key)
            emails_out.append(entry["value"])

    # === TELEFÓNY — 800-znakový kontext + klucove_slova ===
    cisla_out: List[Dict[str, Any]] = []
    ico_out: Optional[str] = None
    seen_phones: set = set()

    # JSON-LD telefón (ak existuje) — nemá kontext v norm_text, daj generický
    if jsonld_data.get("phone"):
        p = jsonld_data["phone"].strip()
        norm_key = re.sub(r'\D', '', p)
        if norm_key and norm_key not in seen_phones:
            seen_phones.add(norm_key)
            cisla_out.append({
                "cislo": p,
                "kontext": "JSON-LD schema (homepage)",
                "klucove_slova": [],
            })

    for entry in candidates["phones"]:
        p = entry["value"]
        norm_key = re.sub(r'\D', '', p)
        if not norm_key:
            continue

        # Nájdi telefón v norm_text pre kontext
        idx = norm_text.find(p)
        if idx >= 0:
            ctx_600    = norm_text[max(0, idx - 600):idx + len(p) + 600].strip()
            ctx_2000   = norm_text[max(0, idx - 2000):idx + len(p) + 2000].strip()
            before_phone = norm_text[max(0, idx - 80):idx]
        else:
            # Fallback na ±150-znakový kontext z candidates
            fallback_ctx = entry.get("context", "").strip()
            ctx_600      = fallback_ctx
            ctx_2000     = fallback_ctx
            before_phone = fallback_ctx[:80]

        # IČO kontrola: len text PRED číslom (IČO/DIČ labely vždy predchádzajú číslu)
        if _is_ico_context(before_phone):
            if not ico_out and len(norm_key) >= 7:
                ico_out = p.strip()
            continue

        if norm_key not in seen_phones:
            seen_phones.add(norm_key)
            cisla_out.append({
                "cislo": p,
                "kontext": ctx_600,
                "klucove_slova": _extract_klucove_slova(ctx_2000),
            })

    # === POZNAMKA ===
    found_on: List[str] = []
    if combined_text:
        for path_hint in [
            "kontakt", "contact", "o-nas", "o-firme", "obchodne-podmienky",
            "obchodni-podminky", "gdpr", "ochrana-udajov", "impressum",
            "tym", "team", "vedenie",
        ]:
            if re.search(re.escape(path_hint), combined_text, re.IGNORECASE):
                found_on.append(f"/{path_hint}")
    poznamka = "Nájdené na: " + ", ".join(found_on) if found_on else "Podstránky neboli identifikované"

    return {
        "firma": firma,
        "emails": emails_out,
        "cisla": cisla_out,
        "ico": ico_out,
        "poznamka": poznamka,
    }