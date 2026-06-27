import sys, io
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

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
from fastapi.responses import JSONResponse, StreamingResponse
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
import urllib.parse
from urllib.parse import urlparse, urljoin, quote_plus
try:
    import whois as _whois_lib  # python-whois
except Exception:
    _whois_lib = None

import scoring
from registry_lookup import extract_ico_from_text, lookup_sk, lookup_cz, lookup_registry, orsr_search_by_name

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
    try:
        await init_db()
        await seed_orgs()
    except Exception as e:
        print(f"[WARN] DB init failed (non-fatal for scrape-only endpoints): {e}")

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
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
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
                await page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3}",
                    lambda r: r.abort()
                )
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
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
        except NotImplementedError:
            print(f"⚠️ Playwright NotImplementedError na Windows — skip pre {url}")
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
    # Produktové kódy s pomlčkami (037-001-6536, 047-927-682) — nie telefón
    if '-' in num and not num.lstrip().startswith(('+', '00')):
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
    # IČO má presne 8 číslic → nikdy nie je platné telefónne číslo
    if len(digits) == 8:
        return False
    # CZ holých 9 číslic, mobil začína 6/7, pevná 2-5; SK mobil bez 0 (9XX...)
    if len(digits) == 9 and digits[0] in '23456789':
        return True
    # 10-digit starting with '00': not a valid SK/CZ local number (no prefix 00X exists)
    if len(digits) == 10 and digits.startswith('00'):
        return False
    # Ostatné 10-13 ciferné čísla — zachytí medzinárodné formáty
    if 10 <= len(digits) <= 13:
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
_UPPER = "A-ZÁČĎÉĚÍĹĽŇÓÔŔŘŠŤÚŮÝŽ"
_LOWER = "a-záčďéěíľĺňóôŕřšťúůýž"
# Titul + 2-3 Capitalized slová oddelené iba medzerou/tabom (NIE newline – meno sa nezalamuje cez riadky)
_NAME_PATTERN = re.compile(
    rf'(?:Mgr\.|Ing\.|Bc\.|JUDr\.|MUDr\.|PhDr\.|prof\.|doc\.|MVDr\.|RNDr\.)?[ \t]*'
    rf'[{_UPPER}][{_LOWER}]{{2,}}[ \t]+[{_UPPER}][{_LOWER}]{{2,}}'
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
    # Pridané: UI elementy, anglické slová, navigácia zachytávaná IČO triggerom
    "Kontakty", "Obrázok", "Odoslať", "Zavrieť", "Outdoor", "Republic",
    "Dotaz", "Kontrolný", "Newsletter", "Prihlásiť", "Registrovať",
    "Specialist", "Manager", "Consultant", "Coordinator", "Analyst",
    # Slovakčina: zámenné/slovesné tvary nie sú mená
    "Som", "Vám", "Vás", "Sme", "Ste", "Môžem", "Môžete", "Budeme",
}

def _de_accent(s: str) -> str:
    """Odstráni diakritiku — 'Nákupný' → 'Nakupny'. Umožní porovnanie blacklistu
    aj s textom ktorý prišiel bez diakritiky (terminál, niektoré web-stránky)."""
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

# Pre-normalizovaný (bez diakritiky, lowercase) blacklist pre rýchle porovnanie.
_NOT_A_NAME_WORD_PLAIN: frozenset = frozenset(_de_accent(w).lower() for w in _NOT_A_NAME_WORD)

# ── OPRAVA 2: UI token blocklist ─────────────────────────────────────────────
# Slová ktoré sa NIKDY nevyskytujú v reálnych menách osôb.
_UI_BLOCKLIST: frozenset = frozenset(_de_accent(w).lower() for w in {
    # Navigácia a buttony
    "heslo", "nemôžete", "nastavení", "nastavenia", "souhlasím",
    "prispôsobiť", "povoliť", "pokračovať", "pokračovat",
    "prihlásiť", "prihlásit", "registrovať", "registrovat",
    "odmietnuť", "zavrieť", "odoslať", "uložiť", "uložit",
    "odoslat", "vyhľadávanie", "vyhledávání",
    # E-commerce
    "objednávky", "objedná", "objednavky", "košík", "kosik",
    "pokladňa", "pokladna", "reklamácie", "reklamacie",
    "showroom", "realizácie", "katalógy", "katalogy",
    "veľkoobchod", "velkoobchod", "vypredaj", "výpredaj",
    # Social / UI
    "facebook", "google", "instagram", "pinterest", "youtube",
    "twitter", "linkedin", "whatsapp",
    "prev", "next", "menu", "footer", "header", "sidebar",
    "error", "ľutujeme", "loading", "spinner",
    # Marketing
    "novinky", "akcie", "akcia", "blog", "kariéra", "kariera",
    "recenzie", "newsletter", "subscribe",
    # Tracking / Analytics (Google Tag Manager false positives)
    "gtm", "analytics", "datalayer", "tracking",
    # VOP právnické pojmy — nikdy nie sú mená osôb
    "kupujúci", "kupující", "predávajúci", "prodávající",
    "spotrebiteľ", "spotřebitel", "objednávateľ", "objednatel",
    "podnikateľ", "podnikatel", "dodávateľ", "dodavatel",
    "prevádzkovateľ", "provozovatel", "zhotoviteľ", "zhotovitel",
    "obchodník", "obchodnik", "právnická", "fyzická",
    "zmluvná", "smluvní", "strana", "subjekt",
})

# ── OPRAVA 3: Mesto / adresa blocklist ───────────────────────────────────────
_CITY_BLOCKLIST: frozenset = frozenset(_de_accent(c).lower() for c in {
    # SK mestá (top 30)
    "bratislava", "košice", "prešov", "žilina", "banská bystrica",
    "nitra", "trnava", "trenčín", "martin", "poprad", "piešťany",
    "zvolen", "považská bystrica", "prievidza", "topoľčany",
    "lučenec", "komárno", "levice", "michalovce", "humenné",
    "bardejov", "ružomberok", "čadca", "galanta", "dunajská streda",
    "stará turá", "nové zámky", "dolný kubín", "liptovský mikuláš",
    "spišská nová ves",
    # CZ mestá (top 15)
    "praha", "brno", "ostrava", "plzeň", "olomouc", "liberec",
    "české budějovice", "hradec králové", "pardubice", "zlín",
    "jihlava", "blansko", "karlovy vary", "opava", "frýdek místek",
    # Mestské časti / vidiek — false positives z kontaktu
    "nové mesto", "staré mesto", "ružinov", "petržalka", "rača",
    "devínska nová ves", "karlova ves", "dúbravka", "lamač",
    "liptovská porúbka", "liptovskej porúbky", "čeľadice",
    "moravská ostrava",
    # Adresné frázy a štáty
    "dolné rudiny", "ratnovce", "slavičín",
    "czech republic", "slovenská republika", "slovensko", "česko",
})

# ── OPRAVA 4: Produktový token blocklist ─────────────────────────────────────
_PRODUCT_TOKENS: frozenset = frozenset({
    "collagen", "serum", "cream", "vitamin", "gel", "mask",
    "skin", "hair", "oil", "lotion", "spray", "shampoo",
    "conditioner", "moisturizer", "cleanser", "toner",
    "liftactiv", "retinol", "hyaluron", "peptide", "niacinamide",
    "keratin", "biotin", "wrapping", "peel",
    # Kancelárske/papierové produkty — false positives v officeland-like e-shopoch
    "fotopapier", "format", "produkt", "tovar", "material", "materiál",
    "papier", "cartridge", "kancelaria", "kancelársky", "kancelářský",
    # Produktové brandy z e-shopov
    "jollein", "cottelli", "satisfyer", "dillio", "fleshlight",
})

# ── Delivery / logistics companies — NIKDY nie sú konatelia ──────────────────
_DELIVERY_BLOCKLIST: frozenset = frozenset(_de_accent(w).lower() for w in {
    "packeta", "packeta slovakia", "zásielkovňa", "zasielkovna",
    "geis", "geis parcel", "geis sk", "geis cz",
    "dpd", "gls", "gls slovakia", "gls czech",
    "slovenská pošta", "slovenska posta", "česká pošta", "ceska posta",
    "ppl", "toptrans", "fofr", "spring courier",
    "shipmonk", "balíkovo", "balikovo", "depo", "expres kurier",
})

# ── Slovenské a české krstné mená — na validáciu kandidátov ──────────────────
_SK_FIRST_NAMES: frozenset = frozenset({
    # SK mužské
    "adam", "adrián", "alexander", "andrej", "anton", "branislav", "boris",
    "dalibor", "daniel", "dávid", "dušan", "erik", "filip", "františek",
    "gabriel", "igor", "ivan", "ján", "jakub", "jaroslav", "jozef", "juraj",
    "karol", "ladislav", "libor", "lukáš", "ľubomír", "ľuboš", "marek",
    "marián", "martin", "matej", "matúš", "michal", "milan", "miroslav",
    "ondrej", "patrik", "pavol", "peter", "radoslav", "rastislav", "richard",
    "robert", "roman", "samuel", "stanislav", "šimon", "štefan", "tibor",
    "tomáš", "vladimír", "vladislav", "vlastimil", "zdenko", "milan", "róbert",
    "ľuboslav", "rudolf", "rastko", "marko", "viktor", "boris", "dominik",
    "oto", "róbert", "ernest", "imrich", "norbert", "dezider", "eugen",
    # SK ženské
    "adriana", "alena", "alexandra", "alžbeta", "andrea", "anna", "barbora",
    "beata", "dagmar", "dana", "daniela", "denisa", "diana", "dominika",
    "elena", "erika", "eva", "gabriela", "hana", "helena", "ivana", "iveta",
    "jana", "janka", "jaroslava", "katarína", "klára", "kristína", "lenka",
    "lucia", "ľudmila", "magdaléna", "marcela", "margita", "mária", "marianna",
    "marina", "martina", "michaela", "miroslava", "monika", "natália", "nina",
    "oľga", "patrícia", "paulína", "petra", "radka", "renáta", "simona",
    "soňa", "stanislava", "sylvia", "tatiana", "tereza", "tímea", "veronika",
    "viktória", "zuzana", "žaneta", "zdenka", "silvia", "emília", "marta",
    "dagmar", "ružena", "viera", "ľubica", "blanka", "darina", "ingrid",
    # CZ mená
    "jiří", "jan", "josef", "karel", "václav", "petr", "pavel", "martin",
    "zdeněk", "miloslav", "jaroslav", "milan", "tomáš", "ondřej", "lukáš",
    "marie", "lucie", "kateřina", "věra", "ludmila", "jana", "eva", "hana",
    "petra", "lenka", "markéta", "monika", "simona", "tereza", "barbora",
    # Medzinárodné / anglické
    "carolina", "fatima", "nikola", "nikoleta", "kristian", "christian",
    "michael", "david", "thomas", "stefan", "peter", "mario", "marco",
})

def _first_name_known(meno: str) -> bool:
    """True ak prvé slovo mena je v _SK_FIRST_NAMES (bez diakritiky)."""
    if not meno:
        return False
    first = _de_accent(meno.split()[0]).lower()
    return first in _SK_FIRST_NAMES

# ── Ingredients / random nonsense / accidental matches ────────────────────────
_INGREDIENT_BLOCKLIST: frozenset = frozenset(_de_accent(w).lower() for w in {
    "panax ginseng", "ginkgo biloba", "služba účel", "sluzba ucel",
    "knieradl táta", "knieradl tata",
    "aloe vera", "tea tree", "shea butter",
    "perfect fit", "little dutch", "happy horse",
})

# ===== SCORING ENGINE =====

SCORE_CONFIG = {
    "registry_konatel": 30,
    "personal_phone": 20,
    "info_phone": 10,
    "delivery_phone": 0,
    "personal_email": 15,
    "generic_email": 5,
    "role_decision_maker": 20,
    "name_match_registry": 10,
    "fallback_high_confidence": 10,
    "fallback_low_confidence": 0,
    "no_personal_phone_penalty": -30,
}

TIER_RANGES = {
    "HOT": (80, 100),
    "WARM": (60, 79),
    "COOL": (40, 59),
    "DEAD": (0, 39),
}

TIER_COLORS = {
    "HOT": "\U0001f525",
    "WARM": "\U0001f7e0",
    "COOL": "\U0001f535",
    "DEAD": "⚫",
}

TIER_ACTIONS = {
    "HOT": "Volaj DNES — konateľ + personal kontakt",
    "WARM": "Volaj denne — konateľ ale bez personal telefónu",
    "COOL": "Volaj v tomto týždni — fallback osoba alebo info tel",
    "DEAD": "Skip alebo fallback — slabý match",
}

# Regex pre strippovanie titulov pri blocklist kontrole (bez diakritiky-safe)
_TITLE_STRIP_RE = re.compile(
    r'\b(Mgr|Ing|Bc|JUDr|MUDr|PhDr|prof|doc|MVDr|RNDr)\.?\s*',
    re.IGNORECASE,
)

def _is_blocked_name(raw: str) -> bool:
    """Vráti True ak raw string vyzerá ako UI token, mesto alebo produkt — nie reálna osoba.
    Aplikuje sa PRED confidence scoringom na všetky name kandidáty.
    """
    no_title = _TITLE_STRIP_RE.sub('', raw).strip()
    plain = _de_accent(no_title).lower()
    words = plain.split()
    if not words:
        return False
    # Combo: "tag" + "manager" → Google Tag Manager false positive
    if 'tag' in words and 'manager' in words:
        return True
    # OPRAVA 2: UI token — stačí jedno slovo z mena
    if any(w in _UI_BLOCKLIST for w in words):
        return True
    # OPRAVA 4: Produktový token — stačí jedno slovo z mena
    if any(w in _PRODUCT_TOKENS for w in words):
        return True
    # Delivery / logistics — celé meno alebo 2-slovné kombo
    if plain in _DELIVERY_BLOCKLIST:
        return True
    for i in range(len(words) - 1):
        if words[i] + ' ' + words[i + 1] in _DELIVERY_BLOCKLIST:
            return True
    # Ingredient / nonsense — celé meno alebo 2-slovné kombo
    if plain in _INGREDIENT_BLOCKLIST:
        return True
    for i in range(len(words) - 1):
        if words[i] + ' ' + words[i + 1] in _INGREDIENT_BLOCKLIST:
            return True
    # OPRAVA 3: Mesto — POZOR: "Martin" je aj meno aj mesto, preto
    # kontrolujeme len celé meno a 2-slovné kombá, NIE jednotlivé slová.
    if plain in _CITY_BLOCKLIST:
        return True
    for i in range(len(words) - 1):
        if words[i] + ' ' + words[i + 1] in _CITY_BLOCKLIST:
            return True
    return False

# ─── Person↔Role association ──────────────────────────────────────────────────

# Trigger frázy pre detekciu živnostníka (= fyzická osoba ako prevádzkovateľ).
# Dve skupiny:
#   _ZIVNOSTNIK_ACTION_RE  — meno býva ZA triggerom  (hľadáme ±80 okolo)
#   _ICO_POSITIONAL_RE     — meno bezprostredne (max 10 znakov) PRED "IČO: číslo"
_ZIVNOSTNIK_ACTION_RE = re.compile(
    r'prevádzkovateľom\s+je|prevadzkovatelom\s+je'       # "prevádzkovateľom je [meno]"
    r'|predávajúcim\s+je|predavajucim\s+je'              # "Predávajúcim je [meno]" — VOP deklarácia
    r'|pod\s+obchodn[yý]m\s+menom|pod\s+obchodn[íi]m\s+jménem'
    r'|obchodn[eé]\s+meno\s+je|obchodn[íi]\s+jméno\s+je'
    r'|zapísan[yý]\s+v\s+živnostenskom|zapsán\s+v\s+živnostenském'
    r'|\bživnostník\b|\bpodnikateľ\b|\bpodnikatel\b'
    r'|stoj[íi]\s+za\s+tý?mto|riadim\s+\w{1,6}\s*[-–]',
    re.IGNORECASE,
)
# Pozičný vzor — dve vetvy, meno capture bez globálneho IGNORECASE:
#
#  Vetva 1 (groups 1,2): strict gap — meno + max čiarka/10 znakov medzery + IČO
#    napr. "Ladislav Ferenci, IČO: 12345678"
#
#  Vetva 2 (groups 3,4): živnostenský formát — meno + OBCHODNÉ_MENO (ASCII uppercase)
#    + ulica číslo + PSČ/mesto (lazy ≤40 ch) + IČO, celý gap ≤80 ch
#    napr. "Mgr. Ladislav Ferenci FGYM.SK Ratnovce 128 922 31 Ratnovce IČO: 46 41 27 27"
#
# IČO/IČ case-insensitive cez inline (?i:...) — meno capture ostáva case-sensitive.
_ICO_POSITIONAL_RE = re.compile(
    # Vetva 1
    rf'([{_UPPER}][{_LOWER}]{{2,}}(?:\s+[{_UPPER}][{_LOWER}]{{2,}}){{1,3}})'
    r'(\s*,?\s{0,10})'
    r'(?i:IČO?\s*:?\s*\d(?:\s?\d){5,9})'
    r'|'
    # Vetva 2 — voliteľný titul pred menom (nekaptúrovaný)
    r'(?:(?:Mgr|Ing|Bc|JUDr|MUDr|PhDr|RNDr|MVDr|PaedDr|Dr|prof|doc)\.\s*)?'
    + rf'([{_UPPER}][{_LOWER}]{{2,}}\s+[{_UPPER}][{_LOWER}]{{2,}})'
    + r'(\s+[A-Z][A-Z0-9.\-_]{2,}\s+\w+\s+\d+.{0,40}?)'
    + r'(?i:IČO?\s*:?\s*\d(?:\s?\d){5,9})',
)


# Indikátory právnickej osoby — ak sa nachádzajú do 30 znakov ZA menom,
# nie je to živnostník → nepovyšuj na majiteľa
_LEGAL_ENTITY_RE = re.compile(
    r'\bs\.?\s*r\.?\s*o\.?\b|\ba\.?\s*s\.?\b|\bspol\.\s*s\s*r\.?\s*o\b'
    r'|\bakcio(?:vá|va)\s+spoloč|\bs\.p\.\b|\bgmbh\b|\bllc\b',
    re.IGNORECASE,
)

