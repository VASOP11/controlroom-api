"""Fresh ORSR lookup (cache cleared) + save HTML for debug"""
import httpx
from bs4 import BeautifulSoup
import re
from registry_lookup import lookup_orsr, _parse_orsr_detail

_ORSR_BASE = "https://www.orsr.sk"
_ORSR_SEARCH = "https://www.orsr.sk/hladaj_ico.asp"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"}

def debug_orsr(ico, label):
    print(f"\n{'='*60}")
    print(f"{label} (ICO: {ico})")
    print(f"{'='*60}")

    with httpx.Client(timeout=15, follow_redirects=True) as client:
        # Step 1: Search
        search_resp = client.get(
            _ORSR_SEARCH,
            params={"ICO": ico, "SID": "0", "T": "f0", "R": "on"},
            headers={**_HEADERS, "Accept-Language": "sk-SK,sk;q=0.9"},
        )
        print(f"Search HTTP: {search_resp.status_code}")

        soup = BeautifulSoup(search_resp.text, "html.parser")
        detail_url = None
        for a in soup.find_all("a", href=True):
            if "vypis.asp" in a["href"] and "ID=" in a["href"]:
                detail_url = _ORSR_BASE + "/" + a["href"].lstrip("/")
                print(f"Detail URL: {detail_url}")
                print(f"Company: {a.get_text(strip=True)}")
                break

        if not detail_url:
            print("DETAIL URL NOT FOUND!")
            # Save search page for debug
            with open(f"orsr_search_{ico}.html", "w", encoding="utf-8") as f:
                f.write(search_resp.text)
            print(f"Search HTML saved: orsr_search_{ico}.html")
            return

        # Step 2: Detail
        detail_resp = client.get(detail_url, headers=_HEADERS)
        print(f"Detail HTTP: {detail_resp.status_code}")

        # Save detail HTML
        with open(f"orsr_detail_{ico}.html", "w", encoding="utf-8") as f:
            f.write(detail_resp.text)
        print(f"Detail HTML saved: orsr_detail_{ico}.html")

        # Step 3: Parse
        members = _parse_orsr_detail(detail_resp.text)
        print(f"\nParsed konatelia: {len(members)}")
        for m in members:
            print(f"  -> {m}")

        if not members:
            # Debug: show relevant lines from detail page
            text = BeautifulSoup(detail_resp.text, "html.parser").get_text(separator="\n")
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            print("\n--- Hladam 'Konatel/Statutarny' v texte ---")
            for i, line in enumerate(lines):
                ll = line.lower()
                if any(kw in ll for kw in ["konateľ", "konatelia", "štatutárny", "statutarny", "jednatel"]):
                    start = max(0, i-2)
                    end = min(len(lines), i+8)
                    for j in range(start, end):
                        marker = ">>>" if j == i else "   "
                        print(f"  {marker} [{j}] {lines[j][:120]}")
                    print()

    # Now test through the official function
    print("\n--- Official lookup_orsr() ---")
    r = lookup_orsr(ico)
    print(f"  found: {r.get('found')}")
    print(f"  obchodne_meno: {r.get('obchodne_meno')}")
    print(f"  konatelia: {r.get('konatelia')}")


tests = [
    ("51747391", "minilove.sk / MAXVOLT s.r.o."),
    ("48288713", "lavanda.sk / Lavanda Decor s.r.o."),
    ("46168931", "isexshop.sk / INTERNET BUSINESS s.r.o."),
]

for ico, label in tests:
    debug_orsr(ico, label)
