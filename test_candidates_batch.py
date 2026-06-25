"""
Test v6.16 candidates endpoint — batch 37 shopov.
Output: CSV tabuľka + HTML report.
"""

import asyncio
import httpx
import re
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

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
    "https://www.ruzovyslon.cz/",
    "https://www.isexshop.sk/",
    "https://sexshopbratislava.sk/",
    "https://www.sexiveci.sk/",
    "https://www.erotickaplaneta.sk/",
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
    "https://www.sexshop-erotic.cz/",
    "https://www.eshopemanuela.sk/",
]

V615_RESULTS = {
    "https://www.lavanda.sk/": {"meno": "Beata Strbova", "phone": "+421 903 715 099"},
    "https://www.minilove.sk/": {"meno": "Erika Blizikova", "phone": "+421 903 928 140"},
    "https://elmishop.sk/": {"meno": "Erika Matulova", "phone": "0907 581 791"},
    "https://www.ruzovyslon.cz/": {"meno": "Adam Durcak", "phone": None},
    "https://www.isexshop.sk/": {"meno": "Roman Melisek", "phone": None},
    "https://www.sedooz.sk/": {"meno": "Peter Durak", "phone": "+421 904 530 656"},
    "https://www.ferex.sk/": {"meno": "Ernesta Bielika", "phone": None},
    "https://www.eroloveshop.sk/": {"meno": "Michal Babensky", "phone": None},
    "https://www.mhsexshop.com/": {"meno": "Martin Hruby", "phone": "+420 608 926 623"},
    "https://www.sexshop-erotic.cz/": {"meno": None, "phone": "+420774305098"},
}

KNOWN_FP_PATTERNS = [
    "packeta", "geis", "panax", "ginkgo", "dpd", "ppl", "gls",
    "zasielkovna", "balikovna", "slovensky dorucovacie", "ceska posta",
]


class TestResult:
    def __init__(self, url: str):
        self.url = url
        self.status = "PENDING"
        self.error = None
        self.ico = None
        self.registry_source = None
        self.registry_ok = False
        self.registry_konatelia = []
        self.phones_found = 0
        self.emails_found = 0
        self.candidate_names = []
        self.v615_meno = V615_RESULTS.get(url, {}).get("meno")
        self.v615_phone = V615_RESULTS.get(url, {}).get("phone")
        self.v616_best_meno = None
        self.v616_best_phone = None
        self.blocked_fp = []
        self.warnings = []
        self.duration_s = 0.0

    def is_improved(self) -> bool:
        if self.error:
            return False
        if self.registry_konatelia:
            return True
        if self.emails_found > 0 and not self.v615_phone:
            return True
        return False

    def to_csv_row(self):
        return {
            "URL": self.url.replace("https://", "").replace("http://", "").rstrip("/"),
            "Status": self.status,
            "Duration": f"{self.duration_s:.1f}s",
            "ICO": self.ico or "",
            "Registry": self.registry_source or "",
            "Konatelia": "; ".join(self.registry_konatelia) if self.registry_konatelia else "",
            "Phones": self.phones_found,
            "Emails": self.emails_found,
            "Best Name v6.16": self.v616_best_meno or "",
            "Best Phone v6.16": self.v616_best_phone or "",
            "Blocked FP": "; ".join(self.blocked_fp) if self.blocked_fp else "",
            "V6.15 Name": self.v615_meno or "",
            "V6.15 Phone": self.v615_phone or "",
            "Improved": "YES" if self.is_improved() else ("ERROR" if self.error else ""),
            "Warnings": "; ".join(self.warnings) if self.warnings else "",
        }