# ── Wector fix: štatutár bezprostredne ZA názvom s.r.o./a.s. ──────────────────
# SK pattern "<Obchodné meno> s.r.o. <Meno Priezvisko>" — meno hneď za právnickou
# osobou (do ~12 znakov) = konateľ. Opačný prípad k _LEGAL_ENTITY_RE (ten blokuje
# s.r.o. ZA menom → živnostník). Anchor na KONIEC "before" okna ($).
_STATUTAR_SRO_RE = re.compile(
    r'(?:\bs\.?\s*r\.?\s*o|\ba\.?\s*s|\bspol\.\s*s\s*r\.?\s*o)\.?[\s,]*$',
    re.IGNORECASE,
)

# Owner self-intro: "volám sa Erika", "ja som Erika", "moje meno je Erika".
# Trigger case-insensitive (inline (?i:...)), krstné meno capture case-sensitive
# (musí začínať veľkým písmenom — inak by IGNORECASE chytalo aj slovesá ako "som").
_SELF_INTRO_RE = re.compile(
    rf'(?i:vol[áa]m\s+sa|ja\s+som|moje\s+meno\s+je|\bsom)\s+'
    rf'([{_UPPER}][{_LOWER}]{{2,}})'
)

# Owner-intent korroborácia v okolí self-intro — bráni promócii náhodného
# "som Peter" na majiteľa. Vyžaduje sa do ±250 znakov od self-intro matchu.
_OWNER_INTENT_RE = re.compile(
    r'm[áa]m\s+na\s+staros|chod\s+\w*\s*eshop|ved(?:iem|enie)\s+\w*eshop'
    r'|majiteľ|majitel|zakladateľ|zakladatel|vlastn[íi]m|riadim'
    r'|stoj[íi]m\s+za|tá\s+ktorá|ten\s+ktorý',
    re.IGNORECASE,
)

_PERSON_ROLE_LEVELS: List[tuple] = [
    # Sub-úrovne v rámci LVL3 (float) — štatutári a vlastníci majú vyššiu prioritu ako ředitelia.
    # Sort kľúč: -rola_level_sort DESC → 3.3 pred 3.2 pred 3.1.
    # V output JSON sa rola_level konvertuje späť na int(3) pre backward compat.
    (3.3, re.compile(
        r'konateľ(?:ka)?|konatel(?:ka)?'
        r'|jednateľ(?:ka)?|jednatel(?:ka)?'
        r'|majiteľ(?:ka)?|majitel(?:ka)?|vlastník(?:čka)?'
        r'|zakladateľ\w*|zakladatel\w*'
        r'|\bCEO\b|\bCTO\b|\bCFO\b|\bowner\b|\bfounder\b|co-founder|prokurista',
        re.IGNORECASE,
    )),
    (3.2, re.compile(
        r'generálny\s+riaditeľ|generalny\s+riaditel'
        r'|generální\s+ředitel|generalny\s+reditel'
        r'|managing\s+director',
        re.IGNORECASE,
    )),
    (3.1, re.compile(
        r'riaditeľ(?:ka)?|riaditel(?:ka)?|ředitel(?:ka)?|reditel(?:ka)?'
        r'|\bdirector\b|\bpresident\b',
        re.IGNORECASE,
    )),
    (2, re.compile(
        r'zodpovedn[yý]\s+vedúci|zodpovedn[yý]\s+veduci'
        r'|odpovědn[yý]\s+vedouc[íi]|odpovedny\s+vedouci'
        r'|odpovědn[aá]\s+osoba|odpovedna\s+osoba'
        r'|zodpovedn[aá]\s+osoba|zodpovedna\s+osoba'
        r'|prevádzkar|prevadzkar|provozn[íi]'
        r'|vedúci\s+prevádzky|veduci\s+prevadzky'
        r'|obchodný\s+riaditeľ|obchodny\s+riaditel'
        r'|obchodný\s+manažér|obchodny\s+manazer'
        r'|\bsales\b'
        r'|kontaktná\s+osoba|kontaktna\s+osoba|kontaktní\s+osoba|kontaktni\s+osoba',
        re.IGNORECASE,
    )),
    (1, re.compile(
        r'manažér|manazer|manažer|\bmanager\b'
        r'|vedúci|veduci|vedoucí|vedouci'
        r'|koordinátor|koordinator|\bspecialist\b',
        re.IGNORECASE,
    )),
]

_ASSOC_TITLE_RE = re.compile(
    r'\b(?:Bc|Ing|Mgr|JUDr|PhDr|RNDr|MUDr|MVDr|PaedDr|Dr|prof|doc)\.',
    re.IGNORECASE,
)

_EMAIL_POS_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

_GENERIC_EMAIL_PREFIXES_SET = frozenset({
    "info", "podpora", "support", "office", "kontakt", "contact",
    "sales", "obchod", "objednavky", "objednávky", "eshop", "shop",
    "noreply", "no-reply", "marketing", "reklama", "helpdesk",
    "hello", "ahoj", "admin", "mail", "post",
})


def _find_email_near_name(text: str, name: str, window: int = 500) -> Optional[str]:
    """Find the best email within `window` chars of `name` in text.
    Prefers personal emails (containing first/last name) over generic (info@, etc.)."""
    if not text or not name:
        return None
    norm = text.replace('\xa0', ' ')
    name_lower = name.lower()
    name_parts = [p.lower() for p in name.split() if len(p) >= 3]

    best_email = None
    best_score = -999

    # Find all positions of the name
    search_name = name_lower
    norm_lower = norm.lower()
    pos = 0
    name_positions = []
    while True:
        idx = norm_lower.find(search_name, pos)
        if idx < 0:
            break
        name_positions.append(idx)
        pos = idx + 1

    if not name_positions:
        return None

    for npos in name_positions:
        start = max(0, npos - window)
        end = min(len(norm), npos + len(name) + window)
        chunk = norm[start:end]

        for em in _EMAIL_POS_RE.finditer(chunk):
            email = em.group(0)
            if _email_is_ignored(email, ""):
                continue

            score = 0
            local = email.split("@")[0].lower()

            # Personal email bonus: local part contains first or last name
            if any(part in local for part in name_parts):
                score += 5

            # Generic email penalty
            if any(local == g or local.startswith(g + ".") or local.startswith(g + "@")
                   for g in _GENERIC_EMAIL_PREFIXES_SET):
                score -= 3

            # Same line/paragraph bonus
            email_abs_pos = start + em.start()
            if abs(email_abs_pos - npos) < 100:
                score += 2

            if score > best_score:
                best_score = score
                best_email = email

    return best_email


