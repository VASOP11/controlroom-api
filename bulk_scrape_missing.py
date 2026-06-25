import requests
import time
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Nahraj premenné z .env súboru
load_dotenv()

# Získaj a uprav DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

# 1. Odstráň parameter '?sslmode=require', ktorý robí problém
DATABASE_URL = DATABASE_URL.split("?")[0]

# 2. Nahraď asynchrónny driver 'asyncpg' za 'psycopg2'
if "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

# 3. Pridaj späť parameter pre SSL, ktorý psycopg2 zvládne (voliteľné, ale odporúčané)
#    Toto zabezpečí, že spojenie bude stále šifrované.
if "?" not in DATABASE_URL:
    DATABASE_URL += "?sslmode=require"

# Vytvor inžinier pre pripojenie k databáze
engine = create_engine(DATABASE_URL)

API_URL = "https://controlroom-api.onrender.com/api/leads/scrape"
HEADERS = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

def get_leads_without_name():
    """Získa ID a URL leadov, ktoré nemajú meno, ale majú URL."""
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT id, primary_url FROM leads WHERE (primary_identifier IS NULL OR primary_identifier = 'Neznámy' OR primary_identifier = '?') AND primary_url IS NOT NULL AND primary_url != ''")
        )
        return result.fetchall()

def scrape_lead(url):
    """Odošle URL na scrapovací endpoint."""
    try:
        resp = requests.post(API_URL, json={"url": url}, headers=HEADERS, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✓ Scrapnutý: {url} → {data.get('primary_identifier', '?')} (skóre {data.get('score', '?')})")
            return True
        else:
            print(f"✗ Chyba pri {url}: {resp.status_code} - {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"✗ Výnimka pri {url}: {e}")
        return False

def main():
    leads = get_leads_without_name()
    print(f"Nájdených {len(leads)} leadov na scrapovanie.")
    for idx, (lead_id, url) in enumerate(leads, 1):
        print(f"[{idx}/{len(leads)}] Spracovávam {url}...")
        scrape_lead(url)
        time.sleep(1)  # oneskorenie, aby sme nepreťažili backend
    print("Hotovo.")

if __name__ == "__main__":
    main()