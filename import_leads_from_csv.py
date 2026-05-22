import csv
import requests

url = "http://localhost:8000/api/leads"
headers = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

with open("leads.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        nazov = row.get("nazov firmy", "").strip()
        if not nazov:
            continue
        lead_data = {
            "primary_identifier": nazov,
            "vertical": row.get("segment", "").strip(),
            "platform_presence": {"platforms": [p.strip() for p in row.get("platform", "").split(",") if p.strip()]} if row.get("platform") else {},
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
        payload = {"lead_data": lead_data}
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            print(f"Lead {nazov} pridaný")
        else:
            print(f"Chyba pri {nazov}: {response.status_code} - {response.text}")