def associate_persons_with_roles(text: str) -> List[Dict[str, Any]]:
    """
    Nájde mená osôb a priradí im roly podľa okolitého textu.

    Smer asociácie určuje oddeľovač:
      ':' za rolou    → meno hľadáme ZA rolou
      '–/-/,' pred rolou → meno hľadáme PRED rolou
      inak            → najbližšie meno v celom okne ±80

    Confidence: +3 adjacent role, +2 titul (Bc./Ing./…), +2 blízko emailu.
    Mená s confidence 0 sa zahadzujú.
    Vracia zoznam zoradený (rola_level DESC, confidence DESC).
    """
    if not text:
        return []

    norm = text.replace('\xa0', ' ')
    # OPRAVA 2: collapse všetkých whitespace (newlines + viacnásobné medzery) do jednej medzery.
    # Opravuje weby kde medzi rolou a menom je 40+ medzier/newlines (napr. ruzovakozmetika.sk).
    norm = re.sub(r'\s+', ' ', norm)

    email_pos: List[int] = [m.start() for m in _EMAIL_POS_RE.finditer(norm)]

    all_role_spans: List[tuple] = []  # (start, end, level, matched_text)
    for level, pat in _PERSON_ROLE_LEVELS:
        for m in pat.finditer(norm):
            all_role_spans.append((m.start(), m.end(), level, m.group(0)))
    all_role_spans.sort(key=lambda x: x[0])

    WINDOW = 80
    persons: Dict[str, Dict] = {}

    def _strip_title(raw: str) -> str:
        no_title = _ASSOC_TITLE_RE.sub('', raw).strip()
        tokens = [t for t in no_title.split() if t and not t.endswith('.') and len(t) > 1]
        return ' '.join(tokens) if len(tokens) >= 2 else raw.strip()

    def _calc_conf(name_pos: int, has_title: bool, has_role: bool) -> int:
        conf = 3 if has_role else 0
        if has_title:
            conf += 2
        for ep in email_pos:
            if abs(ep - name_pos) <= 100:
                conf += 2
                break
        return conf

    _phone_near_re = re.compile(
        r'(?<!\d)(\+?(?:421|420)?[\s\-/]?(?:\d[\s\-/]?){9,12})(?!\d)'
    )

    def _find_phone_near_name(name_pos: int, window: int = 500) -> Optional[str]:
        start = max(0, name_pos - window)
        ctx = norm[start: name_pos + window]
        best_ph, best_dist = None, window + 1
        for m in _phone_near_re.finditer(ctx):
            ph = m.group(1).strip()
            digits = re.sub(r'\D', '', ph)
            # Must be a valid SK/CZ phone structure
            valid = (
                (len(digits) == 12 and digits[:3] in ('421', '420')) or
                (len(digits) == 10 and digits[0] == '0') or
                (len(digits) == 9 and digits[0] in '56789')
            )
            if not valid:
                continue
            # Skip fax numbers — check 40 chars before the phone in full norm text
            abs_ph_pos = start + m.start()
            pre_ctx = norm[max(0, abs_ph_pos - 40): abs_ph_pos]
            if re.search(r'\bfax\b', pre_ctx, re.IGNORECASE):
                continue
            dist = abs(abs_ph_pos - name_pos)
            if dist < best_dist:
                best_dist = dist
                best_ph = ph
        return best_ph

    def _upsert(clean_name: str, rola: Optional[str], level: int,
                conf: int, name_pos: int) -> None:
        if not scoring.is_person_name(clean_name):
            return
        key = clean_name.lower()
        if key in persons:
            ex = persons[key]
            if level > ex['rola_level']:
                ex['rola'] = rola
                ex['rola_level'] = level
                # Update phone too — new role position may be closer to the right phone
                new_tel = _find_phone_near_name(name_pos)
                if new_tel:
                    ex['telefon_osoby'] = new_tel
            ex['confidence'] = max(ex['confidence'], conf)
        else:
            ctx_s = max(0, name_pos - 150)
            ctx_e = min(len(norm), name_pos + len(clean_name) + 150)
            persons[key] = {
                'meno': clean_name,
                'rola': rola,
                'rola_level': level,
                'confidence': conf,
                'kontext': norm[ctx_s:ctx_e].strip(),
                'telefon_osoby': _find_phone_near_name(name_pos),
            }

    def _best_name_in(seg: str, seg_offset: int, direction: str,
                      role_rs: int, role_re: int) -> Optional[tuple]:
        best = None
        best_dist = float('inf')
        for nm in _NAME_PATTERN.finditer(seg):
            raw = nm.group(0).strip()
            tokens = [t for t in raw.split() if not t.endswith('.')]
            if len(tokens) < 2:
                continue
            if any(t in _NOT_A_NAME_WORD for t in tokens):
                continue
            if any(_de_accent(t).lower() in _NOT_A_NAME_WORD_PLAIN for t in tokens):
                continue
            if _is_blocked_name(raw):  # OPRAVA 2+3+4: UI/mesto/produkt filter
                continue
            abs_s = seg_offset + nm.start()
            abs_e = seg_offset + nm.end()
            has_title = bool(_ASSOC_TITLE_RE.search(raw))
            if direction == 'after':
                dist = abs_s - role_re
            elif direction == 'before':
                dist = role_rs - abs_e
            else:
                dist = min(abs(abs_s - role_rs), abs(abs_e - role_re))
            if 0 <= dist < best_dist:
                best_dist = dist
                best = (_strip_title(raw), abs_s, has_title)
        return best

    for (rs, re_end, level, role_text) in all_role_spans:
        # Separator → direction
        after_chars = norm[re_end:re_end + 4]
        before_chars = norm[max(0, rs - 4):rs].rstrip()
        if ':' in after_chars:
            direction = 'after'
        elif before_chars and before_chars[-1] in '–-,':
            direction = 'before'
        else:
            direction = 'any'

        # Window trimmed by neighbouring role spans
        win_left = max(0, rs - WINDOW)
        for (ors, ore, _, _) in all_role_spans:
            if ore <= rs and ore > win_left:
                win_left = ore
        win_right = min(len(norm), re_end + WINDOW)
        for (ors, ore, _, _) in all_role_spans:
            if ors >= re_end and ors < win_right:
                win_right = ors

        if direction == 'after':
            seg, off = norm[re_end:win_right], re_end
        elif direction == 'before':
            seg, off = norm[win_left:rs], win_left
        else:
            seg, off = norm[win_left:win_right], win_left

        found = _best_name_in(seg, off, direction, rs, re_end)
        if not found:
            continue
        clean_nm, name_pos, has_title = found
        conf = _calc_conf(name_pos, has_title, has_role=True)
        _upsert(clean_nm, role_text, level, conf, name_pos)

    # === Živnostník detekcia: meno pri trigger fráze → majiteľ LVL3 ===
    # Ak meno nemá rolu alebo má nižší level, povyšujeme na LVL3.
    # Ak meno MÁ rolu rovnakej alebo vyššej úrovne, _upsert ju neprepisuje.

    def _zivnostnik_upsert_from_seg(seg: str, seg_offset: int) -> None:
        """Pokús sa nájsť živnostníka v segmente textu a upsertnúť ho ako majiteľa."""
        for nm in _NAME_PATTERN.finditer(seg):
            raw = nm.group(0).strip()
            has_title = bool(_ASSOC_TITLE_RE.search(raw))
            tokens = [t for t in raw.split() if not t.endswith('.')]
            if len(tokens) < 2:
                continue
            if any(t in _NOT_A_NAME_WORD for t in tokens):
                continue
            if any(_de_accent(t).lower() in _NOT_A_NAME_WORD_PLAIN for t in tokens):
                continue
            if _is_blocked_name(raw):  # OPRAVA 2+3+4: UI/mesto/produkt filter
                continue
            abs_nm_start = seg_offset + nm.start()
            abs_nm_end   = seg_offset + nm.end()
            # Ochrana: s.r.o./a.s. do 30 znakov ZA menom → právnická osoba
            after_name = norm[abs_nm_end:min(len(norm), abs_nm_end + 30)]
            if _LEGAL_ENTITY_RE.search(after_name):
                continue
            clean_nm = _strip_title(raw)
            conf = _calc_conf(abs_nm_start, has_title, has_role=True)
            _upsert(clean_nm, 'majiteľ', 3, conf, abs_nm_start)

    # Typ 1: "prevádzkovateľom je", "pod obchodným menom" atď. — meno ±80 okolo
    ZW = 80
    for zm in _ZIVNOSTNIK_ACTION_RE.finditer(norm):
        zs, ze = zm.start(), zm.end()
        win_s = max(0, zs - ZW)
        win_e = min(len(norm), ze + ZW)
        _zivnostnik_upsert_from_seg(norm[win_s:win_e], win_s)

    # Typ 2: pozičný vzor — vetva 1 (strict gap) alebo vetva 2 (živnostenský formát)
    for im in _ICO_POSITIONAL_RE.finditer(norm):
        # Vetva 1: groups (1,2), Vetva 2: groups (3,4)
        if im.group(1) is not None:
            raw      = im.group(1).strip()
            gap      = im.group(2)
            nm_grp   = 1
        else:
            raw      = im.group(3).strip()
            gap      = im.group(4)
            nm_grp   = 3
        # Gap nesmie obsahovať právnickú osobu (s.r.o., a.s., spol.)
        if _LEGAL_ENTITY_RE.search(gap):
            continue
        abs_nm_start = im.start(nm_grp)
        abs_nm_end   = im.end(nm_grp)
        # Extra ochrana: právnická osoba do 30 znakov priamo za menom
        after_name = norm[abs_nm_end:min(len(norm), abs_nm_end + 30)]
        if _LEGAL_ENTITY_RE.search(after_name):
            continue
        tokens = [t for t in raw.split() if not t.endswith('.')]
        if len(tokens) < 2:
            continue
        if any(t in _NOT_A_NAME_WORD for t in tokens):
            continue
        if any(_de_accent(t).lower() in _NOT_A_NAME_WORD_PLAIN for t in tokens):
            continue
        if _is_blocked_name(raw):  # OPRAVA 2+3+4: UI/mesto/produkt filter
            continue
        clean_nm = _strip_title(raw)
        has_title = bool(_ASSOC_TITLE_RE.search(raw))
        conf = _calc_conf(abs_nm_start, has_title, has_role=True)
        _upsert(clean_nm, 'majiteľ', 3, conf, abs_nm_start)

    # === Wector Typ 3: štatutár bezprostredne ZA "s.r.o."/"a.s." ===
    # "MAXVOLT s.r.o. Erika Blíziková" → Erika = konateľ(ka). _STATUTAR_SRO_RE
    # matchuje právnickú osobu na KONCI okna 12 znakov PRED menom.
    for nm in _NAME_PATTERN.finditer(norm):
        raw = nm.group(0).strip()
        tokens = [t for t in raw.split() if not t.endswith('.')]
        if len(tokens) < 2:
            continue
        if any(t in _NOT_A_NAME_WORD for t in tokens):
            continue
        if any(_de_accent(t).lower() in _NOT_A_NAME_WORD_PLAIN for t in tokens):
            continue
        if _is_blocked_name(raw):
            continue
        abs_s = nm.start()
        before = norm[max(0, abs_s - 12):abs_s]
        if not _STATUTAR_SRO_RE.search(before):
            continue
        # Address guard: meno priamo nasledované číslom = "Mesto 428" adresa, nie osoba
        if re.match(r'\s*\d', norm[nm.end():nm.end() + 3]):
            continue
        clean_nm = _strip_title(raw)
        has_title = bool(_ASSOC_TITLE_RE.search(raw))
        rola = 'konateľka' if clean_nm.split()[-1].endswith('á') else 'konateľ'
        conf = _calc_conf(abs_s, has_title, has_role=True) + 2
        _upsert(clean_nm, rola, 3.3, conf, abs_s)

    # === Wector Typ 4: owner self-intro cross-reference ===
    # "Ahojte, volám sa Erika. Mám na starosť ... chod celého eshopu" (homepage)
    # krížom s plným menom "Erika Blíziková" pri kontaktných údajoch → majiteľ(ka).
    self_intro_first: set = set()
    for m in _SELF_INTRO_RE.finditer(norm):
        fn = m.group(1)
        if not fn:
            continue
        # Owner-intent musí byť v okolí — inak je to len bežné "som Peter".
        if not _OWNER_INTENT_RE.search(norm[max(0, m.start() - 50): m.end() + 250]):
            continue
        fnl = _de_accent(fn).lower()
        if fnl in _NOT_A_NAME_WORD_PLAIN or fnl in _UI_BLOCKLIST:
            continue
        self_intro_first.add(fnl)
    if self_intro_first:
        # Kontaktné kotvy = pozície emailov + validných telefónov
        contact_pos = list(email_pos)
        for pm in _phone_near_re.finditer(norm):
            d = re.sub(r'\D', '', pm.group(1))
            if (len(d) == 12 and d[:3] in ('421', '420')) or \
               (len(d) == 10 and d[0] == '0') or \
               (len(d) == 9 and d[0] in '56789'):
                contact_pos.append(pm.start())
        for nm in _NAME_PATTERN.finditer(norm):
            raw = nm.group(0).strip()
            tokens = [t for t in raw.split() if not t.endswith('.')]
            if len(tokens) < 2:
                continue
            if any(t in _NOT_A_NAME_WORD for t in tokens):
                continue
            if any(_de_accent(t).lower() in _NOT_A_NAME_WORD_PLAIN for t in tokens):
                continue
            if _is_blocked_name(raw):
                continue
            clean_nm = _strip_title(raw)
            first_tok = _de_accent(clean_nm.split()[0]).lower()
            if first_tok not in self_intro_first:
                continue
            abs_s = nm.start()
            # Plné meno musí byť pri kontaktných údajoch (email/telefón do 150 zn.)
            if not any(abs(cp - abs_s) <= 150 for cp in contact_pos):
                continue
            has_title = bool(_ASSOC_TITLE_RE.search(raw))
            rola = 'majiteľka' if clean_nm.split()[-1].endswith('á') else 'majiteľ'
            conf = max(_calc_conf(abs_s, has_title, has_role=True) + 2, 5)
            _upsert(clean_nm, rola, 3.3, conf, abs_s)

    # Mená blízko emailov (bez roly) — zachováme ak confidence ≥ 2
    for ep in email_pos:
        win_s = max(0, ep - 150)
        win_e = min(len(norm), ep + 150)
        for nm in _NAME_PATTERN.finditer(norm[win_s:win_e]):
            raw = nm.group(0).strip()
            tokens = [t for t in raw.split() if not t.endswith('.')]
            if len(tokens) < 2:
                continue
            if any(t in _NOT_A_NAME_WORD for t in tokens):
                continue
            if any(_de_accent(t).lower() in _NOT_A_NAME_WORD_PLAIN for t in tokens):
                continue
            if _is_blocked_name(raw):  # OPRAVA 2+3+4: UI/mesto/produkt filter
                continue
            clean_nm = _strip_title(raw)
            has_title = bool(_ASSOC_TITLE_RE.search(raw))
            conf = 2 + (2 if has_title else 0)
            _upsert(clean_nm, None, 0, conf, win_s + nm.start())

    # OPRAVA 1: conf<=2 bez roly = UI šum → zahodíme.
    # Ponecháme: conf>=3 (má titul/rolu/email kontext) ALEBO rola!=None (akýkoľvek conf).
    # OPRAVA 1c: jednoslovné meno (žiadna medzera) s conf < 5 → šum → zahodíme.
    # BUG 6: ak prvé slovo nie je v _SK_FIRST_NAMES a confidence < 5 → REJECT (false positives ako "Fotopapier Formát")
    out = [p for p in persons.values()
           if (p['confidence'] >= 3 or p['rola'] is not None)
           and not (' ' not in p['meno'] and p['confidence'] < 5)
           and (_first_name_known(p['meno']) or p['confidence'] >= 5)]
    # Zoradenie: sub-priorita LVL3 — 3.3 (jednatel) pred 3.1 (ředitel), potom confidence
    out.sort(key=lambda x: (-x['rola_level'], -x['confidence']))
    # Backward compat: konvertuj float sub-úrovne späť na int pre výstup JSON
    for p in out:
        p['rola_level'] = int(p['rola_level'])
    return out


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

    # BUG 1: Extrahuj IČO čísla z textu — tieto 8-ciferné čísla nikdy nie sú telefóny
    ico_digits_set: set = set()
    for _m in re.finditer(r'\bIČ[OQ]?\s*:?\s*(\d[\s\d]{5,8})', normalized, re.IGNORECASE):
        _d = re.sub(r'\D', '', _m.group(1))
        if len(_d) == 8:
            ico_digits_set.add(_d)

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
        # preskočiť čísla ktoré sú IČO (aj s leading zeros: 0002605074 → 02605074)
        if norm in ico_digits_set or norm.lstrip('0').zfill(8) in ico_digits_set:
            print(f"⚠️ Preskakujem IČO ako telefón: {raw}")
            continue
        seen_phones.add(norm)
        # Kontext ber z pôvodného norm_text (pred odstránením tel: prefixov)
        orig_idx = normalized.find(raw)
        if orig_idx >= 0:
            ctx_start, ctx_end = orig_idx, orig_idx + len(raw)
        else:
            ctx_start, ctx_end = m.start(), m.end()
        ctx_text = _context(normalized, ctx_start, ctx_end)
        # Fax detection: check 40 chars before the phone in context
        pre_phone = normalized[max(0, ctx_start - 40): ctx_start]
        is_fax = bool(re.search(r'\bfax\b', pre_phone, re.IGNORECASE))
        # Near names: find person names within ±200 chars of this phone
        nn_start = max(0, ctx_start - 200)
        nn_end = min(len(normalized), ctx_end + 200)
        nn_window = normalized[nn_start:nn_end]
        near_names = []
        for nm in _NAME_PATTERN.finditer(nn_window):
            nv = nm.group(0).strip()
            tokens = [tk for tk in nv.split() if not tk.endswith('.')]
            if len(tokens) < 2:
                continue
            if any(tk in _NOT_A_NAME_WORD for tk in tokens):
                continue
            if any(_de_accent(tk).lower() in _NOT_A_NAME_WORD_PLAIN for tk in tokens):
                continue
            if _is_blocked_name(nv):
                continue
            if nv not in near_names:
                near_names.append(nv)
        result["phones"].append({
            "value": raw,
            "context": ctx_text,
            "is_fax": is_fax,
            "near_names": near_names,
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
- IGNORUJ fax čísla: v phones[] každý záznam má is_fax:true/false — NIKDY nevyberaj číslo kde is_fax=true
- PREFERUJ telefón ktorý má contact_name v near_names[] — ak phones[X].near_names obsahuje meno vybraného kontaktu, VYBER TOTO číslo. near_names ukazuje kto je fyzicky blízko telefónu na stránke

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
    # === DIAG: phone candidates dump ===
    print(f"🔬 DIAG extract_with_ai: {len(candidates['phones'])} phone kandidátov:")
    for i, p in enumerate(candidates["phones"][:15]):
        print(f"  📞 [{i}] {p['value']}  is_fax={p.get('is_fax',False)}  ctx={p['context'][:80]}...")
    print(f"🔬 DIAG: {len(candidates['names'])} name kandidátov:")
    for i, n in enumerate(candidates["names"][:15]):
        print(f"  👤 [{i}] {n['value']}  near_role={n.get('near_role','')}  ctx={n['context'][:80]}...")
    # === END DIAG ===
    try:
        response = openai_client.chat.completions.create(
            model=GPT_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        # AI občas vracia string "null" namiesto None — vyčisti
        for _f in ("contact_name", "role", "phone", "email"):
            if result.get(_f) in ("null", "None", "N/A", "n/a", "—", "-"):
                result[_f] = None
        print(f"AI result: phone={result.get('phone')}, contact_name={result.get('contact_name')}, "
              f"role={result.get('role')}, role_category={result.get('role_category')}")

        # Post-AI phone korekcia: ak AI vybrala contact_name, over že vybraný
        # telefón je skutočne blízko toho mena. Ak nie, nahraď telefónom ktorý JE.
        ai_contact = result.get("contact_name") or ""
        ai_phone = result.get("phone") or ""
        if ai_contact and ai_phone and candidates["phones"]:
            ai_phone_digits = re.sub(r'\D', '', ai_phone)
            contact_lower = ai_contact.lower()
            contact_parts = [p.lower() for p in ai_contact.split() if len(p) >= 3]

            def _phone_has_name(phone_entry: dict) -> bool:
                for nn in phone_entry.get("near_names", []):
                    nn_lower = nn.lower()
                    if contact_lower in nn_lower or nn_lower in contact_lower:
                        return True
                    if all(cp in nn_lower for cp in contact_parts):
                        return True
                return False

            # Nájdi phone entry pre AI-vybraný telefón
            current_entry = None
            for p in candidates["phones"]:
                if re.sub(r'\D', '', p["value"]) == ai_phone_digits:
                    current_entry = p
                    break

            current_has_name = current_entry and _phone_has_name(current_entry)

            if not current_has_name:
                # AI vybrala telefón ktorý NIE JE pri mene — hľadám lepší
                better = None
                for p in candidates["phones"]:
                    if p.get("is_fax"):
                        continue
                    if _phone_has_name(p):
                        better = p
                        break
                if better:
                    old_phone = result["phone"]
                    result["phone"] = better["value"]
                    print(f"📞 Phone korekcia: {old_phone} → {better['value']} "
                          f"(near_names={better.get('near_names', [])})")

        result["_candidates"] = candidates
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

async def _get_employee_count(ico: str, jurisdiction: str) -> dict:
    """Počet zamestnancov z finstat.sk (SK) alebo kurzy.cz (CZ)."""
    if not ico:
        return {"count_range": "unknown", "count_category": "unknown", "source": "none"}
    try:
        if jurisdiction == "SK":
            url = f"https://finstat.sk/{ico}"
        else:
            url = f"https://www.kurzy.cz/rejstrik-firem/ico-{ico}/"
        async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                     headers={"User-Agent": random.choice(_USER_AGENTS)}) as client:
            resp = await client.get(url)
            text = resp.text
        # SK: "Počet zamestnancov 5 - 9" alebo "1 - 4"
        m = re.search(r'Počet\s+zamestnancov[^<\d]*?(\d+)\s*[-–]\s*(\d+)', text, re.IGNORECASE)
        if m:
            low, high = int(m.group(1)), int(m.group(2))
            cat = "solo" if high <= 1 else "micro" if high <= 9 else "small" if high <= 49 else "medium" if high <= 249 else "large"
            return {"count_range": f"{low}-{high}", "count_category": cat, "source": "finstat"}
        m2 = re.search(r'zamestnancov[:\s]*(\d+)', text, re.IGNORECASE)
        if m2:
            count = int(m2.group(1))
            cat = "solo" if count <= 1 else "micro" if count <= 9 else "small" if count <= 49 else "medium"
            return {"count_range": str(count), "count_category": cat, "source": "finstat"}
    except Exception as e:
        print(f"_get_employee_count chyba: {e}")
    return {"count_range": "unknown", "count_category": "unknown", "source": "none"}


def _smart_phone_assignment(
    contact_name: Optional[str],
    phone: Optional[str],
    combined_text: str,
    employee_info: dict,
    candidates: dict,
) -> dict:
    """Určí phone_type, confidence, reasoning a other_contacts pre lead."""
    result: dict = {
        "phone_type": None,
        "phone_confidence": "low",
        "name_found_on_web": False,
        "reasoning": "",
        "other_contacts": [],
    }
    if not phone:
        result["reasoning"] = "Na webe e-shopu som nenašiel žiadne platné telefónne číslo"
        return result

    phone_digits = re.sub(r'\D', '', phone)
    text_norm = combined_text.replace('\xa0', ' ')
    text_lower = text_norm.lower()

    # KROK 1-2: Hľadaj contact_name blízko telefónu (±300 znakov)
    if contact_name:
        name_parts = contact_name.split()
        search_terms = [contact_name] + ([name_parts[-1]] if len(name_parts) > 1 else [])
        for term in search_terms:
            pos = text_lower.find(term.lower())
            if pos < 0:
                continue
            result["name_found_on_web"] = True
            win_s = max(0, pos - 300)
            win_e = min(len(text_norm), pos + 300)
            win_digits = re.sub(r'\D', '', text_norm[win_s:win_e])
            if phone_digits in win_digits:
                result["phone_type"] = "personal"
                result["phone_confidence"] = "high"
                result["reasoning"] = (
                    f"Na stránke som našiel meno konateľa {contact_name} "
                    f"a pri ňom telefón {phone} (±300 znakov) → osobný kontakt"
                )
                return result
            break

    # KROK 3: Hľadaj iné mená s rolou + telefónom
    _ROLE_RE = re.compile(
        r'vedúci|vedúca|správca|manažér|obchodné\s*odd|obchodný\s*zástupca|'
        r'zákaznícky\s*servis|zákaznícka\s*podpora|reklamáci|konateľ|konateľka|'
        r'jednateľ|riaditeľ|majiteľ|prevádzkovateľ|CEO|COO|CTO|'
        r'vedoucí|manažer|obchodní\s*odd|zákaznický\s*servis',
        re.IGNORECASE,
    )
    for name_entry in (candidates.get("names") or []):
        name_val = name_entry.get("value", "")
        if name_val == contact_name:
            continue
        ctx = name_entry.get("context", "")
        role_m = _ROLE_RE.search(name_entry.get("near_role", "") + " " + ctx)
        if not role_m:
            continue
        for ph_entry in (candidates.get("phones") or []):
            if name_val in ph_entry.get("near_names", []):
                other_phone = ph_entry.get("value", "")
                if other_phone and other_phone != phone:
                    result["other_contacts"].append({
                        "name": name_val,
                        "role": role_m.group(0),
                        "phone": other_phone,
                        "page": "/kontakt",
                    })
                    break
    result["other_contacts"] = result["other_contacts"][:3]

    # KROK 4: Rozhodnutie podľa veľkosti firmy
    emp_cat = employee_info.get("count_category", "unknown")
    emp_count = employee_info.get("count_range", "unknown")
    name_str = contact_name or "konateľa"

    if emp_cat in ("solo", "micro"):
        result["phone_type"] = "predpokladaný_osobný"
        result["phone_confidence"] = "medium"
        result["reasoning"] = (
            f"Meno {name_str} som nenašiel na webe pri čísle. "
            f"Firma má {emp_count} zamestnancov — predpokladám osobný kontakt."
        )
    else:
        result["phone_type"] = "info"
        result["phone_confidence"] = "low"
        result["reasoning"] = (
            f"Firma má {emp_count} zamestnancov. "
            f"Meno {name_str} nie je pri čísle → pravdepodobne info linka."
        )
    return result


class ScrapeRequest(BaseModel):
    url: str


# ─── v7 contact pairing (Kroky 1-5) ─────────────────────────────────────────

_PAIR_ROLE_RE = re.compile(
    r'vedúci|vedúca|manažér|obchodný|zákaznícky|konateľ|konateľka|'
    r'jednateľ|riaditeľ|majiteľ|prevádzkovateľ|CEO|'
    r'vedoucí|manažer|jednatel',
    re.IGNORECASE,
)


def _estimate_firm_size(
    jurisdiction: str,
    konatelia_count: int,
    osoby: list,
    registry_data: dict,
) -> Optional[str]:
    """Krok 5: SK size estimate when ARES data not available."""
    cat = registry_data.get("velkost_category")
    if cat:
        return cat
    # SK heuristic: ORSR konateľ count + web person count
    web_roles = sum(1 for o in osoby if o.get("rola"))
    if konatelia_count == 1 and web_roles <= 2:
        return "micro"
    if konatelia_count <= 3 and web_roles <= 5:
        return "micro"
    if konatelia_count >= 4 or web_roles >= 6:
        return "small"
    return "unknown"


_COMPANY_SUFFIXES = {"s.r.o", "a.s", "spol", "v.o.s", "k.s", "ltd", "gmbh", "s.r.o.", "a.s."}


def _is_person_name(name: str) -> bool:
    parts = name.strip().split()
    if len(parts) < 2:
        return False
    return not any(p.lower().rstrip(".") in _COMPANY_SUFFIXES for p in parts)


def pair_contact_with_phone(
    registry_data: dict,
    osoby: list,
    candidates: dict,
    combined_text: str,
    jurisdiction: str,
) -> dict:
    """
    Implementuje Kroky 1-5 zo špecifikácie.
    Vracia primary_contact, other_contacts, reasoning, velkost_category.
    """
    reasoning: list = []
    norm_text = re.sub(r'\s+', ' ', combined_text.replace('\xa0', ' '))
    norm_lower = norm_text.lower()

    all_phones = [p for p in candidates.get("phones", []) if not p.get("is_fax")]
    all_emails = candidates.get("emails", [])
    first_phone = all_phones[0]["value"] if all_phones else None
    first_email = all_emails[0]["value"] if all_emails else None
    first_email_type = _classify_email_type(first_email, "") if first_email else None

    konatel = registry_data.get("konatel")
    konatelia_count = registry_data.get("konatelia_count", 0)
    emp_cat = _estimate_firm_size(jurisdiction, konatelia_count, osoby, registry_data)

    def _other_contacts(exclude_name, exclude_phone):
        out = []
        for o in osoby:
            if o.get("meno") == exclude_name:
                continue
            if not o.get("rola"):
                continue
            tel = o.get("telefon_osoby")
            if tel and tel != exclude_phone:
                out.append({"name": o["meno"], "role": o["rola"], "phone": tel, "confidence": "MEDIUM"})
        return out[:3]

    # Krok 2: konateľ z registra nájdený na webe (pri telefóne alebo kdekoľvek)
    if konatel and first_phone and _is_person_name(konatel):
        phone_digits = re.sub(r'\D', '', first_phone)
        terms = [konatel] + ([konatel.split()[-1]] if len(konatel.split()) > 1 else [])
        for term in terms:
            pos = norm_lower.find(term.lower())
            if pos < 0:
                continue
            # Name IS on the web — check if phone is nearby (±300 chars)
            win_s, win_e = max(0, pos - 300), min(len(norm_text), pos + 300)
            phone_in_window = phone_digits in re.sub(r'\D', '', norm_text[win_s:win_e])
            if phone_in_window:
                ph_pos = norm_text.lower().find(re.sub(r'\D', '', first_phone)[:7], win_s)
                dist = abs((ph_pos if ph_pos >= 0 else pos) - pos)
                reasoning.append(f"Meno '{konatel}' nájdené na webe ({dist} znakov od čísla {first_phone})")
                return {
                    "primary_contact": {
                        "name": konatel, "role": "konateľ",
                        "name_source": "register+web",
                        "phone": first_phone, "phone_type": "osobny",
                        "phone_match": "proximity_direct_chars",
                        "email": first_email, "email_type": first_email_type,
                        "confidence": "HIGH",
                    },
                    "other_contacts": _other_contacts(konatel, first_phone),
                    "reasoning": reasoning,
                    "velkost_category": emp_cat,
                }
            else:
                reasoning.append(f"Meno '{konatel}' nájdené na webe, ďaleko od telefónu (register+web_distant)")
                return {
                    "primary_contact": {
                        "name": konatel, "role": "konateľ",
                        "name_source": "register+web_distant",
                        "phone": first_phone, "phone_type": "osobny",
                        "phone_match": "proximity_indirect_chars",
                        "email": first_email, "email_type": first_email_type,
                        "confidence": "MEDIUM-HIGH",
                    },
                    "other_contacts": _other_contacts(konatel, first_phone),
                    "reasoning": reasoning,
                    "velkost_category": emp_cat,
                }

    # Krok 3: iné meno s rolou + telefón na webe
    for o in osoby:
        if o.get("meno") == konatel:
            continue
        if not o.get("rola") or not _PAIR_ROLE_RE.search(o["rola"]):
            continue
        tel = o.get("telefon_osoby")
        if not tel:
            continue
        reasoning.append(f"Meno '{o['meno']}' (rola: {o['rola']}) nájdené na webe s telefónom {tel}")
        return {
            "primary_contact": {
                "name": o["meno"], "role": o["rola"],
                "name_source": "web_only",
                "phone": tel, "phone_type": "osobny",
                "phone_match": "proximity_300_chars",
                "email": first_email, "email_type": first_email_type,
                "confidence": "MEDIUM-HIGH",
            },
            "other_contacts": _other_contacts(o["meno"], tel),
            "reasoning": reasoning,
            "velkost_category": emp_cat,
        }

    # Krok 4: žiadne meno pri telefóne — rozhoduje veľkosť
    if not first_phone:
        reasoning.append("Žiadny telefón nenájdený na webe")
        _ns_no_phone = (
            "registry_only"
            if (konatel and _is_person_name(konatel) and registry_data.get("verified"))
            else None
        )
        return {
            "primary_contact": {
                "name": konatel, "role": "konateľ" if konatel else None,
                "name_source": _ns_no_phone, "phone": None, "phone_type": None,
                "phone_match": None, "email": first_email, "email_type": first_email_type,
                "confidence": "LOW",
            },
            "other_contacts": [],
            "reasoning": reasoning,
            "velkost_category": emp_cat,
        }

    # Phone exists but no name match
    if emp_cat in ("solo", "micro") or (jurisdiction == "SK" and emp_cat == "unknown"):
        phone_type, confidence = "odhad_osobny", "MEDIUM"
        reasoning.append(
            f"Konateľ '{konatel or '?'}' nenájdený pri telefóne. "
            f"Odhad veľkosti: {emp_cat} → telefón pravdepodobne osobný"
        )
    else:
        phone_type, confidence = "info", "LOW"
        reasoning.append(f"Firma odhad väčšia ({emp_cat}) → pravdepodobne info linka")

    _ns = (
        "registry_only"
        if (konatel and _is_person_name(konatel) and registry_data.get("verified"))
        else None
    )
    return {
        "primary_contact": {
            "name": konatel, "role": "konateľ" if konatel else None,
            "name_source": _ns, "phone": first_phone, "phone_type": phone_type,
            "phone_match": None, "email": first_email, "email_type": first_email_type,
            "confidence": confidence,
        },
        "other_contacts": _other_contacts(konatel, first_phone),
        "reasoning": reasoning,
        "velkost_category": emp_cat,
    }


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


# ─── FIX 1+3: Anchor link discovery ────────────────────────────────────────
def _find_candidate_subpages(html: bytes, base_url: str) -> tuple:
    """
    Skenuje VŠETKY <a href> na stránke — nie len nav/header.
    Hľadá URLs s kľúčovými slovami VOP/kontakt/o-nás/team.
    Umožňuje aj subdomény rovnakej registered domény (FIX 3).

    Returns: (regular_urls: list[str], pdf_urls: list[str])
      - regular_urls: max 15 URL (ne-PDF) s relevantným kľúčovým slovom
      - pdf_urls: max 3 PDF URL s relevantným kľúčovým slovom
    """
    if not html:
        return [], []
    try:
        html_str = html.decode('utf-8', errors='replace')
        soup = BeautifulSoup(html_str, 'html.parser')
        parsed_base = urlparse(base_url)
        # base_domain bez "www." pre subdomén matching
        base_domain = parsed_base.netloc.lower().replace('www.', '')

        vop_kw = [
            'obchodn', 'podmien', 'podmink', 'vop',
            'všeobecn', 'vseobecn',
        ]
        contact_kw = [
            'kontakt', 'contact',
            'o-nas', 'o nas', 'o nás', 'o-nás',
            'o-firme', 'o firme', 'about',
            'tim', 'team', 'vedenie', 'nas-tim', 'impressum',
            'informaci', 'informáci',
        ]
        all_kw = vop_kw + contact_kw

        regular_urls: list = []
        pdf_urls: list = []
        seen: set = set()

        for a in soup.find_all('a', href=True):
            href = (a.get('href') or '').strip()
            if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
                continue

            text = a.get_text(strip=True).lower()
            try:
                full_url = urljoin(base_url, href).split('#')[0]  # strip fragment
                parsed_full = urlparse(full_url)
                link_domain = parsed_full.netloc.lower().replace('www.', '')
            except Exception:
                continue

            # Scheme musí byť http/https
            if parsed_full.scheme not in ('http', 'https'):
                continue

            # Doménová kontrola: rovnaká doména ALEBO subdoména (FIX 3)
            if not (
                link_domain == base_domain
                or link_domain.endswith('.' + base_domain)
                or base_domain.endswith('.' + link_domain)
            ):
                continue

            if full_url in seen or full_url == base_url:
                continue

            # BUG 1 FIX: Preskoč login/redirect/register/ucet URL
            _SKIP_URL_PATTERNS = [
                'login', 'prihlasit', 'account', '/ucet',
                'register', 'registracia', 'registrace',
                '?back=', '&back=',
            ]
            if any(p in full_url.lower() for p in _SKIP_URL_PATTERNS):
                continue
            if len(full_url) > 300:
                continue

            seen.add(full_url)

            combined = (href + ' ' + text).lower()

            # PDF s relevantným kľúčovým slovom
            if full_url.lower().endswith('.pdf'):
                if any(kw in combined for kw in vop_kw + ['kontakt']):
                    pdf_urls.append(full_url)
                continue  # PDF nikdy do regular_urls

            # Bežný link s relevantným kľúčovým slovom
            if any(kw in combined for kw in all_kw):
                regular_urls.append(full_url)

        return regular_urls[:15], pdf_urls[:3]

    except Exception as e:
        print(f"_find_candidate_subpages výnimka: {e}")
        return [], []


# ─── FIX 2: PDF extraction ──────────────────────────────────────────────────
async def _extract_pdf_text(url: str, max_size_mb: float = 5.0) -> str:
    """
    Stiahne PDF cez httpx a extrahuje text cez pdfplumber.
    Max 5 MB, max 20 strán, max 50k znakov výstupu.
    Vracia "[PDF: filename]\\n<text>" alebo "" pri chybe.
    """
    try:
        import pdfplumber  # lazy import — nepovinný v prod
        from io import BytesIO
    except ImportError:
        print("⚠️ pdfplumber nie je nainštalovaný — skip PDF extraction")
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; bot/1.0)"},
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                print(f"⚠️ PDF HTTP {resp.status_code}: {url}")
                return ""
            if len(resp.content) > max_size_mb * 1024 * 1024:
                print(f"⚠️ PDF príliš veľký (>{max_size_mb:.0f}MB): {url}")
                return ""
            text_parts: list = []
            with pdfplumber.open(BytesIO(resp.content)) as pdf:
                for page in pdf.pages[:20]:
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)
                    if sum(len(t) for t in text_parts) >= 50000:
                        break
            text = "\n".join(text_parts).strip()
            fname = url.rsplit('/', 1)[-1]
            result = f"[PDF: {fname}]\n{text}"
            print(f"📄 PDF extrahovaný: {url} ({len(text)} znakov)")
            return result
    except Exception as e:
        print(f"⚠️ PDF extract chyba pre {url}: {e}")
        return ""


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
        # OPRAVA 3: team/vedenie subpages — napr. bioruza.sk/nas-tim
        "nas-tim", "nas-team", "tim", "nas-tym", "o-tim",
        "o-nasom-time", "our-team", "vedenie-spolocnosti",
        "impressum", "prevadzka", "organizacna-struktura",
    ]
    other_paths = [p for p in SUBPAGE_PATHS if p not in contact_priority_paths]
    all_paths = contact_priority_paths + other_paths

    jsonld_data: Dict[str, Any] = {}
    whois_data: Dict[str, Any] = {}

    # FORCE_PLAYWRIGHT=1 → preskočí httpx/cloudscraper a vynúti Playwright vetvu.
    # Použiť lokálne na simuláciu produkčného Cloudflare blokovania:
    #   FORCE_PLAYWRIGHT=1 python -c "import asyncio; from main import _scrape_all_pages; ..."
    force_playwright = os.getenv("FORCE_PLAYWRIGHT") == "1"
    if force_playwright:
        print(f"⚡ FORCE_PLAYWRIGHT=1: preskakujem httpx/cloudscraper pre {base_url}")

    # === KROK 1: homepage cez httpx + JSON-LD ===
    home_bytes = b"" if force_playwright else fetch_html_httpx(base_url)
    if home_bytes:
        jsonld_data = extract_jsonld_contacts(home_bytes)

    home_text = extract_text_from_html(home_bytes) if home_bytes else ""

    # Detekuj Cloudflare garbled content — ak httpx dostal zablokovanú odpoveď
    if force_playwright or is_garbled_content(home_text):
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
    print(f"[nav] Nav links objavene: {len(nav_links)} -- {str(nav_links[:5]).encode('ascii', errors='replace').decode('ascii')}")

    # FIX 1+3: Anchor link discovery — skenuje VŠETKY <a href>, vrátane VOP slugov a subdomén
    _cand_links, _pdf_links = _find_candidate_subpages(home_bytes, base_url) if home_bytes else ([], [])
    _added = 0
    for _u in _cand_links:
        if _u not in nav_links:
            nav_links.append(_u)
            _added += 1
    if _cand_links:
        print(f"🔍 Anchor kandidáti (+{_added} nových): {_cand_links[:5]}")
    if _pdf_links:
        print(f"📄 PDF kandidáti: {_pdf_links}")

    # === KROK 2: paralelný httpx + cloudscraper na všetky subpages ===
    sem = asyncio.Semaphore(5)  # max 5 concurrent fetches pre Render free tier (0.5 CPU)

    async def _fetch_fast(url: str) -> str:
        """Skúsi httpx, potom cloudscraper, potom retry s trailing slash. Bez Playwright.
        Garbled/binary obsah (Cloudflare block) sa nezaráta — vracia prázdny string.
        FORCE_PLAYWRIGHT=1: okamžite vráti prázdny string (vynúti Playwright vetvu)."""
        if force_playwright:
            print(f"⚡ FORCE_PLAYWRIGHT: skip httpx pre {url}")
            return ""
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
    jur_texts: List[str] = []  # prvých 10k znakov veľkých stránok pre IČO/DIČ scan
    _pw_extra_vop: List[str] = []   # VOP URLs objavené z Playwright-renderovania
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
        _pw_fetched_urls: set = set()
        _pw_queue: List[str] = list(pw_urls)  # mutable queue pre dynamické pridávanie VOP URLs
        while _pw_queue:
            url = _pw_queue.pop(0)
            if url in _pw_fetched_urls:
                continue
            _pw_fetched_urls.add(url)

            html = await fetch_html_playwright(url, browser_ctx=browser_ctx)
            if html:
                # Vytiahni JSON-LD ak sme ho ešte nemali
                if not jsonld_data:
                    jsonld_data = extract_jsonld_contacts(html)

                # FIX 2+1: Skenuj Playwright HTML pre PDF a VOP linky
                # (JS-rendered stránky odhaľujú linky ktoré Scrapling nevidel)
                _pw_cands, _pw_pdfs = _find_candidate_subpages(html, base_url)
                for _pp in _pw_pdfs:
                    if _pp not in _pdf_links:
                        _pdf_links.append(_pp)
                        print(f"📄 PDF objavený z PW stránky: {_pp}")
                # Nové VOP/podmienky URLs → VOP s podmienk/vop idú na FRONT (priorita)
                # BUG 2 FIX: URL samotná musí obsahovať VOP keyword — zabraňuje produktovým stránkam
                _vop_url_keywords = [
                    'obchodn', 'podmienk', 'podmink',
                    'vop/', '/vop', 'vseobecn', 'vseobecne',
                    'gdpr', 'reklamac', 'informacie/v',
                    'content/3-', 'a43',
                ]
                _vop_priority_kws = ['podmienk', 'podminky', 'vop']  # podmienky vždy na front
                _vop_info_kws = ['informaci', 'informáci']           # info-sekcie na back
                _vop_back_count = 0
                for _pc in _pw_cands:
                    if _pc in _pw_fetched_urls or _pc in _pw_queue:
                        continue
                    # BUG 2 FIX: URL musí obsahovať aspoň jeden VOP keyword
                    if not any(kw in _pc.lower() for kw in _vop_url_keywords):
                        continue
                    if any(kw in _pc.lower() for kw in _vop_priority_kws):
                        _pw_queue.insert(0, _pc)  # PRIORITA: VOP na FRONT fronty
                        print(f"🔍 VOP URL z PW scan (priorita): {_pc}")
                    elif (any(kw in _pc.lower() for kw in _vop_info_kws)
                            and _vop_back_count < 2):
                        _pw_queue.append(_pc)
                        _vop_back_count += 1
                        print(f"🔍 VOP URL z PW scan: {_pc}")

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
                if len(_full_text) > 50000:
                    page_text = _full_text[-50000:]
                    # Odrezaná časť (nie je v combined) → pre full-text IČO/DIČ scan
                    jur_texts.append(_full_text[:-50000])
                else:
                    page_text = _full_text
                pw_texts.append(page_text)

            # Memory cleanup po každej stránke
            try:
                await browser_ctx.clear_cookies()
            except Exception:
                pass
            gc.collect()

            # Safety limit — max 8 Playwright stránok celkovo
            if len(_pw_fetched_urls) >= 6:
                break
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

    print(f"🔎 PRED PW MERGE: combined={len(combined)}, pw_texts_count={len(pw_texts)}, "
          f"pw_total_chars={sum(len(t) for t in pw_texts)}")
    combined = (combined + "\n" + "\n".join(pw_texts)).strip()
    print(f"🔎 PO PW MERGE: combined={len(combined)}, has_Martin={'Martin' in combined}")

    # FIX 2: PDF extraction — po Playwright merge, aby PDF text šiel do finálneho combined
    # _pdf_links môže byť rozšírený aj z Playwright-renderovaných stránok (PDF scan v PW loope)
    if _pdf_links:
        _pdf_results = await asyncio.gather(
            *[_extract_pdf_text(u) for u in _pdf_links[:3]],
            return_exceptions=True,
        )
        for _pr in _pdf_results:
            if isinstance(_pr, str) and _pr:
                combined = combined + "\n" + _pr
                print(f"📄 PDF pridaný do combined ({len(_pr)} znakov)")

    # === KROK 5: WHOIS ako absolútny fallback ===
    if not has_good_contacts(combined) and not jsonld_data.get("email"):
        whois_data = whois_contacts(base_url)

    print(f"🔎 _scrape_all_pages RETURN: combined={len(combined)} znakov, "
          f"pw_texts_count={len(pw_texts)}, "
          f"has_Martin={'Martin' in combined}, "
          f"has_zodpoved={'zodpoved' in combined.lower()}")
    return {"text": combined, "jsonld": jsonld_data, "whois": whois_data,
            "jur_extra": "\n".join(jur_texts)}