async def test_one(client: httpx.AsyncClient, url: str) -> TestResult:
    result = TestResult(url)
    short = url.replace("https://", "").replace("http://", "").rstrip("/")
    try:
        print(f"  [{short}] ...", end=" ", flush=True)
        import time
        t0 = time.monotonic()

        r = await client.post(
            "http://localhost:8000/api/leads/candidates",
            json={"url": url},
            headers={"Authorization": "Bearer test-token"},
            timeout=90,
        )
        result.duration_s = time.monotonic() - t0

        if r.status_code != 200:
            result.status = f"HTTP {r.status_code}"
            result.error = r.text[:300]
            print(f"ERR {r.status_code} ({result.duration_s:.1f}s)")
            return result

        data = r.json()
        result.status = "OK"
        result.ico = data.get("ico")
        result.warnings = data.get("scrape_warnings", [])

        registry = data.get("registry", {})
        result.registry_source = registry.get("source")
        result.registry_ok = registry.get("lookup_ok", False)
        result.registry_konatelia = [
            k.get("meno") for k in registry.get("konatelia", []) if k.get("meno")
        ]

        phones = data.get("phones", [])
        result.phones_found = len(phones)
        for p in phones:
            if p.get("typ_pravdepodobne") == "personal":
                result.v616_best_phone = p.get("cislo")
                break
        if not result.v616_best_phone and phones:
            result.v616_best_phone = phones[0].get("cislo")

        result.emails_found = len(data.get("emails", []))

        for n in data.get("kandidati_meno", []):
            name = n.get("meno", "")
            if not name:
                continue
            name_lower = name.lower()
            if any(fp in name_lower for fp in KNOWN_FP_PATTERNS):
                result.blocked_fp.append(name)
                continue
            result.candidate_names.append(name)
            if not result.v616_best_meno:
                result.v616_best_meno = name

        parts = []
        if result.registry_konatelia:
            parts.append(f"reg={','.join(result.registry_konatelia[:2])}")
        parts.append(f"{result.phones_found}ph/{result.emails_found}em")
        print(f"OK {' '.join(parts)} ({result.duration_s:.1f}s)")
        return result

    except httpx.TimeoutException:
        result.status = "TIMEOUT"
        result.error = "Timeout 90s"
        print("TIMEOUT")
        return result
    except Exception as e:
        result.status = "ERROR"
        result.error = str(e)[:300]
        print(f"ERR {str(e)[:60]}")
        return result


def generate_html_report(results):
    ok = [r for r in results if r.status == "OK"]
    errs = [r for r in results if r.error]
    reg = [r for r in results if r.registry_konatelia]
    improved = [r for r in results if r.is_improved()]
    total_phones = sum(r.phones_found for r in ok)
    total_emails = sum(r.emails_found for r in ok)
    avg_dur = sum(r.duration_s for r in results) / len(results) if results else 0

    rows_html = ""
    for r in results:
        cls = ""
        if r.error:
            cls = "row-error"
        elif r.registry_konatelia:
            cls = "row-registry"

        konatelia_str = "; ".join(r.registry_konatelia) if r.registry_konatelia else ""
        fp_str = "; ".join(r.blocked_fp) if r.blocked_fp else ""
        short_url = r.url.replace("https://", "").replace("http://", "").rstrip("/")

        status_cls = "st-ok" if r.status == "OK" else ("st-timeout" if "TIMEOUT" in r.status else "st-err")

        rows_html += f"""<tr class="{cls}">
<td class="url">{short_url}</td>
<td class="{status_cls}">{r.status}</td>
<td>{r.duration_s:.1f}s</td>
<td>{r.ico or ''}</td>
<td>{r.registry_source or ''}</td>
<td>{konatelia_str}</td>
<td>{r.phones_found}</td>
<td>{r.emails_found}</td>
<td><b>{r.v616_best_meno or ''}</b><br><small>{r.v616_best_phone or ''}</small></td>
<td>{r.v615_meno or ''}<br><small>{r.v615_phone or ''}</small></td>
<td>{fp_str}</td>
</tr>
"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Wector v6.16 Test Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 20px; background: #f8f9fa; color: #333; }}
h1 {{ margin-bottom: 5px; }}
.meta {{ color: #666; margin-bottom: 20px; }}
.summary {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }}
.card {{ background: white; border-radius: 8px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.1); min-width: 120px; }}
.card .num {{ font-size: 28px; font-weight: 700; }}
.card .label {{ font-size: 13px; color: #666; }}
.card.green .num {{ color: #16a34a; }}
.card.red .num {{ color: #dc2626; }}
.card.blue .num {{ color: #2563eb; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); font-size: 13px; }}
th {{ background: #1e293b; color: white; padding: 10px 8px; text-align: left; font-weight: 600; white-space: nowrap; }}
td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
tr:hover {{ background: #f1f5f9; }}
.url {{ font-family: monospace; font-size: 12px; white-space: nowrap; }}
.row-error {{ background: #fef2f2; }}
.row-registry {{ background: #f0fdf4; }}
.st-ok {{ color: #16a34a; font-weight: 600; }}
.st-err {{ color: #dc2626; font-weight: 600; }}
.st-timeout {{ color: #d97706; font-weight: 600; }}
</style></head><body>
<h1>Wector v6.16 &mdash; Test Report</h1>
<div class="meta">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | {len(results)} shops | avg {avg_dur:.1f}s/shop</div>

<div class="summary">
<div class="card green"><div class="num">{len(ok)}/{len(results)}</div><div class="label">OK</div></div>
<div class="card red"><div class="num">{len(errs)}</div><div class="label">Errors</div></div>
<div class="card blue"><div class="num">{len(reg)}</div><div class="label">Registry found</div></div>
<div class="card green"><div class="num">{len(improved)}</div><div class="label">Improved vs v6.15</div></div>
<div class="card"><div class="num">{total_phones}</div><div class="label">Total phones</div></div>
<div class="card"><div class="num">{total_emails}</div><div class="label">Total emails</div></div>
</div>

<table>
<thead><tr>
<th>Shop</th><th>Status</th><th>Time</th><th>ICO</th><th>Registry</th><th>Konatelia</th><th>Ph</th><th>Em</th><th>v6.16 Best</th><th>v6.15</th><th>Blocked FP</th>
</tr></thead>
<tbody>
{rows_html}
</tbody></table>
</body></html>"""


