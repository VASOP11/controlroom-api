import asyncio
import sys

# Fix Windows terminal encoding (scraper prints emoji → cp1250 crash inak)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from main import _scrape_all_pages, associate_persons_with_roles


async def main():
    r = await _scrape_all_pages("https://www.minilove.sk")
    osoby = associate_persons_with_roles(r["text"])
    erika = next((o for o in osoby if "Erika" in o["meno"]), None)
    assert erika, f"Erika not found. osoby={osoby}"
    assert "Blíziková" in erika["meno"], f"Wrong name: {erika['meno']}"
    assert any(k in (erika["rola"] or "").lower() for k in ["konateľ", "majiteľ", "konatel", "majitel"]), \
        f"Wrong role: {erika['rola']}"
    assert erika["confidence"] >= 5, f"Low confidence: {erika['confidence']}"
    assert erika.get("telefon_osoby") and "903 928 140" in erika["telefon_osoby"], \
        f"Phone not associated: {erika.get('telefon_osoby')}"
    print("PASS")
    print(f"  meno      = {erika['meno']}")
    print(f"  rola      = {erika['rola']} (LVL{erika['rola_level']})")
    print(f"  confidence= {erika['confidence']}")
    print(f"  telefon   = {erika['telefon_osoby']}")


asyncio.run(main())