async def _do_scrape(base_url: str) -> dict:
    """Core scrape logic. Called by scrape_lead and source_auto."""
    base_url = base_url.strip()
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    base_url = base_url.rstrip('/')
    try:
        scrape_out = await _scrape_all_pages(base_url)
        combined_text = scrape_out["text"]
        jsonld_data = scrape_out.get("jsonld", {})
        whois_data = scrape_out.get("whois", {})

        if not combined_text and not jsonld_data and not whois_data:
            raise HTTPException(status_code=400, detail="Nepodarilo sa načítať žiadny text.")

        # === v7: IČO → registry → pair contact → score ===

        # 1. IČO z textu
        ico_info = extract_ico_from_text(combined_text)
        scraped_ico = ico_info.get("ico") or ""

        # 2. Jurisdikcia
        jurisdiction_str = "SK" if ".sk" in base_url.lower() else "CZ" if ".cz" in base_url.lower() else "SK"

        # 3. Registry lookup (sync → run in executor to avoid blocking)
        registry_data: dict = {"source": None, "verified": False, "konatel": None,
                                "konatelia_count": 0, "velkost_category": None,
                                "obchodne_meno": None}
        if scraped_ico:
            try:
                loop = asyncio.get_event_loop()
                # Use IČO country hint (CZ prefix in DIČ) to override TLD-based jurisdiction.
                # Handles SK-TLD sites operated by CZ companies (e.g. evonashop.sk → EVONA a.s. CZ).
                ico_country = (ico_info.get("country") or "").lower()
                use_cz = ico_country == "cz" or (not ico_country and jurisdiction_str == "CZ")
                if use_cz:
                    reg = await loop.run_in_executor(None, lookup_cz, scraped_ico)
                else:
                    reg = await loop.run_in_executor(None, lookup_sk, scraped_ico)
                registry_data = reg
                print(f"📋 Registry [{reg.get('source')}] verified={reg.get('verified')} konatel={reg.get('konatel')}")
            except Exception as reg_err:
                print(f"⚠️ Registry lookup error: {reg_err}")

        # 4. Kandidáti + osoby
        candidates = extract_all_candidates(combined_text)
        osoby = associate_persons_with_roles(combined_text)

        # 5. Pair contact → phone
        pairing = pair_contact_with_phone(registry_data, osoby, candidates, combined_text, jurisdiction_str)
        pc = pairing["primary_contact"]

        # 6. Company name: registry > JSON-LD > domain
        company_name = registry_data.get("obchodne_meno") or jsonld_data.get("name") or _domain_of(base_url)

        # 7. phone_confirmed_by_user z DB (pre lock)
        phone_confirmed = False
        try:
            async with async_session() as session:
                stmt_existing = select(Lead).where(Lead.primary_url == base_url)
                ex_lead = (await session.execute(stmt_existing)).scalar_one_or_none()
                if ex_lead:
                    phone_confirmed = bool((ex_lead.lead_metadata or {}).get("phone_confirmed_by_user"))
        except Exception:
            pass

        # 8. Score — jediné miesto
        score_input = {
            "name_source": pc.get("name_source"),
            "phone": pc.get("phone"),
            "phone_type": pc.get("phone_type"),
            "email": pc.get("email"),
            "email_type": pc.get("email_type"),
            "registry_verified": registry_data.get("verified", False),
            "registry_konatel": registry_data.get("konatel"),
            "ico": scraped_ico,
            "velkost_category": pairing.get("velkost_category"),
            "other_contacts": pairing.get("other_contacts", []),
            "phone_confirmed_by_user": phone_confirmed,
        }
        score_result = scoring.calculate_lead_score(score_input)
        final_score = score_result["score"]
        final_tier = score_result["tier"]

        # 9. Full reasoning = registry steps + pairing steps + score steps
        full_reasoning = pairing.get("reasoning", []) + score_result["reasoning"]

        # Vertikála
        body_lower = combined_text.lower()
        vertical = "Unknown"
        if any(w in body_lower for w in ["home garden", "zahrada", "nábytok"]):
            vertical = "Home & Garden"
        elif any(w in body_lower for w in ["beauty", "kozmetika"]):
            vertical = "Beauty & Personal Care"
        elif any(w in body_lower for w in ["pet", "zvieratá"]):
            vertical = "Pet Supplies"

        # contact_channels pre DB
        contact_channels: dict = {}
        if pc.get("phone"):
            contact_channels["phone"] = pc["phone"]
        if pc.get("email"):
            contact_channels["email"] = pc["email"]

        db_metadata = {
            "scraped_url": base_url,
            "scraped_at": datetime.datetime.utcnow().isoformat(),
            "primary_url": base_url,
            "v7": True,
            "registry": registry_data,
            "primary_contact": pc,
            "other_contacts": pairing.get("other_contacts", []),
            "phone_confirmed_by_user": phone_confirmed,
        }

        def _build_response(action, lead_id):
            return {
                "action": action,
                "lead_id": lead_id,
                "url": base_url,
                "jurisdiction": jurisdiction_str,
                "ico": scraped_ico,
                "company_name": company_name,
                "registry": {
                    "source": registry_data.get("source"),
                    "verified": registry_data.get("verified", False),
                    "konatel": registry_data.get("konatel"),
                    "konatelia_count": registry_data.get("konatelia_count", 0),
                    "velkost_firmy": registry_data.get("velkost_category"),
                },
                "primary_contact": pc,
                "other_contacts": pairing.get("other_contacts", []),
                "all_phones": [p["value"] for p in candidates.get("phones", []) if not p.get("is_fax")],
                "all_emails": [e["value"] for e in candidates.get("emails", [])],
                "score": final_score,
                "tier": final_tier,
                "confidence": score_result["confidence"],
                "reasoning": full_reasoning,
                "score_breakdown": score_result["breakdown"],
                "scraped_at": db_metadata["scraped_at"],
                # legacy fields — frontend ignoruje kým ho neprerobíme
                "primary_identifier": company_name,
                "extracted": {
                    "email": pc.get("email"), "phone": pc.get("phone"),
                    "contact_name": pc.get("name"), "contact_role": pc.get("role"),
                    "ico": scraped_ico, "phone_type": pc.get("phone_type"),
                    "phone_confidence": pc.get("confidence"),
                    "registry_source": registry_data.get("source") or "",
                    "reasoning": full_reasoning, "other_contacts": pairing.get("other_contacts", []),
                    "score_breakdown": score_result["breakdown"],
                },
            }

        # Uloženie — wrap do try/except
        try:
            async with async_session() as session:
                stmt = select(Lead).where(Lead.primary_url == base_url)
                existing = (await session.execute(stmt)).scalar_one_or_none()
                if existing:
                    existing.contact_channels = contact_channels
                    existing.vertical = vertical
                    existing.lead_metadata = db_metadata
                    existing.final_score = final_score
                    existing.tier = final_tier
                    await session.commit()
                    await session.refresh(existing)
                    return _build_response("updated", existing.lead_id)
                else:
                    new_lead = Lead(
                        lead_id=str(uuid.uuid4()),
                        primary_identifier=company_name,
                        primary_url=base_url,
                        vertical=vertical,
                        lead_metadata=db_metadata,
                        contact_channels=contact_channels,
                        final_score=final_score,
                        tier=final_tier,
                    )
                    session.add(new_lead)
                    await session.commit()
                    await session.refresh(new_lead)
                    return _build_response("created", new_lead.lead_id)
        except Exception as db_err:
            print(f"⚠️ DB chyba pri uložení lead, ale scraping OK: {db_err}")
            return {**_build_response("scrape_only", None),
                    "warning": f"DB nedostupná: {str(db_err)}"}


    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        import traceback
        error_detail = f"Scraping error: {str(e)}\n{traceback.format_exc()}"
        print(error_detail.encode('ascii', errors='replace').decode('ascii'))
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/leads/scrape")
async def scrape_lead(req: ScrapeRequest, user=Depends(verify_jwt)):
    return await _do_scrape(req.url)


