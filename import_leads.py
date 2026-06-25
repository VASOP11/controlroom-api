import csv
import requests
import os

# Tvoja URL backendu na Renderi
API_URL = "https://controlroom-api.onrender.com/api/leads"
HEADERS = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

# Názvy stĺpcov v tvojom CSV (prispôsob podľa skutočnosti)
MAPPING = {
    "nazov firmy": "primary_identifier",
    "url": "primary_url",
    "segment": "vertical",
    "email": "email",
    "phone": "phone",
    "contact_person": "contact_person",
    "role": "role",
    "mesto": "city",
    "platform": "platform",
    "notes": "notes",
    "country": "country",
    "added_at": "added_at"
}

def import_leads(csv_path):
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lead_data = {
                "primary_identifier": row.get("nazov firmy") or row.get("primary_identifier", "Neznámy"),
                "primary_url": row.get("url") or row.get("primary_url", ""),
                "vertical": row.get("segment") or row.get("vertical", ""),
                "lead_metadata": {}
            }
            # Presun zvyšných údajov do lead_metadata (JSON)
            for key, val in row.items():
                if key not in ["nazov firmy", "url", "segment"] and val:
                    lead_data["lead_metadata"][key] = val
            # Pridanie email a phone do contact_channels (ak existujú)
            if row.get("email"):
                lead_data["contact_channels"] = {"email": row["email"]}
            if row.get("phone"):
                if "contact_channels" not in lead_data:
                    lead_data["contact_channels"] = {}
                lead_data["contact_channels"]["phone"] = row["phone"]
            # Pošli POST request
            try:
                resp = requests.post(API_URL, json={"lead_data": lead_data}, headers=HEADERS)
                if resp.status_code == 200:
                    print(f"✓ Importovaný: {lead_data['primary_identifier']}")
                else:
                    print(f"✗ Chyba pri {lead_data['primary_identifier']}: {resp.status_code} - {resp.text}")
            except Exception as e:
                print(f"✗ Výnimka: {e}")

if __name__ == "__main__":
    # Cesta k tvojmu CSV súboru
    csv_file = input("Zadaj cestu k CSV súboru (napr. C:\\Users\\vizva\\Desktop\\leads.csv): ")
    if os.path.exists(csv_file):
        import_leads(csv_file)
    else:
        print("Súbor neexistuje.")