import csv
import requests
import time
import os

API_URL = "https://controlroom-api.onrender.com/api/leads/scrape"
HEADERS = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}

def scrape_url(url):
    try:
        resp = requests.post(API_URL, json={"url": url}, headers=HEADERS, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✓ {url} → {data.get('primary_identifier', '?')} (skóre {data.get('score', '?')})")
            return True
        else:
            print(f"✗ Chyba pri {url}: {resp.status_code} - {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"✗ Výnimka pri {url}: {e}")
        return False

def main():
    csv_path = input("Zadaj cestu k CSV súboru (napr. leads.csv): ").strip()
    if not os.path.exists(csv_path):
        print(f"Súbor {csv_path} neexistuje.")
        return
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Skús nájsť stĺpec s URL
        url_column = None
        for col in ["primary_url", "url", "web", "website"]:
            if col in reader.fieldnames:
                url_column = col
                break
        if not url_column:
            print("V CSV nebol nájdený stĺpec s URL (primary_url, url, web, website).")
            return
        
        urls = [row[url_column] for row in reader if row[url_column].strip()]
        print(f"Nájdených {len(urls)} URL na scrapovanie.")
        
        for idx, url in enumerate(urls, 1):
            print(f"[{idx}/{len(urls)}] Spracovávam {url}...")
            scrape_url(url)
            time.sleep(1)  # oneskorenie
    print("Hotovo.")

if __name__ == "__main__":
    main()