class BatchRequest(BaseModel):
    urls: List[str]
    max_concurrent: int = 1  # ponytail: always sequential, server can't handle parallel


@app.post("/api/leads/batch")
async def batch_scrape(req: BatchRequest, user=Depends(verify_jwt)):
    """Sequentially scrape + save a list of URLs. Streams SSE progress events."""
    try:
        async with async_session() as session:
            result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == 1))
            org_config = result.scalar_one_or_none()
    except Exception:
        org_config = None

    async def _generate():
        total = len(req.urls)
        ok_count = 0
        for i, url in enumerate(req.urls):
            event: dict = {"i": i + 1, "total": total, "url": url}
            try:
                data = await _do_scrape(url)
                rule_score = evaluate_lead(data, org_config.scoring_rules) if org_config else 0
                thresholds = org_config.tier_thresholds if org_config else {"HOT": 80, "WARM": 60, "COOL": 40, "DEAD": 0}
                if rule_score >= thresholds["HOT"]: tier = "HOT"
                elif rule_score >= thresholds["WARM"]: tier = "WARM"
                elif rule_score >= thresholds.get("COOL", 40): tier = "COOL"
                else: tier = "DEAD"
                new_lead = Lead(
                    lead_id=str(uuid.uuid4()),
                    primary_identifier=data.get("primary_identifier", "Unknown"),
                    vertical=data.get("vertical"),
                    platform_presence=data.get("platform_presence", {}),
                    value_indicators=data.get("value_indicators", {}),
                    lead_metadata=data,
                    rule_score=rule_score,
                    final_score=rule_score,
                    tier=tier,
                )
                try:
                    async with async_session() as session:
                        session.add(new_lead)
                        await session.commit()
                except Exception:
                    pass  # ponytail: scrape result still emitted even if DB save fails
                ok_count += 1
                event.update({"status": "ok", "tier": tier, "score": rule_score,
                              "name": data.get("primary_identifier", url)})
            except Exception as e:
                event.update({"status": "error", "error": str(e)[:200]})
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True, 'total': total, 'ok': ok_count})}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


# ─── Context-aware phone deduplication ───────────────────────────────────────

# Rola keywords pre skórovanie kontextu telefónu
_CTX_ROLE_RE = re.compile(
    r'zodpovedn|odpovědn|odpovedna|konateľ|konatel|jednateľ|jednatel'
    r'|majiteľ|majitel|vlastník|riaditeľ|riaditel|ředitel|reditel'
    r'|provozn|prevadzk|prevádzk|\bsales\b|prokurista|\bceo\b|\bowner\b|\bfounder\b',
    re.IGNORECASE,
)
# Meno vo formáte Veľké Malé (aspoň 3+3 znakov)
_CTX_NAME_RE = re.compile(
    r'[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž]{2,}'
    r'[ \t]+'
    r'[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž]{2,}',
)
_CTX_TEL_RE = re.compile(r'\btel\b|\bmobil\b|\btelefon\b|\bphone\b', re.IGNORECASE)


def _ctx_score(ctx: str) -> int:
    """Skóre kontextu: +3 role keyword, +2 meno osoby, +1 tel/mobil label."""
    s = 0
    if _CTX_ROLE_RE.search(ctx): s += 3
    if _CTX_NAME_RE.search(ctx): s += 2
    if _CTX_TEL_RE.search(ctx):  s += 1
    return s


def _all_phone_positions(norm_text: str, phone_value: str) -> List[int]:
    """Vráti všetky pozície telefónu v texte — formátovaná aj kompaktná verzia (bez medzier)."""
    positions: List[int] = []
    # Formátovaná verzia (napr. "+421 948 028 999")
    pos = 0
    while True:
        idx = norm_text.find(phone_value, pos)
        if idx < 0:
            break
        positions.append(idx)
        pos = idx + 1
    # Kompaktná verzia — bez whitespace (napr. "+421948028999" → nájde aj "tel:+421948028999")
    compact = re.sub(r'\s+', '', phone_value)
    if compact != phone_value:
        pos = 0
        while True:
            idx = norm_text.find(compact, pos)
            if idx < 0:
                break
            if idx not in positions:
                positions.append(idx)
            pos = idx + 1
    return positions


def _extract_cisla_ico(
    candidates: Dict[str, Any],
    norm_text: str,
    jsonld_phone: Optional[str] = None,
) -> tuple:
    """
    Context-aware deduplikácia telefónov pre raw_extract endpoint.

    Rovnaké normalizované číslo sa môže vyskytovať na viacerých miestach
    (napr. v hlavičke aj v obchodných podmienkach). Namiesto prvého výskytu
    vyberieme ten s najvyšším skóre kontextu (role keyword > meno > tel label).

    Vracia (cisla_out, ico_out).
    """
    cisla_out: List[Dict[str, Any]] = []
    ico_out: Optional[str] = None
    seen_phones: set = set()

    # JSON-LD telefón — nemá kontext v texte, daj generický
    if jsonld_phone:
        p = jsonld_phone.strip()
        nk = re.sub(r'\D', '', p)
        if nk and nk not in seen_phones:
            seen_phones.add(nk)
            cisla_out.append({
                "cislo": p,
                "kontext": "JSON-LD schema (homepage)",
                "klucove_slova": [],
            })

    for entry in candidates.get("phones", []):
        p = entry["value"]
        norm_key = re.sub(r'\D', '', p)
        if not norm_key or norm_key in seen_phones:
            continue

        # Zbieraj VŠETKY pozície (formátovanú + kompaktnú verziu)
        all_pos = _all_phone_positions(norm_text, p)

        # IČO kontrola z textu PRED prvým výskytom
        if all_pos:
            first_before = norm_text[max(0, all_pos[0] - 80):all_pos[0]]
        else:
            first_before = entry.get("context", "")[:80]

        if _is_ico_context(first_before):
            if not ico_out and len(norm_key) >= 7:
                ico_out = p.strip()
            continue

        # Vyber výskyt s NAJVYŠŠÍM kontextovým skóre
        best_score = -1
        best_ctx_600: str = ""
        best_ctx_2000: str = ""

        if not all_pos:
            # Fallback na kontext z candidates
            fb = entry.get("context", "").strip()
            best_ctx_600 = fb
            best_ctx_2000 = fb
            best_score = _ctx_score(fb)
        else:
            plen = len(p)
            for idx in all_pos:
                ctx_600  = norm_text[max(0, idx - 600):idx + plen + 600].strip()
                ctx_2000 = norm_text[max(0, idx - 2000):idx + plen + 2000].strip()
                score = _ctx_score(ctx_600)
                if score > best_score:
                    best_score = score
                    best_ctx_600  = ctx_600
                    best_ctx_2000 = ctx_2000

        seen_phones.add(norm_key)
        cisla_out.append({
            "cislo": p,
            "kontext": best_ctx_600,
            "klucove_slova": _extract_klucove_slova(best_ctx_2000),
        })

    return cisla_out, ico_out


# ─── Detekcia jurisdikcie (SK / CZ) ──────────────────────────────────────────

_JUR_ICO_RE = re.compile(r'I[ČC]O?\s*[:.：]?\s*(\d[\d ]{5,9}\d)', re.IGNORECASE)
_JUR_DIC_SK = re.compile(
    r'(?:DI[ČC]|I[ČC]\s*DPH|VAT)\s*[:.：]?\s*(SK\s?\d[\d ]{6,12})', re.IGNORECASE
)
_JUR_DIC_CZ = re.compile(
    r'(?:DI[ČC]|I[ČC]\s*DPH|VAT)\s*[:.：]?\s*(CZ\s?\d[\d ]{6,12})', re.IGNORECASE
)
_JUR_STATE_SK = re.compile(
    r'Slovensk[aá]\s+republika|Slovensko\b|Slovak\s+Republic', re.IGNORECASE
)
_JUR_STATE_CZ = re.compile(
    r'[CČ]esk[aá]\s+republika|[CČ]esko\b|Czech\s+Republic', re.IGNORECASE
)
_JUR_CITY_SK = re.compile(
    r'\b(Bratislava|Košice|Prešov|Žilina|Nitra|Trnava|Trenčín|Martin|Poprad|'
    r'Banská\s+Bystrica|Piešťany|Zvolen|Ružomberok|Čadca|Galanta|Michalovce|'
    r'Humenné|Prievidza|Lučenec|Komárno|Levice|Topoľčany|Nové\s+Zámky|'
    r'Spišská\s+Nová\s+Ves|Liptovský\s+Mikuláš|Senec|Malacky|Pezinok|'
    r'Dunajská\s+Streda|Hlohovec|Senica)\b',
    re.IGNORECASE,
)
_JUR_CITY_CZ = re.compile(
    r'\b(Praha|Brno|Ostrava|Plzeň|Olomouc|Liberec|Pardubice|Zlín|Jihlava|'
    r'Blansko|Kladno|Most|Chomutov|Opava|Frýdek.Místek|Karlovy\s+Vary|'
    r'Hradec\s+Králové|České\s+Budějovice|Ústí\s+nad\s+Labem|Teplice|'
    r'Stehelčeves|Přerov|Prostějov|Třebíč|Slavičín)\b',
    re.IGNORECASE,
)
# SK PSČ: prefix 0xx, 8xx, 9xx — CZ PSČ: prefix 1xx–7xx
_JUR_PSC_RE = re.compile(r'PSČ\s*[:：]\s*(\d{3})\s?\d{2}', re.IGNORECASE)


