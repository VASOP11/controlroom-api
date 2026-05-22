import os
import uuid
import datetime
import re
import json
from typing import List, Optional
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
import cloudscraper

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# --- SQLAlchemy modely ---
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
                        {"name": "in_target_vertical", "points": 20, "condition": "lead_data.get('vertical') in ['Home & Garden', 'Beauty', 'Pet', 'Sport', 'Auto-moto']"}
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

# 🔥 PRIDANÉ CORS (pre Appsmith Cloud)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Počas vývoja necháme otvorené, neskôr obmedzíš
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

# ---- Health check ----
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

# ---- Email templates endpoints ----
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

# ---- WEB SCRAPING ENDPOINT (používa cloudscraper a BeautifulSoup) ----
class ScrapeRequest(BaseModel):
    url: str

@app.post("/api/leads/scrape")
async def scrape_lead(req: ScrapeRequest, user=Depends(verify_jwt)):
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, timeout=30)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Nepodarilo sa načítať stránku (status {response.status_code})")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Názov firmy
        title = soup.title.string if soup.title else ""
        meta_title = soup.find('meta', attrs={'name': 'application-name'})
        meta_title = meta_title['content'] if meta_title else ""
        primary_identifier = meta_title or title or url.split("//")[-1].split("/")[0]
        
        # Email
        email = None
        mailto = soup.find('a', href=lambda x: x and x.startswith('mailto:'))
        if mailto:
            email = mailto['href'].replace('mailto:', '')
        if not email:
            email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', response.text)
            if email_match:
                email = email_match.group(0)
        
        # Telefón
        phone = None
        tel = soup.find('a', href=lambda x: x and x.startswith('tel:'))
        if tel:
            phone = tel['href'].replace('tel:', '')
        if not phone:
            phone_match = re.search(r'(\+421|\+420|0)\d{9,12}', response.text)
            if phone_match:
                phone = phone_match.group(0)
        
        # Meno osoby
        name = None
        if phone:
            pos = response.text.find(phone)
            if pos != -1:
                surrounding = response.text[max(0, pos-100):min(len(response.text), pos+100)]
                name_match = re.search(r'([A-Z][a-z]+ [A-Z][a-z]+)', surrounding)
                if name_match:
                    name = name_match.group(1)
        if not name:
            kontakt = soup.find(text=re.compile("Kontakt|Kontakty|Manažér|Ředitel", re.IGNORECASE))
            if kontakt:
                parent = kontakt.find_parent()
                if parent:
                    name_match = re.search(r'([A-Z][a-z]+ [A-Z][a-z]+)', parent.get_text())
                    if name_match:
                        name = name_match.group(1)
        
        # Vertikála
        body_text = soup.get_text().lower()
        vertical = "Unknown"
        if any(w in body_text for w in ["home garden", "zahrada", "nábytok", "doplnky"]):
            vertical = "Home & Garden"
        elif any(w in body_text for w in ["beauty", "kozmetika", "parfum"]):
            vertical = "Beauty & Personal Care"
        elif any(w in body_text for w in ["pet", "zvieratá", "pes", "mačka"]):
            vertical = "Pet Supplies"
        
        # Body za kontakt
        has_phone = bool(phone)
        has_email = bool(email)
        has_name = bool(name and len(name.split()) >= 2)
        is_direct_email = False
        if has_email and email:
            local = email.split('@')[0].lower()
            if local not in ['info', 'obchod', 'sales', 'support', 'contact']:
                is_direct_email = True
        if has_name and has_phone and is_direct_email:
            points = 45
            level = 3
        elif has_name and has_phone:
            points = 30
            level = 2
        elif has_phone or has_email:
            points = 15
            level = 1
        else:
            points = 0
            level = 0
        
        # Priprav dáta pre leada
        lead_data = {
            "primary_identifier": primary_identifier,
            "vertical": vertical,
            "contact_channels": {},
            "platform_presence": {},
            "lead_metadata": {
                "scraped_url": url,
                "scraped_at": datetime.datetime.utcnow().isoformat(),
                "scraped_email": email,
                "scraped_phone": phone,
                "contact_name": name,
                "contact_level": level
            }
        }
        if email:
            lead_data["contact_channels"]["email"] = email
        if phone:
            lead_data["contact_channels"]["phone"] = phone
        
        # Získaj organizačnú konfiguráciu
        org_id = 1
        async with async_session() as session:
            result = await session.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == org_id))
            org_config = result.scalar_one_or_none()
            if not org_config:
                raise HTTPException(status_code=404, detail="Organization config not found")
        
        # Skóre
        rule_score = evaluate_lead(lead_data, org_config.scoring_rules)
        final_score = rule_score + points
        final_score = max(0, min(100, final_score))
        thresholds = org_config.tier_thresholds
        if final_score >= thresholds["HOT"]:
            tier = "HOT"
        elif final_score >= thresholds["WARM"]:
            tier = "WARM"
        elif final_score >= thresholds["COOL"]:
            tier = "COOL"
        else:
            tier = "DEAD"
        
        # Ulož alebo aktualizuj (merge podľa URL)
        async with async_session() as session:
            stmt = select(Lead).where(Lead.lead_metadata["url"].astext == url)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                stmt = select(Lead).where(Lead.primary_identifier == primary_identifier)
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
                    "primary_identifier": existing.primary_identifier,
                    "score": final_score,
                    "tier": tier,
                    "extracted": {"email": email, "phone": phone, "contact_name": name, "vertical": vertical}
                }
            else:
                new_lead = Lead(
                    lead_id=str(uuid.uuid4()),
                    primary_identifier=primary_identifier,
                    vertical=vertical,
                    platform_presence=lead_data.get("platform_presence", {}),
                    value_indicators=lead_data.get("value_indicators", {}),
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
                    "primary_identifier": primary_identifier,
                    "score": final_score,
                    "tier": tier,
                    "extracted": {"email": email, "phone": phone, "contact_name": name, "vertical": vertical}
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping error: {str(e)}")