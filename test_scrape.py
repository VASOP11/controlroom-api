"""
Test scraping cez nasadený debug endpoint na Renderi.
Postupne zavolá /api/debug/scrape pre každú URL a vypíše tabuľku výsledkov.
Na konci uloží aj scrape_results.csv.
"""
import requests
import csv
import sys
import time

API_BASE = "https://controlroom-api.onrender.com"
ENDPOINT = f"{API_BASE}/api/debug/scrape"
HEADERS = {
    "Authorization": "Bearer test-token",
    "Content-Type": "application/json"
}
TIMEOUT = 300  # sekúnd — Playwright fallback potrebuje viac času

URLS = [
    "https://www.indarceky.sk/",
    "https://www.stylin.sk/",
    "https://www.zeniqo.sk/",
    "https://www.domoss.sk/",
    "https://www.fgym.sk/",
    "https://www.velkykosik.cz/",
    "https://ema-elektro.sk/",
    "https://lomax.sk/",
    "https://www.zuriel.cz/",
    "https://www.fermatshop.sk/",
]

COLUMNS = [
    "url",
    "primary_identifier",
    "contact_name",
    "role",
    "email",
    "phone",
    "contact_points",
    "direct_personal_email",
    "reasoning",
]


def scrape_one(url: str) -> dict:
    """Zavolá debug endpoint pre jednu URL a vráti spracovaný riadok."""
    row = {c: "" for c in COLUMNS}
    row["url"] = url
    try:
        resp = requests.post(ENDPOINT, json={"url": url}, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code != 200:
            row["primary_identifier"] = f"HTTP {resp.status_code}"
            return row
        data = resp.json()

        ai = data.get("ai_extracted") or {}
        fb = data.get("regex_fallback") or {}
        sc = data.get("contact_scoring") or {}

        row["primary_identifier"] = ai.get("primary_identifier") or ""
        row["contact_name"] = ai.get("contact_name") or ""
        row["role"] = ai.get("role") or ""
        row["email"] = ai.get("email") or fb.get("email") or ""
        row["phone"] = ai.get("phone") or fb.get("phone") or ""
        row["contact_points"] = sc.get("contact_points", "")
        row["direct_personal_email"] = sc.get("direct_personal_email", "")
        row["reasoning"] = ai.get("reasoning") or ""

    except requests.exceptions.Timeout:
        row["primary_identifier"] = "TIMEOUT"
    except Exception as e:
        row["primary_identifier"] = f"ERROR: {e}"
    return row


def print_row(i: int, row: dict):
    """Vypíše jeden riadok prehľadne."""
    print(f"\n{'='*70}")
    print(f"  [{i}/{len(URLS)}]  {row['url']}")
    print(f"{'='*70}")
    print(f"  Firma:          {row['primary_identifier']}")
    print(f"  Kontakt:        {row['contact_name']}")
    print(f"  Rola:           {row['role']}")
    print(f"  Email:          {row['email']}")
    print(f"  Telefón:        {row['phone']}")
    print(f"  Body kontaktu:  {row['contact_points']}")
    print(f"  Priamy email:   {row['direct_personal_email']}")
    print(f"  Reasoning:      {row['reasoning']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Scraping {len(URLS)} URL cez {ENDPOINT}")
    print(f"Timeout na request: {TIMEOUT}s\n")

    # Wake-up ping (Render free tier cold start)
    print("Ping health check (cold-start wake-up)...", end=" ", flush=True)
    try:
        r = requests.get(f"{API_BASE}/health", timeout=90)
        print(f"OK ({r.status_code})")
    except Exception as e:
        print(f"WARN: {e} — pokračujem aj tak")

    results = []
    total_start = time.time()
    for i, url in enumerate(URLS, 1):
        print(f"\n>>> [{i}/{len(URLS)}] Scrapujem {url} ...", flush=True)
        t0 = time.time()
        row = scrape_one(url)
        elapsed = time.time() - t0
        print(f"    hotovo za {elapsed:.1f}s", flush=True)
        print_row(i, row)
        results.append(row)
    total_elapsed = time.time() - total_start
    print(f"\nTOTAL TEST TIME: {total_elapsed:.1f}s")

    # CSV export
    csv_path = "scrape_results_v4.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(results)
    print(f"\n{'='*70}")
    print(f"Hotovo! Výsledky uložené do {csv_path}")

    # Súhrnná tabuľka
    print(f"\n{'='*70}")
    print(f"{'URL':<35} {'Firma':<20} {'Email':<30} {'Tel':<18} {'Body':>4} {'Priamy':>6}")
    print("-" * 135)
    for r in results:
        domain = r["url"].replace("https://","").replace("http://","").rstrip("/")[:33]
        firma = (r["primary_identifier"] or "")[:18]
        email = (r["email"] or "")[:28]
        tel = (r["phone"] or "")[:16]
        body = str(r["contact_points"])
        priamy = str(r["direct_personal_email"])
        print(f"{domain:<35} {firma:<20} {email:<30} {tel:<18} {body:>4} {priamy:>6}")


if __name__ == "__main__":
    main()