def detect_jurisdiction(combined_text: str, url: str, extra_text: str = "") -> dict:
    """
    Detects whether an e-shop operates under SK or CZ jurisdiction.
    Aggregates 5 weighted signals. DIČ/IČ DPH prefix is authoritative.

    Dvojfázové skenovanie:
      Fáza 1 — IČO/DIČ: full combined_text + extra_text (začiatky veľkých stránok)
      Fáza 2 — štát/mesta/PSČ: posledných 50k combined_text (kontextové signály)

    Returns dict: jurisdiction, confidence (0-10), signals, ico, dic,
                  domain_country, domain_jurisdiction_match, ico_dic_found_in.
    """
    combined = combined_text or ""
    norm_full = re.sub(r'\s+', ' ', combined.replace('\xa0', ' '))
    # Fáza 2 okno: posledných 50k pre kontextové signály (štát, mesto, PSČ)
    ctx_window = norm_full[-50000:] if len(norm_full) > 50000 else norm_full
    # Fáza 1 zdroj: full combined + začiatky stránok z extra_text
    norm_extra = re.sub(r'\s+', ' ', extra_text.replace('\xa0', ' ')) if extra_text else ""
    ico_source = norm_full + (" " + norm_extra if norm_extra else "")

    sk_score = 0
    cz_score = 0
    signals: list = []
    ico_val: Optional[str] = None
    dic_val: Optional[str] = None
    ico_dic_found_in: Optional[str] = None

    # Signál 4: TLD domény (váha +1)
    domain_country = "OTHER"
    try:
        host = url.lower().split("//", 1)[-1].split("/")[0]
        host = re.sub(r'^www\.', '', host)
        tld = host.rsplit(".", 1)[-1] if "." in host else ""
        if tld == "sk":
            domain_country = "SK"
            sk_score += 1
            signals.append("domain:.sk")
        elif tld == "cz":
            domain_country = "CZ"
            cz_score += 1
            signals.append("domain:.cz")
    except Exception:
        pass

    # Fáza 1: IČO a DIČ/IČ DPH prefix — skenuj celý ico_source (combined + extra)
    m_ico = _JUR_ICO_RE.search(ico_source)
    if m_ico:
        ico_val = m_ico.group(1).replace(' ', '')
        signals.append(f"IČO:{ico_val}")
        # Zisti kde bolo nájdené
        pos = m_ico.start()
        if pos < len(norm_full):
            pct = pos / max(len(norm_full), 1)
            ico_dic_found_in = "header" if pct < 0.25 else ("footer" if pct > 0.75 else "middle")
        else:
            ico_dic_found_in = "header"  # bolo v extra_text (začiatok stránky)

    m_dic_sk = _JUR_DIC_SK.search(ico_source)
    m_dic_cz = _JUR_DIC_CZ.search(ico_source)

    if m_dic_sk and not m_dic_cz:
        dic_val = m_dic_sk.group(1).replace(' ', '')
        sk_score += 4
        signals.append(f"DIČ:{dic_val}(autoritatívne-SK)")
        pos = m_dic_sk.start()
        if pos < len(norm_full):
            pct = pos / max(len(norm_full), 1)
            ico_dic_found_in = "header" if pct < 0.25 else ("footer" if pct > 0.75 else "middle")
        else:
            ico_dic_found_in = "header"
    elif m_dic_cz and not m_dic_sk:
        dic_val = m_dic_cz.group(1).replace(' ', '')
        cz_score += 4
        signals.append(f"DIČ:{dic_val}(autoritatívne-CZ)")
        pos = m_dic_cz.start()
        if pos < len(norm_full):
            pct = pos / max(len(norm_full), 1)
            ico_dic_found_in = "header" if pct < 0.25 else ("footer" if pct > 0.75 else "middle")
        else:
            ico_dic_found_in = "header"
    elif m_dic_sk and m_dic_cz:
        dic_val = f"{m_dic_sk.group(1)}/{m_dic_cz.group(1)}"
        signals.append("DIČ:SK+CZ(multinational)")
        ico_dic_found_in = "middle"

    # Fáza 2: Kontextové signály — posledných 50k combined_text
    m_sk_st = _JUR_STATE_SK.search(ctx_window)
    m_cz_st = _JUR_STATE_CZ.search(ctx_window)
    if m_sk_st:
        sk_score += 3
        signals.append(f"štát:{m_sk_st.group(0)[:25]}")
    if m_cz_st:
        cz_score += 3
        signals.append(f"štát:{m_cz_st.group(0)[:25]}")

    sk_cities = _JUR_CITY_SK.findall(ctx_window)
    cz_cities = _JUR_CITY_CZ.findall(ctx_window)
    if sk_cities:
        sk_score += 2
        signals.append(f"mesto:SK({sk_cities[0]})")
    if cz_cities:
        cz_score += 2
        signals.append(f"mesto:CZ({cz_cities[0]})")

    for m in _JUR_PSC_RE.finditer(ctx_window):
        prefix = int(m.group(1))
        if 100 <= prefix <= 799:
            cz_score += 1
            signals.append(f"PSČ:CZ-rozsah({m.group(1)}xx)")
        else:
            sk_score += 1
            signals.append(f"PSČ:SK-rozsah({m.group(1)}xx)")
        break

    # Rozhodovanie
    both_dic = bool(m_dic_sk and m_dic_cz)
    auth_sk = bool(m_dic_sk and not m_dic_cz)
    auth_cz = bool(m_dic_cz and not m_dic_sk)

    if both_dic:
        jurisdiction = "UNKNOWN"
        confidence = max(0, min(10, max(sk_score, cz_score) - 3))
    elif auth_sk:
        jurisdiction = "SK"
        confidence = min(10, sk_score)
    elif auth_cz:
        jurisdiction = "CZ"
        confidence = min(10, cz_score)
    elif sk_score > cz_score + 2:
        jurisdiction = "SK"
        confidence = min(10, sk_score)
    elif cz_score > sk_score + 2:
        jurisdiction = "CZ"
        confidence = min(10, cz_score)
    elif sk_score > 0 and cz_score == 0 and domain_country == "SK":
        # TLD fallback: žiadne CZ signály, doména je .sk → SK s nízkou istotou
        jurisdiction = "SK"
        confidence = min(3, sk_score)
    elif cz_score > 0 and sk_score == 0 and domain_country == "CZ":
        # TLD fallback: žiadne SK signály, doména je .cz → CZ s nízkou istotou
        jurisdiction = "CZ"
        confidence = min(3, cz_score)
    else:
        jurisdiction = "UNKNOWN"
        confidence = min(10, max(sk_score, cz_score))

    domain_jurisdiction_match = (
        (jurisdiction == "SK" and domain_country == "SK")
        or (jurisdiction == "CZ" and domain_country == "CZ")
    )

    return {
        "jurisdiction": jurisdiction,
        "confidence": confidence,
        "signals": signals,
        "ico": ico_val,
        "dic": dic_val,
        "domain_country": domain_country,
        "domain_jurisdiction_match": domain_jurisdiction_match,
        "ico_dic_found_in": ico_dic_found_in,
    }


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

    # === OSOBY — direction-based role association ===
    osoby_raw = associate_persons_with_roles(combined_text)

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

    # === TELEFÓNY — context-aware dedupe ===
    cisla_out, ico_out = _extract_cisla_ico(
        candidates, norm_text, jsonld_phone=jsonld_data.get("phone")
    )

    # === Zostavenie osoby[] — telefon: z okna okolo mena, fallback na cisla kontext ===
    import unicodedata as _ud2
    def _ud2_strip(s: str) -> str:
        return ''.join(c for c in _ud2.normalize('NFD', s) if _ud2.category(c) != 'Mn')
    _norm_text_stripped = _ud2_strip(norm_text).lower()

    def _telefon_pre_osobu(p: dict) -> Optional[str]:
        # 1. Najdi cislo kde meno je FIZICKY NAJBLIZŠIE pred číslom (kontext approach)
        meno_lower = _ud2_strip(p["meno"]).lower()
        first_word = meno_lower.split()[0] if meno_lower.split() else ""
        if first_word and len(first_word) > 3:
            best_cislo, best_dist = None, 200
            for c in cisla_out:
                ctx = _ud2_strip(c.get("kontext") or "").lower()
                if not ctx:
                    continue
                ph_stripped = _ud2_strip(c["cislo"]).lower().strip()
                phone_idx = ctx.find(ph_stripped)
                if phone_idx < 0:
                    continue  # phone not found in kontext — skip
                # Name must appear BEFORE the phone in the kontext
                pre_phone = ctx[:phone_idx]
                idx = pre_phone.rfind(first_word)
                if idx >= 0:
                    dist = phone_idx - idx
                    if dist < best_dist:
                        best_dist = dist
                        best_cislo = c["cislo"]
            if best_cislo:
                return best_cislo
        # 2. Fallback: priamy nález v ±500 znakov okolo mena (z _find_phone_near_name)
        return p.get("telefon_osoby")

    osoby = [
        {
            "meno": p["meno"],
            "rola": p.get("rola"),
            "rola_level": p.get("rola_level", 0),
            "confidence": p.get("confidence", 0),
            "kontext": p.get("kontext", ""),
            "telefon": _telefon_pre_osobu(p),
        }
        for p in osoby_raw
    ]
    print(f"🔎 OSOBY: {len(osoby)} — {[(o['meno'], o['rola'], o['confidence']) for o in osoby]}", flush=True)

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

    jurisdiction_info = detect_jurisdiction(
        combined_text, base_url, extra_text=scrape_out.get("jur_extra", "")
    )

    return {
        "firma": firma,
        "emails": emails_out,
        "cisla": cisla_out,
        "ico": ico_out,
        "osoby": osoby,
        "poznamka": poznamka,
        "jurisdiction": jurisdiction_info,
    }


# ─── /api/leads/candidates — surové dáta pre UI výber ────────────────────────

_DELIVERY_CONTEXT_RE = re.compile(
    r'packeta|zásielkovňa|zasielkovna|geis|dpd|gls|slovenská pošta|slovenska posta'
    r'|česká pošta|ceska posta|ppl|toptrans|balíkovo|balikovo|spring courier'
    r'|expres kurier|shipmonk',
    re.IGNORECASE,
)


def _classify_phone_type(
    context: str,
    dist_to_konatel: Optional[int],
    near_name: Optional[str],
    near_email: Optional[str],
) -> str:
    """Classify phone as personal/info/delivery/unknown based on context."""
    ctx_lower = (context or "").lower()
    if _DELIVERY_CONTEXT_RE.search(ctx_lower):
        return "delivery"
    if dist_to_konatel is not None and dist_to_konatel < 50 and near_name:
        if not near_email or not is_generic_email(near_email):
            return "personal"
    if re.search(r'\bkontakt\b|\bzákaznícky\b|\bzakaznicky\b|\bservis\b|\binfo\b', ctx_lower):
        return "info"
    if near_name and dist_to_konatel is not None and dist_to_konatel < 150:
        return "personal"
    return "unknown"


def _classify_email_type(email: str, context: str) -> str:
    """Classify email as personal/generic/delivery/unknown."""
    if _email_is_ignored(email, context):
        return "ignored"
    if is_generic_email(email):
        return "generic"
    local = email.split("@")[0].lower()
    if any(len(p) >= 3 and p.isalpha() for p in re.split(r'[._\-]', local)):
        return "personal"
    return "unknown"


