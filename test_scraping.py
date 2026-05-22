import csv
import requests
import time

url = "http://localhost:8000/api/leads/scrape"
headers = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

with open("leads.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        web_url = row.get("url", "").strip()
        if not web_url:
            continue
        # Odstráni prázdne alebo neplatné URL
        if not web_url.startswith(("http://", "https://")):
            web_url = "https://" + web_url
        
        print(f"Scrapujem: {web_url}")
        payload = {"url": web_url}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            if response.status_code == 200:
                data = response.json()
                print(f"  -> Lead {data['primary_identifier']} (skóre {data['score']}, tier {data['tier']})")
                print(f"     Extrahované: email={data['extracted']['email']}, phone={data['extracted']['phone']}, vertical={data['extracted']['vertical']}")
            else:
                print(f"  -> Chyba: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"  -> Výnimka: {e}")
        time.sleep(2)  # pauza 2 sekundy medzi požiadavkami (aby sme nezahlili server)