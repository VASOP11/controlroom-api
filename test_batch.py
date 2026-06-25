"""
Wector — batch test
Spustenie: python test_batch.py
Výsledok:  test_batch_results.csv  (otvor v Exceli)
"""

import asyncio, sys, os, csv, time
from datetime import datetime

sys.path.insert(0, r"C:\Users\vizva\controlroom-api")

URLS = [
    "https://www.candyloco.sk/",
    "https://www.floraobal.sk/",
    "https://www.lavanda.sk/",
    "https://capkov.cz/",
    "https://www.inspio.sk/",
    "https://www.mojsvet.eu/",
    "https://www.tuli.sk/",
    "https://www.dajlabku.sk/",
    "https://www.medaren.sk/",
    "https://www.minilove.sk/",
    "https://www.rozkos.sk/",
    "https://elmishop.sk/",
    "https://www.ruzovyslon.cz",
    "https://www.isexshop.sk/",
    "https://sexshopbratislava.sk/",
    "https://www.sexiveci.sk/",
    "http://www.erotickaplaneta.sk/",
    "https://www.ebabo.sk/",
    "https://www.kondomshop.sk/",
    "https://scanquilt.sk/",
    "https://www.bala21.cz/",
    "https://www.sedooz.sk/",
    "https://kktky.sk/",
    "https://www.ferex.sk/",
    "https://babyknihy.sk/",
    "https://superlove.sk/",
    "https://www.eroticcity.sk/",
    "https://www.eros.sk/",
    "https://www.69shop.sk/",
    "https://www.erosstar.cz/",
    "https://www.sexposta.sk/",
    "https://www.slave4master.sk/",
    "https://www.eroloveshop.sk/",
    "https://www.flagranti.sk/",
    "https://www.mhsexshop.com/",
    "https://www.sexshop-erotic.cz",
    "https://www.eshopemanuela.sk/",
]

async def test_one(url):
    try:
        from main import _scrape_all_pages, associate_persons_with_roles
        result = await asyncio.wait_for(_scrape_all_pages(url), timeout=60)

        text = result.get("text", "") or result.get("combined_text", "")
        emails = result.get("emails", [])
        phones_raw = result.get("cisla", []) or result.get("phones", [])

        # osoby
        osoby = []
        try:
            osoby = associate_persons_with_roles(text)
        except Exception as e:
            pass

        top = osoby[0] if osoby else {}

        # všetky telefóny ako string
        all_phones = ""
        if phones_raw:
            if isinstance(phones_raw[0], dict):
                all_phones = " | ".join(p.get("cislo","") for p in phones_raw[:5])
            else:
                all_phones = " | ".join(str(p) for p in phones_raw[:5])

        return {
            "url": url,
            "meno": top.get("meno", ""),
            "rola": top.get("rola", ""),
            "telefon_osoby": top.get("telefon_osoby", "") or top.get("telefon", ""),
            "vsetky_telefony": all_phones,
            "email": emails[0] if emails else "",
            "score": result.get("priority_score", "") or result.get("score", ""),
            "pocet_osob": len(osoby),
            "chyba": "",
        }

    except asyncio.TimeoutError:
        return {"url": url, "meno": "", "rola": "", "telefon_osoby": "",
                "vsetky_telefony": "", "email": "", "score": "", "pocet_osob": 0,
                "chyba": "TIMEOUT"}
    except Exception as e:
        return {"url": url, "meno": "", "rola": "", "telefon_osoby": "",
                "vsetky_telefony": "", "email": "", "score": "", "pocet_osob": 0,
                "chyba": str(e)[:120]}


async def main():
    results = []
    total = len(URLS)

    for i, url in enumerate(URLS, 1):
        domain = url.replace("https://","").replace("http://","").replace("www.","").split("/")[0]
        print(f"[{i:02d}/{total}] {domain}...", end=" ", flush=True)

        r = await test_one(url)
        results.append(r)

        if r["chyba"]:
            print(f"❌ {r['chyba']}")
        else:
            meno = r["meno"] or "—"
            tel  = r["telefon_osoby"] or "—"
            print(f"✅  {meno}  |  {tel}")

        time.sleep(0.5)

    # Ulož CSV
    out = "test_batch_results.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = ["url","meno","rola","telefon_osoby","vsetky_telefony","email","score","pocet_osob","chyba"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    # Súhrn
    ok    = sum(1 for r in results if r["meno"] and not r["chyba"])
    tel   = sum(1 for r in results if r["telefon_osoby"] and not r["chyba"])
    email = sum(1 for r in results if r["email"] and not r["chyba"])
    err   = sum(1 for r in results if r["chyba"])

    print()
    print("="*50)
    print(f"Meno nájdené:    {ok}/{total}")
    print(f"Telefón nájdený: {tel}/{total}")
    print(f"Email nájdený:   {email}/{total}")
    print(f"Chyby/timeout:   {err}/{total}")
    print(f"\nVýsledky uložené: {out}")
    print("Otvor v Exceli a porovnaj s tým čo vieš.")

asyncio.run(main())