@app.post("/api/leads/candidates")
async def candidates_endpoint(req: ScrapeRequest, user=Depends(verify_jwt)):
    """Returns ALL scraped data with contexts for UI selection — no filtering/decisions."""
    from registry_lookup import extract_ico_from_text, lookup_registry

    base_url = req.url.strip()
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    base_url = base_url.rstrip("/")

    firma = _domain_of(base_url)

    try:
        scrape_out = await _scrape_all_pages(base_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scrape error: {e}")

    combined_text = scrape_out.get("text", "")
    jsonld_data = scrape_out.get("jsonld", {})

    if not combined_text:
        raise HTTPException(status_code=400, detail="Nepodarilo sa načítať žiadny text.")

    # Normalizovaný text pre pozičné hľadanie
    norm_text = combined_text.replace('\xa0', ' ')
    norm_text = re.sub(r'\n+', ' ', norm_text)
    norm_text = re.sub(r' {2,}', ' ', norm_text)
    norm_lower = norm_text.lower()

    # === Jurisdikcia ===
    jurisdiction_info = detect_jurisdiction(
        combined_text, base_url, extra_text=scrape_out.get("jur_extra", "")
    )
    jurisdiction = jurisdiction_info.get("jurisdiction", "unknown")

    # === IČO z textu ===
    ico_info = extract_ico_from_text(combined_text + " " + scrape_out.get("jur_extra", ""))
    ico = ico_info.get("ico")
    # Country from IČO context or jurisdiction detection
    country = ico_info.get("country") or (jurisdiction if jurisdiction in ("sk", "cz") else None)

    # === Registry lookup ===
    registry_data = {"source": None, "konatelia": [], "lookup_ok": False, "lookup_error": None}
    if ico:
        try:
            reg = lookup_registry(ico, country=country)
            registry_data["source"] = reg.get("source")
            registry_data["konatelia"] = reg.get("konatelia", [])
            registry_data["lookup_ok"] = reg.get("found", False)
            if reg.get("error"):
                registry_data["lookup_error"] = reg["error"]
            if reg.get("obchodne_meno") and not firma:
                firma = reg["obchodne_meno"]
        except Exception as e:
            registry_data["lookup_error"] = str(e)
            print(f"[WARN] Registry lookup failed for {ico}: {e}")

    registry_names = [k["meno"] for k in registry_data.get("konatelia", [])]

    # === Kandidáti z existujúcich extrakcií ===
    candidates = extract_all_candidates(combined_text)
    osoby_raw = associate_persons_with_roles(combined_text)

    # === PHONES — enrich with context ===
    phones_out = []
    seen_phone_norms = set()

    # Helper: find closest registry name and distance
    def _closest_registry_name(phone_pos: int) -> tuple:
        best_name, best_dist = None, None
        for rname in registry_names:
            rname_lower = rname.lower()
            idx = norm_lower.find(rname_lower)
            while idx >= 0:
                dist = abs(phone_pos - idx)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_name = rname
                idx = norm_lower.find(rname_lower, idx + 1)
        return best_name, best_dist

    # Helper: find closest email to phone position
    def _closest_email(phone_pos: int, window: int = 300) -> Optional[str]:
        best, best_dist = None, window + 1
        for em in _EMAIL_POS_RE.finditer(norm_text):
            dist = abs(em.start() - phone_pos)
            if dist < best_dist:
                best_dist = dist
                best = em.group(0)
        return best

    # Helper: which subpage the phone appears on
    def _detect_page(ctx: str) -> Optional[str]:
        ctx_l = ctx.lower()
        for path in ["kontakt", "contact", "obchodne-podmienky", "o-nas", "about",
                      "obchodni-podminky", "vop", "impressum", "vedenie", "team"]:
            if path in ctx_l:
                return f"/{path}"
        return None

    _PRODUCT_CTX_RE = re.compile(
        r'(?:košík|do košíka|pridať|cena|€|eur |skladom|ks|kus[oy]?v'
        r'|produkt|tovar|objednať|veľkosť|farba|materiál|hmotnosť'
        r'|rozmer|balenie|EAN|kód|SKU|katalóg)',
        re.IGNORECASE,
    )

    for entry in candidates.get("phones", []):
        phone_val = entry["value"]
        norm_key = re.sub(r'\D', '', phone_val)
        if norm_key in seen_phone_norms:
            continue
        seen_phone_norms.add(norm_key)

        # Skip bare numbers (no +/00/0 prefix) in product context
        if not phone_val.lstrip().startswith(('+', '00', '0')):
            ctx = entry.get("context", "")
            if _PRODUCT_CTX_RE.search(ctx):
                continue

        # Find phone position in normalized text
        phone_pos = norm_text.find(phone_val)
        if phone_pos < 0:
            compact = re.sub(r'\s+', '', phone_val)
            phone_pos = norm_text.find(compact)

        # Context windows
        if phone_pos >= 0:
            ctx_before = norm_text[max(0, phone_pos - 100):phone_pos].strip()
            ctx_after = norm_text[phone_pos + len(phone_val):phone_pos + len(phone_val) + 100].strip()
        else:
            ctx = entry.get("context", "")
            mid = len(ctx) // 2
            ctx_before = ctx[:mid].strip()
            ctx_after = ctx[mid:].strip()

        near_name, dist = _closest_registry_name(phone_pos) if phone_pos >= 0 else (None, None)
        near_email = _closest_email(phone_pos) if phone_pos >= 0 else None
        full_ctx = ctx_before + " " + phone_val + " " + ctx_after
        page_hint = _detect_page(full_ctx)

        typ = _classify_phone_type(full_ctx, dist, near_name, near_email)

        phones_out.append({
            "cislo": phone_val,
            "kontext_pred": ctx_before[-100:],
            "kontext_po": ctx_after[:100],
            "vzdialenost_od_konatela": dist,
            "blizke_meno": near_name,
            "blizky_email": near_email,
            "stranka": page_hint,
            "typ_pravdepodobne": typ,
        })

    # === EMAILS — enrich with context ===
    emails_out = []
    seen_email_keys = set()

    for entry in candidates.get("emails", []):
        email_val = entry["value"]
        key = email_val.lower()
        if key in seen_email_keys:
            continue
        seen_email_keys.add(key)

        ctx = entry.get("context", "")
        mid = len(ctx) // 2
        typ = _classify_email_type(email_val, ctx)
        if typ == "ignored":
            continue

        email_pos = norm_text.find(email_val)
        page_hint = _detect_page(ctx) if ctx else None

        emails_out.append({
            "email": email_val,
            "kontext_pred": ctx[:mid].strip()[-100:] if ctx else "",
            "kontext_po": ctx[mid:].strip()[:100] if ctx else "",
            "stranka": page_hint,
            "typ_pravdepodobne": typ,
        })

    # === MENO KANDIDÁTI — from registry + associate_persons_with_roles + self-intro ===
    kandidati_meno = []
    seen_names_lower = set()

    # Registry konatelia (highest authority)
    for k in registry_data.get("konatelia", []):
        name = k.get("meno", "")
        if not name or name.lower() in seen_names_lower:
            continue
        seen_names_lower.add(name.lower())
        # Find context in text
        ctx = ""
        idx = norm_lower.find(name.lower())
        if idx >= 0:
            ctx = norm_text[max(0, idx-50):idx+len(name)+50].strip()
        kandidati_meno.append({
            "meno": name,
            "rola": k.get("funkcia"),
            "zdroj": registry_data.get("source") or "registry",
            "confidence": 10,
            "kontext": ctx,
        })

    # Osoby from associate_persons_with_roles
    for o in osoby_raw:
        name = o.get("meno", "")
        if not name or name.lower() in seen_names_lower:
            continue
        seen_names_lower.add(name.lower())
        kandidati_meno.append({
            "meno": name,
            "rola": o.get("rola"),
            "zdroj": "scrape_association",
            "confidence": o.get("confidence", 0),
            "kontext": o.get("kontext", "")[:200],
        })

    # Self-intro detection (simple "volám sa X" scan)
    _self_intro_simple = re.compile(
        r'(?:volám\s+sa|ja\s+som|moje\s+meno\s+je)\s+'
        r'([A-ZÁČĎÉÍĽĹŇÓÔŔŘŠŤÚŮÝŽ][a-záčďéíľĺňóôŕřšťúůýž]{2,})',
        re.IGNORECASE,
    )
    for m in _self_intro_simple.finditer(norm_text):
        fn = m.group(1)
        if fn.lower() in seen_names_lower:
            continue
        if _is_blocked_name(fn):
            continue
        ctx_s = max(0, m.start() - 30)
        ctx_e = min(len(norm_text), m.end() + 80)
        kandidati_meno.append({
            "meno": fn,
            "rola": None,
            "zdroj": "self_intro",
            "confidence": 5,
            "kontext": norm_text[ctx_s:ctx_e].strip(),
        })

    # === Scraped pages hint ===
    scraped_pages = []
    for path in ["kontakt", "contact", "o-nas", "about", "obchodne-podmienky",
                  "obchodni-podminky", "vop", "impressum", "vedenie", "team", "tym"]:
        if path in norm_lower:
            scraped_pages.append(f"/{path}")

    # === Warnings ===
    warnings = []
    if not combined_text or len(combined_text) < 200:
        warnings.append("Veľmi málo textu bolo získané — pravdepodobne Cloudflare blokácia")
    if not candidates.get("phones"):
        warnings.append("Žiadne telefónne čísla neboli nájdené")
    if not candidates.get("emails"):
        warnings.append("Žiadne emaily neboli nájdené")

    return {
        "url": base_url,
        "firma": firma,
        "jurisdiction": jurisdiction,
        "ico": ico,
        "registry": registry_data,
        "phones": phones_out[:20],
        "emails": emails_out[:15],
        "kandidati_meno": kandidati_meno,
        "scraped_pages": scraped_pages,
        "scrape_warnings": warnings,
    }


def _generate_action_note(
    tier: str,
    meno: str,
    phone: dict,
    email: dict,
    rola: str = None,
) -> str:
    """Generate action note — what user should do with this contact."""
    action = TIER_ACTIONS.get(tier, "Unknown action")
    notes = [f"\U0001f3af Akcia: {action}"]

    if phone:
        tel = phone.get("cislo", "?")
        notes.append(f"\U0001f4de Volaj: {tel}")
        if meno:
            notes.append(f"\U0001f464 Spýtaj sa na: {meno}")
            if rola:
                notes.append(f"   Pozícia: {rola}")
    else:
        notes.append("\U0001f4de Telefón: nie je dostupný")
        if meno:
            notes.append(f"\U0001f4e7 Namiesto toho: pošli email pre {meno}")

    if email:
        em = email.get("email", "?")
        notes.append(f"\U0001f4e7 Email: {em}")

    if not phone and not email:
        notes.append("⚠️ Info: máš len registry dáta bez kontaktov — hľadaj manuálne")

    return "\n".join(notes)


# ─── /api/leads/confirm — user potvrdil telefón ───────────────────────────────

class ConfirmRequest(BaseModel):
    lead_id: str
    field: str
    value: bool


@app.post("/api/leads/confirm")
async def confirm_lead(req: ConfirmRequest, user=Depends(verify_jwt)):
    """Potvrdenie telefónu používateľom → tier sa zamkne na HOT/WARM, confidence = CONFIRMED."""
    if req.field != "phone_confirmed_by_user":
        raise HTTPException(status_code=400, detail=f"Unsupported field: {req.field}")

    async with async_session() as session:
        stmt = select(Lead).where(Lead.lead_id == req.lead_id)
        lead = (await session.execute(stmt)).scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        meta = dict(lead.lead_metadata or {})
        meta["phone_confirmed_by_user"] = req.value

        pc = meta.get("primary_contact", {})
        score_input = {
            "name_source": pc.get("name_source"),
            "phone": pc.get("phone"),
            "phone_type": pc.get("phone_type"),
            "email": pc.get("email"),
            "email_type": pc.get("email_type"),
            "registry_verified": meta.get("registry", {}).get("verified", False),
            "registry_konatel": meta.get("registry", {}).get("konatel"),
            "ico": None,
            "velkost_category": None,
            "other_contacts": meta.get("other_contacts", []),
            "phone_confirmed_by_user": req.value,
        }
        score_result = scoring.calculate_lead_score(score_input)

        lead.lead_metadata = meta
        lead.final_score = score_result["score"]
        lead.tier = score_result["tier"]
        await session.commit()

        return {
            "lead_id": req.lead_id,
            "phone_confirmed_by_user": req.value,
            "score": score_result["score"],
            "tier": score_result["tier"],
            "confidence": score_result["confidence"],
        }


# ─── /api/leads/select — user vybral správne hodnoty ─────────────────────────

class SelectRequest(BaseModel):
    url: str
    selected: dict
    metadata: Optional[dict] = None


@app.post("/api/leads/select")
async def select_lead(req: SelectRequest, user=Depends(verify_jwt)):
    """User selected the correct values from candidates UI — score + save."""
    base_url = req.url.strip().rstrip("/")
    sel = req.selected
    meta = req.metadata or {}

    meno = sel.get("meno")
    rola = sel.get("rola")
    telefon = sel.get("telefon")
    email_val = sel.get("email")
    ico = sel.get("ico")

    registry_konatelia = meta.get("registry_konatelia", [])
    registry_source = meta.get("registry_source")
    has_registry = len(registry_konatelia) > 0 or meta.get("zdroj") in ("ares", "orsr", "registry")

    raw_phone_type = meta.get("phone_type") or meta.get("user_marked_phone_as")
    # Map legacy phone_type values → v7 names
    v7_phone_type = (
        "osobny" if raw_phone_type == "personal" or raw_phone_type == "personal_matched"
        else "info" if raw_phone_type in ("info", "info_kontakt", "info_generic")
        else None
    )

    email_type = "personal" if (email_val and not is_generic_email(email_val)) else "generic"

    # name_source: if meno matches a registry konateľ → register+web, else web_only
    name_source = None
    if meno:
        if any(k.get("meno", "").lower() == meno.lower() for k in registry_konatelia):
            name_source = "register+web"
        else:
            name_source = "web_only"

    score_input = {
        "name_source": name_source,
        "phone": telefon,
        "phone_type": v7_phone_type,
        "email": email_val,
        "email_type": email_type,
        "registry_verified": has_registry,
        "registry_konatel": meno,
        "ico": ico,
        "velkost_category": None,
        "other_contacts": [],
        "phone_confirmed_by_user": False,
    }
    score_result = scoring.calculate_lead_score(score_input)
    score, tier = score_result["score"], score_result["tier"]
    breakdown = score_result["breakdown"]

    action_note = _generate_action_note(
        tier=tier,
        meno=meno,
        phone={"cislo": telefon} if telefon else None,
        email={"email": email_val} if email_val else None,
        rola=rola,
    )

    firma = _domain_of(base_url)
    lead_data = {
        "primary_identifier": firma,
        "vertical": "Unknown",
        "contact_channels": {},
        "lead_metadata": {
            "scraped_url": base_url,
            "scraped_at": datetime.datetime.utcnow().isoformat(),
            "contact_name": meno,
            "contact_role": rola,
            "scraped_email": email_val,
            "scraped_phone": telefon,
            "ico": ico,
            "selection_metadata": meta,
            "source": "candidates_select",
        },
    }
    if email_val:
        lead_data["contact_channels"]["email"] = email_val
    if telefon:
        lead_data["contact_channels"]["phone"] = telefon

    lead_id = None
    saved = False
    save_error = None

    try:
        async with async_session() as session:
            stmt = select(Lead).where(Lead.primary_identifier == firma)
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing:
                existing.contact_channels = lead_data["contact_channels"]
                existing.lead_metadata = lead_data["lead_metadata"]
                existing.final_score = score
                existing.rule_score = score
                existing.tier = tier
                await session.commit()
                await session.refresh(existing)
                lead_id = existing.lead_id
            else:
                new_lead = Lead(
                    lead_id=str(uuid.uuid4()),
                    primary_identifier=firma,
                    vertical="Unknown",
                    lead_metadata=lead_data,
                    contact_channels=lead_data.get("contact_channels", {}),
                    rule_score=score,
                    final_score=score,
                    tier=tier,
                )
                session.add(new_lead)
                await session.commit()
                await session.refresh(new_lead)
                lead_id = new_lead.lead_id
            saved = True
    except Exception as e:
        save_error = str(e)
        print(f"[WARN] DB save failed (scoring still returned): {e}")

    return {
        "status": "success",
        "lead_id": lead_id,
        "lead": {
            "url": base_url,
            "meno": meno,
            "rola": rola or "unknown",
            "telefon": telefon,
            "email": email_val,
            "registry_source": registry_source,
            "ico": ico,
        },
        "score": {
            "total": score,
            "breakdown": breakdown,
        },
        "tier": {
            "name": tier,
            "emoji": TIER_COLORS.get(tier, "❓"),
            "action": TIER_ACTIONS.get(tier, "Unknown"),
        },
        "action_note": action_note,
        "saved": saved,
        "save_error": save_error,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE CHANNELS — Profesia.sk + Heureka.sk
# ══════════════════════════════════════════════════════════════════════════════

AGENCY_BLOCKLIST: frozenset = frozenset({
    "grafton", "manpower", "adecco", "trenkwalder", "randstad",
    "hays", "gi group", "synergie", "personnel", "temporary",
    "personálna agentúra", "personalka", "recruitment",
    "workforce", "lugera", "head hunt", "headhunt", "mcbride",
    "merit", "atlas group", "work service", "antal", "kienbaum",
    "staffing", "executive search", "jobsider", "profesia services",
    # extended
    "proplusco", "start people", "kelly services", "express people",
    "advantage consulting", "mcroy", "talentpro",
    "personálne", "personalne", "personalna", "personalny",
    "práca pre vás", "praca pre vas", "agentúra práce", "agentura prace",
    "sprostredkovanie", "job agency", "human resources",
    "personal agency", "hr partner", "hr solutions",
    "pracovná agentúra", "pracovna agentura",
})

MARKET_BLOCKLIST: frozenset = frozenset({
    "mall.sk", "mall.cz", "alza.sk", "alza.cz",
    "allegro.sk", "allegro.cz", "allegro.pl",
    "amazon", "notino.sk", "notino.cz",
    "datart.sk", "datart.cz", "nay.sk",
    "tesco.sk", "lidl.sk", "kaufland.sk",
    "heureka.sk", "heureka.cz", "ceneo.pl",
    "bol.com", "ok-shop.sk",
})


def _is_agency(name: str) -> bool:
    n = name.lower()
    return any(a in n for a in AGENCY_BLOCKLIST)


def _filter_agencies(jobs: list) -> tuple:
    """Returns (unique_company_jobs, agency_names). Filters by blocklist + 5+ unique job titles heuristic."""
    company_positions: dict = {}
    for j in jobs:
        comp = j["company_name"].lower().strip()
        company_positions.setdefault(comp, set()).add(j["job_title"].lower().strip())

    agency_keys: set = set()
    for comp, positions in company_positions.items():
        if any(a in comp for a in AGENCY_BLOCKLIST):
            agency_keys.add(comp)
        elif len(positions) >= 5:
            # ponytail: staffing agencies post many different roles; 5+ unique titles = agency
            agency_keys.add(comp)

    filtered, agencies = [], []
    seen_companies: set = set()
    for j in jobs:
        comp_key = j["company_name"].lower().strip()
        if comp_key in agency_keys:
            if j["company_name"] not in agencies:
                agencies.append(j["company_name"])
            continue
        if comp_key in seen_companies:
            continue
        seen_companies.add(comp_key)
        filtered.append(j)

    return filtered, agencies


def _is_market(name: str, url: str = "") -> bool:
    n, u = name.lower(), url.lower()
    return any(m in n or m in u for m in MARKET_BLOCKLIST)


class ProfesiaSourceRequest(BaseModel):
    keyword: str
    location: Optional[str] = None
    max_results: int = 20


_PROFESIA_NOISE_DOMAINS = re.compile(
    r"profesia|almacareer|platy|google|facebook|linkedin|twitter|instagram|"
    r"youtube|youtu\.be|vimeo|tiktok|pinterest|snapchat|"
    r"edujobs|dielne|sosrdcom|najzamest|jobs\.cz|prace\.cz|nelisa|arnold-robot|"
    r"teamio|seduo|paylab|cvonline|visidarbi|otsintood|personaloatrankos|"
    r"recruitment\.lv|mojposao|vrabotuvanje|hercul|virtualvalley|zadovoljstvo|"
    r"jobly|pracezaroh|pracazaroh|atmoskop|spotify|intercom\.help|"
    r"w3\.org|gstatic|googleapis|botsrv|pracezarohem|pracazarohom",
    re.I,
)

def _extract_url_from_company_info(soup: "BeautifulSoup") -> str | None:  # type: ignore[name-defined]
    """Vytiahne URL z .company-info sekcie (anchor alebo plain text)."""
    ci = soup.select_one(".company-info")
    if not ci:
        return None
    for a in ci.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("http") and not _PROFESIA_NOISE_DOMAINS.search(href):
            return href
    ci_text = ci.get_text(" ", strip=True)
    for match in re.finditer(
        r'(?:https?://|www\.)[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])\.[a-z]{2,}(?:/[^\s]*)?',
        ci_text,
    ):
        url = match.group(0)
        if not _PROFESIA_NOISE_DOMAINS.search(url):
            return url if url.startswith("http") else "https://" + url
    return None


def _fetch_company_url_from_job(job_url: str) -> str | None:
    """Stiahne detail inzerátu (O-slug) a prípadne firemný profil (C-slug) pre reálnu URL."""
    html_bytes = fetch_html_httpx(job_url)
    if not html_bytes:
        return None
    soup = BeautifulSoup(html_bytes.decode("utf-8", errors="replace"), "html.parser")

    # 1) URL z .company-info na job-detail stránke
    url = _extract_url_from_company_info(soup)
    if url:
        return url

    # 2) Fallback: firemný profil /praca/{slug}/C{id} má rovnakú sekciu, ale niekedy naviac
    cp_a = soup.find("a", href=re.compile(r"^/praca/[^/]+/C\d+"))
    if cp_a:
        cp_url = "https://www.profesia.sk" + cp_a["href"].split("?")[0]
        cp_html = fetch_html_httpx(cp_url)
        if cp_html:
            cp_soup = BeautifulSoup(cp_html.decode("utf-8", errors="replace"), "html.parser")
            url = _extract_url_from_company_info(cp_soup)
            if url:
                return url

    return None


async def _validate_slug_url(slug: str) -> str | None:
    """HEAD-validates profesia slug candidates. 403 = exists but blocks HEAD."""
    candidates = [
        f"https://www.{slug}.sk",
        f"https://{slug}.sk",
        f"https://www.{slug}.com",
    ]
    async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
        for url in candidates:
            try:
                r = await client.head(url)
                if r.status_code in (200, 301, 302, 403):
                    return str(r.url)
            except Exception:
                continue
    return None


async def _create_registry_only_lead(company: dict) -> dict | None:
    """Registry-only lead pre firmy s IČO ale bez web URL.
    Volá lookup_sk(ico) → konateľ + veľkosť, potom score cez calculate_lead_score.
    """
    ico = company.get("ico")
    if not ico:
        return None
    try:
        loop = asyncio.get_event_loop()
        reg = await loop.run_in_executor(None, lookup_sk, ico)
    except Exception as e:
        print(f"[registry_only] lookup_sk error for {ico}: {e}")
        return None

    konatel = reg.get("konatel")
    velkost = reg.get("velkost_category")
    verified = reg.get("verified", False)

    score_result = scoring.calculate_lead_score({
        "name_source": "registry_only",
        "registry_verified": verified,
        "registry_konatel": konatel,
        "ico": ico,
        "velkost_category": velkost,
        "phone": None,
        "phone_type": None,
        "email": None,
        "email_type": None,
        "jurisdiction": "SK",
        "hiring_signal": company.get("source_signal") == "hiring_sales_rep",
    })

    job_url = company.get("job_url")
    konatelia_count = reg.get("konatelia_count", 1 if konatel else 0)
    return {
        "url": job_url,
        "company_name": company.get("company_name"),
        "domain": None,
        "url_confidence": "registry_only",
        "ico": ico,
        "primary_contact": {
            "name": konatel,
            "role": "konateľ",
            "phone": None,
            "email": None,
            "name_source": "registry_only",
        },
        "registry": {
            "source": reg.get("source", "ORSR"),
            "verified": verified,
            "konatel": konatel,
            "konatelia_count": konatelia_count,
            "velkost_firmy": velkost,
        },
        "score": score_result["score"],
        "tier": score_result["tier"],
        "confidence": score_result["confidence"],
        "reasoning": score_result["reasoning"] + [
            f"Firma hľadá obchodníka na profesii ({company.get('job_title', '')}), "
            "konateľ overený v registri, web nenájdený"
        ],
        "score_breakdown": score_result["breakdown"],
        "source_signal": company.get("source_signal"),
        "source_channel": "profesia",
        "job_url": job_url,
    }


async def _scrape_profesia_pages(keyword: str, max_results: int) -> list:
    """Fetch all profesia pages up to max_results raw job entries (not yet deduped/filtered)."""
    encoded = urllib.parse.quote_plus(keyword)
    all_jobs: list = []
    max_pages = max(2, (max_results // 20) + 2)

    for page in range(1, max_pages + 1):
        if len(all_jobs) >= max_results * 3:  # fetch 3x so filter has headroom
            break
        url = (f"https://www.profesia.sk/praca/?count_days=30"
               f"&search_anywhere={encoded}&sort_by=relevance&page_num={page}")
        html_bytes = await _fetch_source_html(url)
        if not html_bytes:
            break
        html = ftfy.fix_text(html_bytes.decode("utf-8", errors="replace"))
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("li.list-row")
        if not rows:
            break
        for li in rows:
            job_link = li.select_one("h2 a")
            if not job_link or not job_link.get("href"):
                continue
            job_href = job_link["href"].split("?")[0]
            job_url_full = f"https://www.profesia.sk{job_href}" if job_href.startswith("/") else job_href
            title_el = li.select_one("span.title")
            job_title = (title_el or job_link).get_text(strip=True)
            employer_el = li.select_one("span.employer")
            company_name = employer_el.get_text(strip=True) if employer_el else ""
            if not company_name:
                continue
            slug_m = re.search(r"/praca/([^/]+)/O\d+", job_url_full)
            company_slug = slug_m.group(1) if slug_m else None
            loc_el = li.select_one("span.job-location")
            location_str = (loc_el.get("title") or loc_el.get_text(strip=True)) if loc_el else None
            all_jobs.append({
                "company_name": company_name,
                "company_url": None,
                "url_confidence": None,
                "company_slug": company_slug,
                "ico": None,
                "job_title": job_title,
                "job_url": job_url_full,
                "location": location_str,
                "source_signal": "hiring_sales_rep",
            })

    # Resolution pipeline: scraped → validated_guess → ORSR (for IČO)
    sem = asyncio.Semaphore(5)

    async def _resolve(job: dict) -> None:
        async with sem:
            # Step 1: scraped from profesia .company-info
            url = await asyncio.get_event_loop().run_in_executor(
                None, _fetch_company_url_from_job, job["job_url"]
            )
            if url:
                job["company_url"] = url
                job["url_confidence"] = "scraped"
                return

            # Step 2: validated slug guess
            slug = job.get("company_slug")
            if slug:
                url = await _validate_slug_url(slug)
                if url:
                    job["company_url"] = url
                    job["url_confidence"] = "validated_guess"
                    return

            # Step 3: ORSR by name → at least get IČO; web_url always None from ORSR
            orsr = await asyncio.get_event_loop().run_in_executor(
                None, orsr_search_by_name, job["company_name"]
            )
            if orsr:
                job["ico"] = orsr.get("ico")
                # web_url from ORSR is always None currently — but IČO enables RPO fallback

    await asyncio.gather(*[_resolve(j) for j in all_jobs])
    return all_jobs


@app.post("/api/leads/source/profesia")
async def source_profesia(req: ProfesiaSourceRequest, user=Depends(verify_jwt)):
    """Nájde firmy inzeujúce na profesia.sk (všetky stránky) a vráti ich URL na scrape."""
    keyword = req.keyword.strip()

    # Page 1 also gives total_found count
    encoded = urllib.parse.quote_plus(keyword)
    first_html = await _fetch_source_html(
        f"https://www.profesia.sk/praca/?count_days=30&search_anywhere={encoded}&sort_by=relevance&page_num=1"
    )
    total_found = 0
    if first_html:
        soup0 = BeautifulSoup(first_html.decode("utf-8", errors="replace"), "html.parser")
        for el in soup0.find_all(string=re.compile(r'z\s+\d+\s+pon', re.IGNORECASE)):
            m = re.search(r'z\s+(\d[\d\s]*)\s+pon', el, re.IGNORECASE)
            if m:
                total_found = int(re.sub(r'\D', '', m.group(1)))
                break

    all_jobs = await _scrape_profesia_pages(keyword, req.max_results)
    results, filtered_agencies = _filter_agencies(all_jobs)
    results = results[:req.max_results]

    if not total_found:
        total_found = len(results)

    print(f"[profesia] keyword={keyword!r} pages={len(all_jobs)//20+1} → {len(results)} firiem, {len(filtered_agencies)} agentúr odfiltrovaných")
    return {
        "source": "profesia.sk",
        "keyword": keyword,
        "location": req.location,
        "results": results,
        "total_found": total_found,
        "returned": len(results),
        "filtered_agencies": filtered_agencies,
    }


class HeurekaSourceRequest(BaseModel):
    category_url: str
    max_results: int = 50


@app.post("/api/leads/source/heureka")
async def source_heureka(req: HeurekaSourceRequest, user=Depends(verify_jwt)):
    """Nájde e-shopy v Heureka kategórii."""
    cat_url = req.category_url.strip()
    if not cat_url.startswith("http"):
        cat_url = "https://www.heureka.sk/" + cat_url.lstrip("/")

    # Ensure we use the /obchody/ sub-path which lists shops, not products
    parsed_cat = urlparse(cat_url)
    path = parsed_cat.path.rstrip("/")
    if not path.startswith("/obchody"):
        # /nabytok/ → /obchody/nabytok/
        obchody_url = f"https://www.heureka.sk/obchody{path}/"
    else:
        obchody_url = cat_url

    # Full fallback chain — Heureka has Cloudflare
    text = await fetch_text_with_fallback(obchody_url)
    if not text or len(text) < 500:
        raise HTTPException(status_code=503, detail=f"Heureka nedostupné (Cloudflare?): {obchody_url}")

    soup = BeautifulSoup(text, "html.parser")

    h1_el = soup.select_one("h1")
    category = h1_el.get_text(strip=True) if h1_el else path.strip("/").split("/")[-1]

    results: List[Dict] = []
    seen_domains: set = set()
    filtered_markets: List[str] = []

    for a in soup.find_all("a", href=True):
        if len(results) >= req.max_results:
            break

        href = a["href"]

        # Pattern A: Heureka redirect link with ?url= param
        if "redirect.heureka" in href or "click.heureka" in href:
            qs = urllib.parse.parse_qs(urlparse(href).query)
            href = (qs.get("url") or qs.get("u") or [None])[0]
            if not href:
                continue

        # Only external links
        if not href.startswith("http") or "heureka" in href.lower():
            continue

        p = urlparse(href)
        domain = p.netloc.lower().lstrip("www.")
        if not domain or domain in seen_domains:
            continue

        shop_url = f"{p.scheme}://www.{domain}/"
        shop_name = a.get_text(strip=True) or domain

        if _is_market(shop_name, shop_url):
            if shop_name not in filtered_markets:
                filtered_markets.append(shop_name)
            continue

        seen_domains.add(domain)

        # Rating from nearby element
        parent = a.parent
        rating = None
        if parent:
            r_el = parent.find(class_=re.compile(r"rating|star|score", re.I))
            if r_el:
                r_m = re.search(r"(\d+[.,]\d+)", r_el.get_text())
                if r_m:
                    rating = float(r_m.group(1).replace(",", "."))

        results.append({
            "shop_name": shop_name,
            "shop_url": shop_url,
            "rating": rating,
            "source_signal": "heureka_category_listing",
        })

    print(f"[heureka] {obchody_url} → {len(results)} shopov, {len(filtered_markets)} odfiltrovaných")
    return {
        "source": "heureka.sk",
        "category": category,
        "category_url": obchody_url,
        "results": results,
        "total_found": len(results),
        "returned": len(results),
        "filtered_markets": filtered_markets,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE CHANNELS — E-shopy agregátor + Google Maps + ORSR nové firmy
# ══════════════════════════════════════════════════════════════════════════════

async def _fetch_source_html(url: str) -> bytes:
    """Fallback chain pre source channels — httpx → cloudscraper → scrapling."""
    html = fetch_html_httpx(url)
    if html and not is_garbled_content(extract_text_from_html(html)):
        return html
    html = fetch_html_cloudscraper_with_ua(url)
    if html and not is_garbled_content(extract_text_from_html(html)):
        return html
    html = await fetch_html_scrapling(url)
    if html:
        return html
    return b""


def _check_robots(base_url: str, path: str) -> bool:
    """Vráti True ak je path bezpečná na scrapovanie.
    Python stdlib robotparser nespráva wildcard vzory (/* atp.) — ručný blacklist
    explicitne zakázaných ciest namiesto parsovania robots.txt."""
    # ponytail: manual blocklist — stdlib robotparser fails on wildcard Disallow patterns
    BLOCKED_PREFIXES = {
        "www.pricemania.sk": ["/vyhladavanie/", "/ajaxCall/", "/exit/", "/mobile/", "/m/"],
        "www.ecommerceslovakia.sk": [],
        "www.shoptet.sk": ["/api/", "/_next/"],
    }
    try:
        from urllib.parse import urlparse as _up
        host = _up(base_url).netloc or base_url.split("/")[2]
        blocked = BLOCKED_PREFIXES.get(host, [])
        return not any(path.startswith(b) for b in blocked)
    except Exception:
        return True


def _parse_pricemania(html: bytes, max_results: int = 50) -> list:
    """Vytiahne e-shopy z pricemania kategórie (JS-rendered — best effort)."""
    if not html:
        return []
    soup = BeautifulSoup(html.decode("utf-8", errors="replace"), "html.parser")
    results = []
    seen_domains: set = set()
    # Pattern: <a href="/obchod-detail/{slug}/"> alebo exit linky s názvom obchodu
    for a in soup.find_all("a", href=True):
        if len(results) >= max_results:
            break
        href = a["href"]
        name = a.get_text(strip=True)
        if not name or len(name) < 2:
            continue
        # Priamy odkaz na obchod
        if "/obchod-detail/" in href:
            slug_m = re.search(r"/obchod-detail/([^/]+)/", href)
            slug = slug_m.group(1) if slug_m else None
            shop_url = f"https://www.{slug}.sk" if slug else None
            domain = slug or name.lower().replace(" ", "")
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            if _is_market(name, shop_url or ""):
                continue
            results.append({
                "shop_name": name,
                "shop_url": shop_url,
                "found_in": "pricemania",
                "source_signal": "active_eshop",
            })
    return results


def _parse_ecommerce_sk_slugs(html: bytes) -> list:
    """Vytiahne slugy a názvy z katalóg-eshopov listing stránky."""
    if not html:
        return []
    soup = BeautifulSoup(html.decode("utf-8", errors="replace"), "html.parser")
    results = []
    seen: set = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Pattern: /eshops/{slug}/ (interná stránka)
        m = re.search(r"/eshops/([^/]+)/?$", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        # Vytiahni názov z img alt textu
        img = a.find("img")
        name = ""
        if img:
            alt = img.get("alt", "")
            name = re.sub(r"\s*[-–]\s*(clen|člen|member|E-commerce|Ecommerce).*", "", alt, flags=re.IGNORECASE).strip()
            name = re.sub(r"\s+(logo|icon|img|image)$", "", name, flags=re.IGNORECASE).strip()
        if not name:
            name = slug.replace("-", " ").title()
        results.append({"slug": slug, "name": name, "detail_url": f"https://www.ecommerceslovakia.sk/eshops/{slug}/"})
    return results


def _extract_shop_url_from_detail(html: bytes) -> str | None:
    """Z detail stránky ecommerceslovakia vytiahne URL samotného e-shopu."""
    if not html:
        return None
    SKIP = {"ecommerceslovakia.sk", "facebook.com", "linkedin.com", "youtube.com", "instagram.com", "google.com"}
    soup = BeautifulSoup(html.decode("utf-8", errors="replace"), "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        domain = urlparse(href).netloc.lower().lstrip("www.")
        if any(s in domain for s in SKIP):
            continue
        if domain.endswith(".sk") or domain.endswith(".cz") or domain.endswith(".eu"):
            return href.rstrip("/") + "/"
    return None


async def _parse_ecommerce_sk(html: bytes, max_results: int = 50) -> list:
    """Vytiahne certifikované e-shopy: listing → detail pages pre skutočné URL."""
    slugs = _parse_ecommerce_sk_slugs(html)[:max_results]
    results = []
    for item in slugs:
        detail_html = await _fetch_source_html(item["detail_url"])
        shop_url = _extract_shop_url_from_detail(detail_html)
        if shop_url and _is_market(item["name"], shop_url):
            continue
        results.append({
            "shop_name": item["name"],
            "shop_url": shop_url,
            "found_in": "ecommerce_sk",
            "source_signal": "certified_eshop",
        })
    return results


class EshopsSourceRequest(BaseModel):
    category: str
    max_results: int = 50
    sources: List[str] = ["pricemania", "ecommerce_sk"]


@app.post("/api/leads/source/eshops")
async def source_eshops(req: EshopsSourceRequest, user=Depends(verify_jwt)):
    """Agregátor e-shopov z viacerých katalógov (pricemania, ecommerce_sk; shoptet TODO)."""
    import urllib.parse as _urlparse
    cat_slug = re.sub(r'[^a-z0-9]', '-', req.category.lower().strip()).strip('-')
    results_per_source: dict = {}
    notes: list = []

    if "pricemania" in req.sources:
        ok = _check_robots("https://www.pricemania.sk", f"/obchod-detail/{cat_slug}/")
        if not ok:
            notes.append("pricemania: robots.txt disallow — preskočené")
        else:
            html = await _fetch_source_html(f"https://www.pricemania.sk/obchod-detail/{cat_slug}/")
            items = _parse_pricemania(html, req.max_results)
            results_per_source["pricemania"] = items
            print(f"[eshops] pricemania: {len(items)} shopov")

    if "shoptet" in req.sources:
        notes.append("shoptet: JS-rendered, zatiaľ nepodporované — pridaj Scrapling s JS wait")
        results_per_source["shoptet"] = []

    if "ecommerce_sk" in req.sources:
        ok = _check_robots("https://www.ecommerceslovakia.sk", "/katalog-eshopov/")
        if not ok:
            notes.append("ecommerce_sk: robots.txt disallow — preskočené")
        else:
            html = await _fetch_source_html("https://www.ecommerceslovakia.sk/katalog-eshopov/")
            items = await _parse_ecommerce_sk(html, req.max_results)
            results_per_source["ecommerce_sk"] = items
            print(f"[eshops] ecommerce_sk: {len(items)} shopov")

    # Agregácia + dedup podľa domény
    seen_domains: set = set()
    aggregated: list = []
    filtered_markets: list = []
    for source, items in results_per_source.items():
        for it in items:
            url = it.get("shop_url") or ""
            dom = _domain_of(url) or it.get("shop_name", "").lower()[:20]
            if dom in seen_domains:
                continue
            seen_domains.add(dom)
            aggregated.append(it)

    aggregated = aggregated[:req.max_results]
    sources_used = [s for s in req.sources if s != "shoptet" or results_per_source.get("shoptet")]
    return {
        "source": "eshops_aggregate",
        "category": req.category,
        "sources_used": list(results_per_source.keys()),
        "results": aggregated,
        "total_found": sum(len(v) for v in results_per_source.values()),
        "returned": len(aggregated),
        "deduplicated": len(aggregated),
        "filtered_markets": filtered_markets,
        "notes": notes,
    }


# ── Google Maps (Places API) ──

class MapsSourceRequest(BaseModel):
    keyword: str
    location: str
    max_results: int = 20


@app.post("/api/leads/source/maps")
async def source_maps(req: MapsSourceRequest, user=Depends(verify_jwt)):
    """Nájde lokálne firmy cez Google Places Text Search API."""
    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Google Places API kľúč nie je nastavený — pridaj GOOGLE_PLACES_API_KEY do .env"
        )
    query = f"{req.keyword.strip()} {req.location.strip()}".strip()
    search_url = (
        f"https://maps.googleapis.com/maps/api/place/textsearch/json"
        f"?query={urllib.parse.quote_plus(query)}&key={api_key}&language=sk&region=sk"
    )
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(search_url)
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Google Places API chyba: {e}")

    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        raise HTTPException(status_code=503, detail=f"Google Places chyba: {data.get('status')} — {data.get('error_message', '')}")

    results: list = []
    for place in data.get("results", [])[:req.max_results]:
        website = place.get("website")
        name = place.get("name", "")
        addr = place.get("formatted_address", "")
        rating = place.get("rating")
        results.append({
            "company_name": name,
            "company_url": website,
            "address": addr,
            "rating": rating,
            "place_id": place.get("place_id"),
            "source_signal": "local_business",
        })

    return {
        "source": "google_maps",
        "keyword": req.keyword,
        "location": req.location,
        "results": results,
        "total_found": len(results),
        "returned": len(results),
    }


# ── ORSR nové firmy (experimentálne / TODO) ──

class OrsrNewSourceRequest(BaseModel):
    days_back: int = 90
    region: Optional[str] = None
    legal_form: Optional[str] = None
    max_results: int = 30


@app.post("/api/leads/source/orsr_new")
async def source_orsr_new(req: OrsrNewSourceRequest, user=Depends(verify_jwt)):
    """
    Nové firmy z ORSR/RPO.
    TODO: RPO API (api.statistics.sk/rpo/v1/) nepodporuje filter podľa dátumu cez GET.
    Alternatíva: Obchodný vestník (ov.justice.sk) — vyžaduje parsing PDF/HTML vestníka.
    Tento endpoint je experimentálny a zatiaľ vracia prázdny zoznam.
    """
    # ponytail: stub — RPO API nepodporuje establishedAfter filter, vestník = TODO
    return {
        "source": "orsr_new",
        "status": "not_implemented",
        "message": (
            "RPO API nepodporuje filter podľa dátumu vzniku cez jednoduchý GET. "
            "Alternatívy: (1) Obchodný vestník ov.justice.sk — parsovanie HTML vydaní, "
            "(2) Finstat.sk Premium API — má filter na nové firmy. "
            "Doimplementuj ktorú z týchto stratégií chceš."
        ),
        "days_back": req.days_back,
        "results": [],
        "total_found": 0,
        "returned": 0,
    }


# ======================================================================
# SOURCE AUTO -- orchestrator: source channel -> scrape -> sorted leads
# ======================================================================

class SourceAutoRequest(BaseModel):
    channel: str           # "profesia" | "eshops" | "maps"
    keyword: str = ""
    location: str = ""
    category: str = ""
    sources: List[str] = []
    max_results: int = 10


@app.post("/api/leads/source/auto")
async def source_auto(req: SourceAutoRequest, user=Depends(verify_jwt)):
    """Find companies via channel, scrape each, return scored leads sorted by score DESC."""
    t0 = datetime.datetime.utcnow()

    # 1. Discover companies
    found: list = []
    filtered_agencies: list = []

    if req.channel == "profesia":
        if not req.keyword:
            raise HTTPException(400, "keyword je povinny pre profesia kanal")
        all_jobs = await _scrape_profesia_pages(req.keyword, req.max_results)
        found, filtered_agencies = _filter_agencies(all_jobs)
        found = found[:req.max_results]

    elif req.channel == "eshops":
        if not req.category:
            raise HTTPException(400, "category je povinna pre eshops kanal")
        sources = req.sources or ["pricemania", "ecommerce_sk"]
        cat_slug = re.sub(r'[^a-z0-9]', '-', req.category.lower().strip()).strip('-')
        items: list = []
        if "pricemania" in sources:
            html = await _fetch_source_html(f"https://www.pricemania.sk/obchod-detail/{cat_slug}/")
            items += _parse_pricemania(html, req.max_results)
        if "ecommerce_sk" in sources:
            html = await _fetch_source_html("https://www.ecommerceslovakia.sk/katalog-eshopov/")
            items += await _parse_ecommerce_sk(html, req.max_results)
        found = [{"company_name": it.get("shop_name", ""), "company_url": it.get("shop_url"),
                   "source_signal": it.get("source_signal")} for it in items][:req.max_results]

    elif req.channel == "maps":
        if not req.keyword:
            raise HTTPException(400, "keyword je povinny pre maps kanal")
        api_key = os.getenv("GOOGLE_PLACES_API_KEY")
        if not api_key:
            raise HTTPException(503, "GOOGLE_PLACES_API_KEY nie je nastaveny")
        query = f"{req.keyword} {req.location}".strip()
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"https://maps.googleapis.com/maps/api/place/textsearch/json"
                f"?query={urllib.parse.quote_plus(query)}&key={api_key}&language=sk&region=sk"
            )
        data = resp.json()
        for place in data.get("results", [])[:req.max_results]:
            found.append({"company_name": place.get("name", ""),
                           "company_url": place.get("website"),
                           "source_signal": "local_business"})

    else:
        raise HTTPException(400, f"Nezname kanaly: {req.channel}")

    # 2. Scrape each company; registry-only fallback for IČO-only
    leads: list = []
    skipped: list = []
    for company in found:
        url = company.get("company_url") or ""
        if not url:
            if company.get("ico"):
                reg_lead = await _create_registry_only_lead(company)
                if reg_lead:
                    leads.append(reg_lead)
                    continue
            skipped.append({"company": company.get("company_name"), "reason": "ziadna URL"})
            continue
        try:
            lead = await _do_scrape(url)
            lead["source_signal"] = company.get("source_signal")
            lead["source_channel"] = req.channel
            leads.append(lead)
        except Exception as e:
            # If scrape failed, try ORSR by name to get IČO → registry-only fallback
            if not company.get("ico"):
                loop = asyncio.get_event_loop()
                orsr = await loop.run_in_executor(None, orsr_search_by_name, company.get("company_name", ""))
                if orsr:
                    company["ico"] = orsr.get("ico")
            if company.get("ico"):
                reg_lead = await _create_registry_only_lead(company)
                if reg_lead:
                    leads.append(reg_lead)
                    continue
            skipped.append({"company": company.get("company_name"), "url": url, "reason": str(e)[:120]})

    # 3. Sort by score DESC
    leads.sort(key=lambda x: x.get("score", 0), reverse=True)

    elapsed = (datetime.datetime.utcnow() - t0).total_seconds()
    print(f"[source_auto] channel={req.channel!r} found={len(found)} scraped={len(leads)} skipped={len(skipped)} elapsed={elapsed:.0f}s")
    return {
        "channel": req.channel,
        "found_companies": len(found),
        "scraped_leads": len(leads),
        "skipped": skipped,
        "filtered_agencies": filtered_agencies,
        "elapsed_seconds": round(elapsed),
        "leads": leads,
    }
