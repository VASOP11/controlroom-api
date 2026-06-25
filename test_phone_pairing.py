import asyncio, sys, os, unicodedata, re
sys.stdout.reconfigure(encoding='utf-8')
os.environ["FORCE_PLAYWRIGHT"] = "1"
from main import _scrape_all_pages, associate_persons_with_roles, extract_all_candidates, _extract_cisla_ico

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

TESTS = [
    ("https://unizdrav.sk/",          "Lamanec",   "051"),
    ("https://www.cisteoblecenie.sk/", "Mikul",     "910 621"),
    ("https://www.bubulakovo.sk/",    "Kozmer",    "905383904"),
]

def telefon_pre_osobu(p, cisla_out):
    """Mirrors the logic in main.py _telefon_pre_osobu"""
    meno_lower = strip_accents(p["meno"]).lower()
    first_word = meno_lower.split()[0] if meno_lower.split() else ""
    if first_word and len(first_word) > 3:
        best_cislo, best_dist = None, 200
        for c in cisla_out:
            ctx = strip_accents(c.get("kontext") or "").lower()
            if not ctx:
                continue
            ph_stripped = strip_accents(c["cislo"]).lower().strip()
            phone_idx = ctx.find(ph_stripped)
            if phone_idx < 0:
                continue
            pre_phone = ctx[:phone_idx]
            idx = pre_phone.rfind(first_word)
            if idx >= 0:
                dist = phone_idx - idx
                if dist < best_dist:
                    best_dist = dist
                    best_cislo = c["cislo"]
        if best_cislo:
            return best_cislo
    return p.get("telefon_osoby")

async def main():
    for url, name, phone_fragment in TESTS:
        domain = url.split("//")[1].split("/")[0].replace("www.", "")
        r = await _scrape_all_pages(url)
        text = r.get("text", "") if isinstance(r, dict) else r[0]
        osoby = associate_persons_with_roles(text)

        cands = extract_all_candidates(text)
        cisla_out, ico_out = _extract_cisla_ico(cands, text)

        target = next(
            (o for o in osoby if name.lower() in strip_accents(o.get("meno", "")).lower()),
            None
        )
        if target:
            tel_near = target.get("telefon_osoby")
            tel_full = telefon_pre_osobu(target, cisla_out)
            tel_ok_full = phone_fragment in (tel_full or "")
            status = "OK" if tel_ok_full else "FAIL"
            print(f"{status} {domain}: {target.get('meno')} | tel_near={tel_near} | tel_full={tel_full} | ocakavam '{phone_fragment}'")
        else:
            print(f"FAIL {domain}: osoba '{name}' nenajdena | osoby={[o.get('meno') for o in osoby[:3]]}")

asyncio.run(main())
