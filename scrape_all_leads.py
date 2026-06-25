import requests
import time
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

# Odstránime parameter sslmode (psycopg2 ho neznáša)
DATABASE_URL = DATABASE_URL.split("?")[0]
if "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")
# Ak chceš SSL, pridaj parameter inak (ale psycopg2 má default)
engine = create_engine(DATABASE_URL)

API_URL = "https://controlroom-api.onrender.com/api/leads/scrape"
HEADERS = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

def get_leads_with_url():
    with engine.connect() as conn:
        # Zoberie leady, ktoré majú v lead_metadata->'scraped_url' nejakú hodnotu
        result = conn.execute(
            text("""
                SELECT id, lead_metadata->>'scraped_url' as url
                FROM leads 
                WHERE lead_metadata->>'scraped_url' IS NOT NULL
                AND lead_metadata->>'scraped_url' != ''
            """)
        )
        return result.fetchall()

def scrape_lead(url):
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
    leads = get_leads_with_url()
    print(f"Nájdených {len(leads)} leadov s URL na scrapovanie.")
    for idx, (lead_id, url) in enumerate(leads, 1):
        print(f"[{idx}/{len(leads)}] Spracovávam {url}...")
        scrape_lead(url)
        time.sleep(1)
    print("Hotovo.")

if __name__ == "__main__":
    main()