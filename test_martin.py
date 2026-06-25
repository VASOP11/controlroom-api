import asyncio
import re
import sys

# Fix Windows terminal encoding
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from main import (
    _scrape_all_pages,
    associate_persons_with_roles,
    extract_all_candidates,
    _extract_cisla_ico,
)

# ── KONFIGURÁCIA TESTOV ──────────────────────────────────────────────────────
TESTS = [
    # (url, popis, ocakavane_mena_s_rolou, ocakavany_min_osob, ocakavany_max_osob)
    ("https://www.magano.sk",                    "magano.sk",                  ["Martin Zachar"],   1, 99),
    ("https://www.indarceky.sk",                 "indarceky.sk",               ["Rastislav Fiala"], 1, 99),
    ("https://www.lavonio.sk",                   "lavonio.sk",                 ["Adam Koudela"],    1, 99),
    # info-only — očakávame 0 osôb s conf>=3
    ("https://www.medistore.sk",                 "medistore.sk",               [],                  0,  2),
    ("https://www.amirashop.sk",                 "amirashop.sk",               [],                  0,  2),
    ("https://www.decorglass.sk",                "decorglass.sk",              [],                  0,  5),
    # nové — len vypíše čo nájde, bez striktných assertions
    ("https://www.pandaoutdoor.cz/",             "pandaoutdoor.cz",            [],                  0, 99),
    ("https://www.profesionalnikosmetika.cz/",   "profesionalnikosmetika.cz",  [],                  0, 99),
    ("https://www.fgym.sk/",                     "fgym.sk",                    [],                  0, 99),
    ("https://www.dekorbymirka.sk/",             "dekorbymirka.sk",            [],                  0, 99),
]

SEP = "─" * 70


def _short(s: str, n: int = 80) -> str:
    """Skráti string na n znakov s '…' na konci."""
    s = s.replace("\n", " ").strip()
    return s[:n] + "…" if len(s) > n else s




async def test_one(url, label, expected_names, min_osob, max_osob):
    print(f"\n{SEP}")
    print(f"🌐  {label}  ({url})")
    print(SEP)

    result = await _scrape_all_pages(url)

    if isinstance(result, dict):
        combined = result.get("text", "")
    elif isinstance(result, tuple):
        combined = result[0]
    else:
        combined = str(result)

    jsonld = result.get("jsonld", {}) if isinstance(result, dict) else {}
    print(f"COMBINED: {len(combined)} znakov")

    # Normalizovaný text pre kontextové hľadanie (rovnako ako raw_extract)
    norm_text = combined.replace("\xa0", " ")
    norm_text = re.sub(r"\n+", " ", norm_text)
    norm_text = re.sub(r" {2,}", " ", norm_text)

    candidates = extract_all_candidates(combined)
    cisla_out, ico_out = _extract_cisla_ico(candidates, norm_text, jsonld_phone=jsonld.get("phone"))
    osoby = associate_persons_with_roles(combined)

    # ── EMAILS ──────────────────────────────────────────────────────────────
    emails_list = []
    seen_e: set = set()
    if jsonld.get("email"):
        e = jsonld["email"].strip()
        if e.lower() not in seen_e:
            seen_e.add(e.lower())
            emails_list.append(e)
    for entry in candidates.get("emails", []):
        if entry["value"].lower() not in seen_e:
            seen_e.add(entry["value"].lower())
            emails_list.append(entry["value"])

    print(f"\nEMAILS: {emails_list}")

    # ── IČO ─────────────────────────────────────────────────────────────────
    print(f"ICO:    {ico_out or '—'}")

    # ── ČÍSLA ───────────────────────────────────────────────────────────────
    print(f"\nCISLA ({len(cisla_out)}):")
    for c in cisla_out:
        kw = ", ".join(c["klucove_slova"]) if c["klucove_slova"] else "—"
        print(f"  • {c['cislo']}")
        print(f"    kontext : {_short(c['kontext'])}")
        print(f"    kľúč sl.: {_short(kw, 100)}")

    # ── OSOBY ───────────────────────────────────────────────────────────────
    print(f"\nOSOBY ({len(osoby)}):")
    for o in osoby:
        rola_str = f"{o['rola']} (LVL{o['rola_level']})" if o.get("rola") else "— (bez roly)"
        print(f"  • {o['meno']:<30} | {rola_str:<40} | conf={o['confidence']}")
        print(f"    kontext : {_short(o.get('kontext', ''))}")

    # ── PRIRADENIE ČÍSLO ↔ OSOBA ────────────────────────────────────────────
    osoby_s_rolou = [o for o in osoby if o.get("rola")]
    if osoby_s_rolou and cisla_out:
        print(f"\nPRIRADENIE číslo ↔ osoba:")
        for o in osoby_s_rolou:
            meno = o["meno"]
            rola = o["rola"]
            for c in cisla_out:
                ctx_lower = c["kontext"].lower()
                meno_v_ctx = meno.lower() in ctx_lower
                rola_v_ctx = rola.lower() in ctx_lower
                if meno_v_ctx or rola_v_ctx:
                    meno_tag = "ÁNO" if meno_v_ctx else "NIE"
                    rola_tag = "ÁNO" if rola_v_ctx else "NIE"
                    print(f"  🔗 {meno} ({rola}) ↔ {c['cislo']}")
                    print(f"     meno v kontexte čísla: {meno_tag}  |  rola v kontexte čísla: {rola_tag}")

    # ── ASSERTIONS (len pre weby s expected) ────────────────────────────────
    ok = True
    strict = max_osob != 99  # nové weby (max=99) sa len zobrazujú, nefailujú

    if strict:
        if not (min_osob <= len(osoby) <= max_osob):
            print(f"\n  ❌ POCET: očakávané {min_osob}–{max_osob}, got {len(osoby)}")
            ok = False

        mena_v_output = [o.get("meno", "") for o in osoby]
        for exp in expected_names:
            found = any(exp.lower() in m.lower() for m in mena_v_output)
            if not found:
                print(f"  ❌ CHÝBA: '{exp}' nie je v osoby")
                ok = False

        for o in osoby:
            if (o.get("rola") or "").upper() in ("EZAL", "E.Z.A.L", "EZAL S.R.O"):
                print(f"  ❌ FALSE ROLA: '{o['meno']}' má rolu 'EZAL' — to je názov živnosti!")
                ok = False

        if max_osob == 2:
            high_conf = [o for o in osoby if o.get("confidence", 0) >= 3]
            if high_conf:
                print(f"  ⚠️  INFO-ONLY web má {len(high_conf)} osôb s conf>=3 — možné false positive:")
                for o in high_conf:
                    print(f"      • {o.get('meno')} | rola={o.get('rola')} | conf={o.get('confidence')}")
                ok = False

    if ok:
        print(f"\n  ✅ PASS")
    return ok


async def main():
    results = []
    for url, label, expected, mn, mx in TESTS:
        ok = await test_one(url, label, expected, mn, mx)
        results.append((label, ok))

    print(f"\n{SEP}")
    print("SÚHRN:")
    for label, ok in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {label}")
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{passed}/{len(results)} testov prešlo")
    print(SEP)


asyncio.run(main())
