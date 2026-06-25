"""Test /api/leads/candidates endpoint with known URLs."""
import asyncio
import httpx
import json
import sys

URLS = [
    "https://www.minilove.sk/",
    "https://www.isexshop.sk/",
    "https://www.sedooz.sk/",
    "https://www.lavanda.sk/",
    "https://www.mojsvet.eu/",
    "https://www.kondomshop.sk/",
]

API_BASE = "http://localhost:8000"
TOKEN = "test-token"


async def test_one(client: httpx.AsyncClient, url: str) -> dict:
    r = await client.post(
        f"{API_BASE}/api/leads/candidates",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"url": url},
    )
    if r.status_code != 200:
        print(f"\n=== {url} === ERROR {r.status_code}")
        print(r.text[:500])
        return {}
    return r.json()


async def main():
    urls = URLS
    if len(sys.argv) > 1:
        urls = [sys.argv[1]]

    async with httpx.AsyncClient(timeout=120) as c:
        for url in urls:
            d = await test_one(c, url)
            if not d:
                continue

            print(f"\n{'='*60}")
            print(f"  {url}")
            print(f"{'='*60}")
            print(f"  Firma:       {d.get('firma')}")
            print(f"  Jurisdiction: {d.get('jurisdiction')}")
            print(f"  ICO:         {d.get('ico')}")

            reg = d.get("registry", {})
            print(f"  Registry:    source={reg.get('source')}, ok={reg.get('lookup_ok')}")
            konatelia = reg.get("konatelia", [])
            if konatelia:
                print(f"  Konatelia:   {[k['meno'] for k in konatelia]}")
            else:
                print(f"  Konatelia:   (none)")

            phones = d.get("phones", [])
            print(f"  Phones ({len(phones)}):")
            for p in phones[:5]:
                print(f"    {p['cislo']:20s}  typ={p['typ_pravdepodobne']:10s}  "
                      f"blizke_meno={p.get('blizke_meno') or '-':20s}  "
                      f"dist={p.get('vzdialenost_od_konatela') or '-'}")

            emails = d.get("emails", [])
            print(f"  Emails ({len(emails)}):")
            for e in emails[:5]:
                print(f"    {e['email']:35s}  typ={e['typ_pravdepodobne']}")

            kandidati = d.get("kandidati_meno", [])
            print(f"  Kandidati meno ({len(kandidati)}):")
            for k in kandidati[:5]:
                print(f"    {k['meno']:25s}  rola={k.get('rola') or '-':15s}  "
                      f"zdroj={k['zdroj']:20s}  conf={k['confidence']}")

            warnings = d.get("scrape_warnings", [])
            if warnings:
                print(f"  Warnings: {warnings}")

            # Acceptance checks
            url_lower = url.lower()
            if "minilove" in url_lower:
                _check("minilove: registry has konatel", bool(konatelia))
                _check("minilove: has phones", len(phones) >= 1)
            elif "mojsvet" in url_lower:
                bad_names = {"Nové Mesto", "Nove Mesto", "nove mesto"}
                found_bad = any(k["meno"] in bad_names for k in kandidati)
                _check("mojsvet: 'Nove Mesto' NOT in kandidati", not found_bad)
            elif "kondomshop" in url_lower:
                packeta_in = any("packeta" in k["meno"].lower() for k in kandidati)
                _check("kondomshop: 'Packeta' NOT in kandidati_meno", not packeta_in)


def _check(label: str, ok: bool):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}")


if __name__ == "__main__":
    asyncio.run(main())
