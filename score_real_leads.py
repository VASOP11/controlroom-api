import csv
import requests
import json
from collections import Counter

url = "http://localhost:8000/api/leads/score/bulk"
headers = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

# Načítaj CSV
leads = []
with open("leads.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        nazov = row.get("nazov firmy", "").strip()
        if not nazov:
            continue
        
        # Priprav lead_data
        lead_data = {
            "primary_identifier": nazov,
            "vertical": row.get("segment", "").strip(),
            "platform_presence": {
                "platforms": [p.strip() for p in row.get("platform", "").split(",") if p.strip()]
            } if row.get("platform") else {},
            "value_indicators": {},  # nemáš, necháme prázdne
            "engagement_signals": {},
            "differentiation_signals": {},
            "risk_signals": {},
            "lead_metadata": {
                "url": row.get("url", ""),
                "mesto": row.get("mesto", ""),
                "contact_person": row.get("contact_person", ""),
                "role": row.get("role", ""),
                "email": row.get("email", ""),
                "phone": row.get("phone", ""),
                "notes": row.get("notes", ""),
                "country": row.get("country", "")
            }
        }
        
        leads.append({
            "lead_id": str(i+1),
            "lead_data": lead_data
        })

# Bulk scoring (max 1000)
payload = {"leads": leads}
response = requests.post(url, json=payload, headers=headers)

if response.status_code == 200:
    results = response.json()["results"]
    
    # Spočítaj tiers
    tiers = Counter(r["tier"] for r in results)
    print("Výsledky scoringu:")
    print(f"HOT: {tiers.get('HOT', 0)}")
    print(f"WARM: {tiers.get('WARM', 0)}")
    print(f"COOL: {tiers.get('COOL', 0)}")
    print(f"DEAD: {tiers.get('DEAD', 0)}")
    
    # Ulož výsledky do CSV
    with open("results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["lead_id", "nazov_firmy", "score", "tier", "rule_score", "ai_adjustment"])
        for r in results:
            writer.writerow([r["lead_id"], leads[int(r["lead_id"])-1]["lead_data"]["primary_identifier"], r["final_score"], r["tier"], r["rule_score"], r.get("ai_adjustment", "")])
    print("\nVýsledky uložené do results.csv")
else:
    print(f"Chyba: {response.status_code} - {response.text}")