async def main():
    print("=" * 70)
    print("Wector v6.16 - Candidates Batch Test (37 shops)")
    print("=" * 70)

    # Wait for server to be ready
    async with httpx.AsyncClient() as client:
        for attempt in range(10):
            try:
                r = await client.get("http://localhost:8000/docs", timeout=3)
                if r.status_code == 200:
                    print("Server is ready.\n")
                    break
            except Exception:
                pass
            print(f"Waiting for server... ({attempt+1}/10)")
            await asyncio.sleep(2)
        else:
            print("ERROR: Server not reachable on localhost:8000")
            return

    results = []
    async with httpx.AsyncClient() as client:
        for i, url in enumerate(URLS, 1):
            result = await test_one(client, url)
            results.append(result)
            if i % 10 == 0:
                print(f"  --- Progress: {i}/{len(URLS)} ---")

    # CSV
    csv_path = Path("test_report_v6.16.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].to_csv_row().keys()))
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_csv_row())
    print(f"\nCSV saved: {csv_path}")

    # HTML
    html_path = Path("test_report_v6.16.html")
    html_path.write_text(generate_html_report(results), encoding="utf-8")
    print(f"HTML saved: {html_path}")

    # Summary
    ok = [r for r in results if r.status == "OK"]
    errs = [r for r in results if r.error]
    reg = [r for r in results if r.registry_konatelia]
    improved = [r for r in results if r.is_improved()]

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  OK:           {len(ok)}/{len(results)}")
    print(f"  Errors:       {len(errs)}/{len(results)}")
    print(f"  Registry:     {len(reg)}/{len(results)}")
    print(f"  Improved:     {len(improved)}/{len(results)}")
    print(f"  Total phones: {sum(r.phones_found for r in ok)}")
    print(f"  Total emails: {sum(r.emails_found for r in ok)}")
    fp_all = []
    for r in results:
        fp_all.extend(r.blocked_fp)
    if fp_all:
        print(f"  Blocked FPs:  {', '.join(set(fp_all))}")
    print("=" * 70)

    if len(errs) > 10:
        print("\n  VERDICT: > 10 errors — FIX PRED PUSHOM")
    elif len(errs) > 5:
        print("\n  VERDICT: 5-10 errors — review before push")
    else:
        print("\n  VERDICT: Ready for push")


if __name__ == "__main__":
    asyncio.run(main())
