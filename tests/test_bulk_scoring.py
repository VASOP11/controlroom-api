import os
import pytest
from fastapi.testclient import TestClient
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from the .env file
print("DATABASE_URL:", os.getenv("DATABASE_URL"))  # Debug statement for verification
from main import app  # Ensure the app is imported correctly

client = TestClient(app)

def test_bulk_score_async_valid():
    response = client.post("/api/leads/score/bulk/async", json={
        "leads": [
            {"lead_id": "some_lead_id", "lead_data": {"key": "value1"}},
            {"lead_id": "some_lead_id_2", "lead_data": {"key": "value2"}}
        ],
        "org_id": "1"  # Provided string org_id for tests
    }, headers={"Authorization": "Bearer <provide-valid-token-here>"})  # Please replace with a valid token
    assert response.status_code == 200
    assert response.json()['status'] == 'pending'  # Check for pending status

def test_bulk_score_async_missing_leads():
    response = client.post("/api/leads/score/bulk/async", json={
        "org_id": "1"  # Provided string org_id for tests
    })
    assert response.status_code == 400
    assert response.json()['detail'] == "Missing leads or org_id"

def test_bulk_score_async_missing_org_id():
    response = client.post("/api/leads/score/bulk/async", json={
        "leads": [
            {"lead_id": "some_lead_id", "lead_data": {"key": "value1"}}
        ]
    })
    assert response.status_code == 400
    assert response.json()['detail'] == "Missing leads or org_id"