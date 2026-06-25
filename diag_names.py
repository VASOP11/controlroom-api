import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from main import _scrape_all_pages, associate_persons_with_roles

TESTS = [
    ("https://www.pomocnik.sk/",         "Buchanec",     "Ján Buchanec"),
    ("https://www.pro-salony.cz/",       "Klimek",       "Ján Klimek"),
    ("https://www.ajsi.sk/",             "Flaškár",      "Dávid Flaškár"),
    ("https://www.bioruza.sk/",          "Conev",        "Radoslav Conev"),
    ("https://dekorbymirka.sk",          "Baránková",    "Miroslava Baránková"),
    ("https://eshop.casca.sk/",          "Stuška",       "Jozef Stuška"),
    ("https://www.drug-store.sk/",       "Kováčiková",   "Jana Kováčiková"),
    ("https://www.ludovka.eu/",          "Rozental",     "Sandra Rozental"),
    ("https://www.ruzovakozmetika.sk/",  "Janota",       "Martin Janota"),
    ("https://www.skinlovers.sk/",       "Gašp",         "Natália Gašpiriková"),
    ("https://www.svetkadernictvi.cz/",  "Kunčar",       "Jiří Kunčar"),
    ("https://www.tapka.sk/",            "Saukuličová",  "Michaela Saukuličová"),
]

async def main():
    opravene = 0
    nie_v_texte = 0
    stale_chyba = 0

    for url, surname, gt_full in TESTS:
        domain = url.split("//")[1].split("/")[0].replace("www.","")
        result = await _scrape_all_pages(url)
        combined = result.get("text","") if isinstance(result,dict) else result[0]

        in_text = surname.lower() in combined.lower()
        osoby = associate_persons_with_roles(combined)
        mena = [o.get("meno","") for o in osoby]
        found = any(surname.lower() in m.lower() for m in mena)

        if found:
            rola = next((o.get("rola") for o in osoby if surname.lower() in o.get("meno","").lower()), None)
            print(f"✅ {domain}: OPRAVENÉ — {gt_full} | rola: {rola}")
            opravene += 1
        elif not in_text:
            print(f"⚫ {domain}: meno NIE JE v texte — nedá sa opraviť bez lepšieho scrapingu")
            nie_v_texte += 1
        else:
            ctx_idx = combined.lower().find(surname.lower())
            ctx = combined[max(0,ctx_idx-80):ctx_idx+80].replace("\n"," ")
            top2 = [(o.get("meno"), o.get("rola"), o.get("confidence")) for o in osoby[:2]]
            print(f"❌ {domain}: meno JE v texte ale stále chýba")
            print(f"   Kontext: ...{ctx}...")
            print(f"   Top osoby: {top2}")
            stale_chyba += 1

    print(f"\n{'='*50}")
    print(f"OPRAVENÉ:        {opravene}/12")
    print(f"NIE JE V TEXTE:  {nie_v_texte}/12  <- neopravitelne bez lepšieho scrapingu")
    print(f"STÁLE CHÝBA:     {stale_chyba}/12  <- dalsia oprava možná")
    print(f"PREDPOKLADANÝ VÝSLEDOK: {11 + opravene}/23 mien ({(11+opravene)*100//23}%)")

asyncio.run(main())
