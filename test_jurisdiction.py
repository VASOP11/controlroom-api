import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from main import _scrape_all_pages, detect_jurisdiction

CASES = [
    # Jasné prípady
    ("https://www.magano.sk/",       "SK"),      # SK firma, DIČ SK...
    ("https://www.pandaoutdoor.cz/", "CZ"),      # CZ firma, DIČ CZ...
    ("https://www.fgym.sk/",         "SK"),      # SK firma, IČO v hlavičke VOP (header scan)
    ("https://www.lavonio.sk/",      "CZ"),      # CZ firma na .sk doméne! DIČ CZ60749440

    # Cross-border (SK doména, CZ firma)
    ("https://www.ruzovakozmetika.sk/",  "CZ"),  # IČ 03522083, Stehelčeves, DIČ CZ...
    ("https://www.amirashop.sk/",        "CZ"),  # DIČ CZ04728190
    ("https://www.profesionalnikosmetika.cz/", "CZ"),

    # Rôzne
    ("https://www.skinlovers.sk/",       "SK"),  # DIČ SK...
    ("https://www.brasty.cz/",           "CZ"),  # DIČ CZ...

    # Nové — veľké CZ eshopy s dlhými VOP
    ("https://www.dedra.cz/",           "CZ"),
    ("https://www.vivantis.cz/",        "CZ"),
    ("https://www.bezvavlasy.cz/",      "CZ"),
]

async def main():
    correct = 0
    for url, expected in CASES:
        result = await _scrape_all_pages(url)
        combined = result.get("text", "") if isinstance(result, dict) else result[0]
        jur_extra = result.get("jur_extra", "") if isinstance(result, dict) else ""
        info = detect_jurisdiction(combined, url, extra_text=jur_extra)

        ok = info["jurisdiction"] == expected
        if ok:
            correct += 1

        marker = "✅" if ok else "❌"
        domain = url.split("//")[1].split("/")[0].replace("www.", "")
        print(f"{marker} {domain}: detekoval {info['jurisdiction']} (exp {expected}) | conf={info['confidence']} | found_in={info.get('ico_dic_found_in')} | DIČ={info.get('dic')}")
        print(f"   signály: {info.get('signals', [])[:4]}")

    print(f"\n{correct}/{len(CASES)} správnych")

asyncio.run(main())
