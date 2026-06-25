import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from main import _scrape_all_pages, associate_persons_with_roles

# 4 weby kde predtým scraper nenašiel meno (NIE V TEXTE)
# Po FIX 1 (anchor discovery) + FIX 2 (PDF) + FIX 3 (subdomain) by mali nájsť meno

TESTS = [
    ("https://www.pomocnik.sk/",     "Buchanec",    "Ján Buchanec"),
    ("https://dekorbymirka.sk",      "Baránková",   "Miroslava Baránková"),
    ("https://eshop.casca.sk/",      "Stuška",      "Jozef Stuška"),
    ("https://www.drug-store.sk/",   "Kováčiková",  "Jana Kováčiková"),
]

async def main():
    correct = 0
    for url, surname, gt_full in TESTS:
        domain = url.split("//")[1].split("/")[0].replace("www.", "")
        print(f"\n{'─'*60}")
        print(f"🌐 {domain}  ({url})")

        result = await _scrape_all_pages(url)
        combined = result.get("text", "") if isinstance(result, dict) else result[0]

        in_text = surname.lower() in combined.lower()
        osoby = associate_persons_with_roles(combined)
        found = any(surname.lower() in o.get("meno", "").lower() for o in osoby)

        if found:
            correct += 1
            o = next(x for x in osoby if surname.lower() in x.get("meno", "").lower())
            print(f"✅ {domain}: {gt_full} | rola: {o.get('rola')} | conf={o.get('confidence')}")
        elif in_text:
            print(f"❌ {domain}: meno JE V TEXTE ale associate ho nenašiel")
            top3 = [(x.get('meno'), x.get('rola'), x.get('confidence')) for x in osoby[:3]]
            print(f"   Top 3 osoby: {top3}")
            # Ukáž kontext kde sa nachádza meno
            idx = combined.lower().find(surname.lower())
            if idx >= 0:
                print(f"   Kontext: ...{combined[max(0, idx-60):idx+80]}...")
        else:
            print(f"⚫ {domain}: meno NIE V TEXTE (ani po anchor discovery)")
            print(f"   Combined text length: {len(combined)}")
            # Ukáž aké URL boli stiahnuté (hľadaj PDF/VOP v debug výstupe)

    print(f"\n{'='*60}")
    print(f"{correct}/{len(TESTS)} správnych")
    print(f"{'='*60}")

asyncio.run(main())
