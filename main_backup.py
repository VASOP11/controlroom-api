import os 
import asyncpg 
from fastapi import FastAPI, Depends, HTTPException 
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials 
from jose import jwt, JWTError 
from pydantic import BaseModel 
from dotenv import load_dotenv 
 
load_dotenv() 
 
app = FastAPI(title="ControlRoom Scoring API") 
security = HTTPBearer() 
 
SECRET = os.getenv("JWT_SECRET", "test-secret-do-not-use-in-prod") 
 
def verify_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)): 
    token = credentials.credentials 
    if token == "test-token": 
        return {"sub": "org_1"} 
    raise HTTPException(status_code=403, detail="Invalid token") 
 
@app.get("/health") 
def health(): 
    return {"status": "ok"} 
 
@app.get("/protected") 
def protected(user = Depends(verify_jwt)): 
    return {"message": "Authenticated", "user": user} 
 
class LeadScoreRequest(BaseModel): 
    lead_data: dict 
    org_config: dict 
 
@app.post("/score") 
async def score_lead(request: LeadScoreRequest, user = Depends(verify_jwt)): 
    return {"score": 75, "tier": "WARM", "explanation": "Mock scoring"} 
 
class OpenAIChatRequest(BaseModel): 
    messages: list 
    model: str = "gpt-4o-mini" 
 
@app.post("/openai/chat") 
async def chat(request: OpenAIChatRequest, user = Depends(verify_jwt)): 
    import httpx 
    openai_endpoint = os.getenv("OPENAI_ENDPOINT") 
    openai_key = os.getenv("OPENAI_API_KEY") 
    if not openai_endpoint or not openai_key: 
        raise HTTPException(status_code=500, detail="OpenAI not configured") 
    headers = {"api-key": openai_key, "Content-Type": "application/json"} 
    url = f"{openai_endpoint}/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-06-01" 
    async with httpx.AsyncClient() as client: 
        response = await client.post(url, json={"messages": request.messages, "model": request.model}, headers=headers, timeout=30) 
    return response.json() 
