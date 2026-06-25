"""
Wector v6.16 — UI Preview Report (slovensky)
Ukazuje presne ako budu data vyzerat v UI: registry, telefony, emaily, triedenie
"""

import asyncio
import httpx
import time
from datetime import datetime
from pathlib import Path


URLS = [
    "https://www.minilove.sk/",
    "https://www.lavanda.sk/",
    "https://elmishop.sk/",
    "https://www.isexshop.sk/",
    "https://www.sedooz.sk/",
    "https://www.mojsvet.eu/",
    "https://www.eros.sk/",
    "https://www.kondomshop.sk/",
    "https://www.ruzovyslon.cz/",
    "https://www.flagranti.sk/",
    "https://www.mhsexshop.com/",
    "https://www.sexshop-erotic.cz/",
]


async def test_one(client, url):
    domain = url.replace("https://", "").replace("http://", "").rstrip("/")
    try:
        print(f"  {domain} ...", end=" ", flush=True)
        t0 = time.monotonic()
        r = await client.post(
            "http://localhost:8000/api/leads/candidates",
            json={"url": url},
            headers={"Authorization": "Bearer test-token"},
            timeout=90,
        )
        dur = time.monotonic() - t0
        if r.status_code != 200:
            print(f"ERR {r.status_code} ({dur:.1f}s)")
            return None
        data = r.json()
        print(f"OK ({dur:.1f}s)")
        return {"domain": domain, "url": url, "data": data, "duration": dur}
    except Exception as e:
        print(f"ERR {str(e)[:50]}")
        return None


def _esc(s):
    if not s:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_html(results):
    total = len(results)
    reg_count = sum(1 for r in results if r["data"].get("registry", {}).get("konatelia"))
    total_ph = sum(len(r["data"].get("phones", [])) for r in results)
    total_em = sum(len(r["data"].get("emails", [])) for r in results)

    cards_html = ""
    for res in results:
        data = res["data"]
        domain = _esc(res["domain"])
        registry = data.get("registry", {})
        konatelia = registry.get("konatelia", [])
        phones = data.get("phones", [])
        emails = data.get("emails", [])
        names = data.get("kandidati_meno", [])
        ico = data.get("ico")

        # --- REGISTRY SECTION ---
        reg_html = ""
        if konatelia:
            items = ""
            for k in konatelia:
                meno = _esc(k.get("meno", ""))
                funkcia = _esc(k.get("funkcia", "konatel"))
                src = _esc((registry.get("source") or "").upper())
                ico_str = _esc(ico) if ico else ""
                items += f"""<div class="item item-green">
                    <div class="item-title">{meno}</div>
                    <div class="item-sub">
                        <span class="badge bg-green">{funkcia}</span>
                        <span class="badge bg-blue">{src}</span>
                        {"<span class='ico'>ICO: " + ico_str + "</span>" if ico_str else ""}
                    </div>
                </div>"""
            reg_html = f"""<div class="section sec-green">
                <div class="sec-title">Z REGISTRA (autoritativne)</div>
                {items}
            </div>"""

        # --- PHONES SECTION ---
        ph_personal = [p for p in phones if p.get("typ_pravdepodobne") in ("personal", "info", "unknown", None)]
        ph_delivery = [p for p in phones if p.get("typ_pravdepodobne") == "delivery"]

        ph_items = ""
        for p in ph_personal[:8]:
            cislo = _esc(p.get("cislo", ""))
            typ = p.get("typ_pravdepodobne", "unknown")
            typ_lbl = {"personal": "Osobny", "info": "Info", "unknown": "Nezaradeny"}.get(typ, typ)
            typ_cls = {"personal": "bg-green", "info": "bg-blue"}.get(typ, "bg-gray")
            near = _esc(p.get("blizke_meno") or "")
            page = _esc(p.get("stranka") or "")
            ctx_pre = _esc((p.get("kontext_pred") or "")[-50:])
            ctx_post = _esc((p.get("kontext_po") or "")[:40])
            ctx_str = ""
            if ctx_pre or ctx_post:
                ctx_str = f'<div class="ctx">&ldquo;{ctx_pre} ... {ctx_post}&rdquo;</div>'
            near_str = f'<span class="near-name">&#128100; {near}</span>' if near else ""
            page_str = f'<span class="page-hint">{page}</span>' if page else ""

            ph_items += f"""<div class="item">
                <div class="item-title">{cislo}</div>
                <div class="item-sub">
                    <span class="badge {typ_cls}">{typ_lbl}</span>
                    {near_str} {page_str}
                </div>
                {ctx_str}
            </div>"""

        filt_note = f" &mdash; {len(ph_delivery)} filtrovanych (prepravca)" if ph_delivery else ""
        ph_html = f"""<div class="section sec-blue">
            <div class="sec-title">TELEFONY ({len(ph_personal)} zobrazených{filt_note})</div>
            {ph_items if ph_items else '<div class="empty">Ziadne telefony nenajdene</div>'}
        </div>"""

        # --- EMAILS SECTION ---
        em_items = ""
        for e in emails[:6]:
            email = _esc(e.get("email", ""))
            typ = e.get("typ_pravdepodobne", "generic")
            typ_lbl = {"personal": "Osobny", "generic": "Genericky (info@)"}.get(typ, typ)
            typ_cls = {"personal": "bg-green", "generic": "bg-orange"}.get(typ, "bg-gray")
            page = _esc(e.get("stranka") or "/")
            em_items += f"""<div class="item">
                <div class="item-title">{email}</div>
                <div class="item-sub">
                    <span class="badge {typ_cls}">{typ_lbl}</span>
                    <span class="page-hint">{page}</span>
                </div>
            </div>"""

        em_html = f"""<div class="section sec-orange">
            <div class="sec-title">EMAILY ({len(emails)} najdenych)</div>
            {em_items if em_items else '<div class="empty">Ziadne emaily nenajdene</div>'}
        </div>"""

        # --- KANDIDATI MENO (ak nie su konatelia) ---
        kand_html = ""
        if not konatelia and names:
            kand_items = ""
            for n in names[:4]:
                if (n.get("confidence") or 0) < 3:
                    continue
                meno = _esc(n.get("meno", ""))
                rola = _esc(n.get("rola") or "neznama")
                zdroj = _esc(n.get("zdroj") or "")
                conf = int((n.get("confidence") or 0) * 10)
                ctx = _esc((n.get("kontext") or "")[:80])
                kand_items += f"""<div class="item">
                    <div class="item-title">{meno}</div>
                    <div class="item-sub">
                        <span class="badge bg-gray">{rola}</span>
                        <span class="badge bg-blue">{zdroj}</span>
                        <span class="conf">Dovera: {conf}%</span>
                    </div>
                    {"<div class='ctx'>&ldquo;" + ctx + "&rdquo;</div>" if ctx else ""}
                </div>"""
            if kand_items:
                kand_html = f"""<div class="section sec-gray">
                    <div class="sec-title">KANDIDATI MENO (alternativa k registru)</div>
                    {kand_items}
                </div>"""

        cards_html += f"""<div class="card">
            <div class="card-head">{domain}
                <span class="dur">{res['duration']:.1f}s</span>
            </div>
            {reg_html}
            {ph_html}
            {em_html}
            {kand_html}
        </div>
"""

    return f"""<!DOCTYPE html>
<html lang="sk"><head><meta charset="utf-8">
<title>Wector v6.16 — UI Preview</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f0f2f5;padding:24px;color:#333}}
.hdr{{background:#1e293b;color:#fff;padding:28px 32px;border-radius:10px;margin-bottom:28px}}
.hdr h1{{font-size:26px;margin-bottom:4px}}
.hdr p{{color:#94a3b8;font-size:13px}}
.stats{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:28px}}
.stat{{background:#fff;border-radius:8px;padding:16px 22px;box-shadow:0 1px 4px rgba(0,0,0,.08);min-width:130px;text-align:center}}
.stat .v{{font-size:28px;font-weight:700}}
.stat .l{{font-size:12px;color:#64748b;margin-top:2px}}
.stat.green .v{{color:#16a34a}}
.stat.blue .v{{color:#2563eb}}
.stat.orange .v{{color:#ea580c}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(560px,1fr));gap:22px}}
.card{{background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.08)}}
.card-head{{background:#1e293b;color:#fff;padding:14px 20px;font-weight:600;font-size:14px;display:flex;justify-content:space-between;align-items:center}}
.dur{{font-size:11px;color:#94a3b8;font-weight:400}}
.section{{padding:14px 20px;border-bottom:1px solid #f1f5f9}}
.section:last-child{{border-bottom:none}}
.sec-title{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;color:#475569}}
.sec-green{{background:#f0fdf4;border-left:4px solid #22c55e}}
.sec-blue{{background:#eff6ff;border-left:4px solid #3b82f6}}
.sec-orange{{background:#fff7ed;border-left:4px solid #f97316}}
.sec-gray{{background:#f8fafc;border-left:4px solid #94a3b8}}
.item{{background:#fff;padding:10px 12px;margin-bottom:8px;border-radius:6px;border:1px solid #e2e8f0}}
.item-green{{border-left:3px solid #22c55e}}
.item-title{{font-weight:600;color:#1e293b;font-size:14px}}
.item-sub{{margin-top:4px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}}
.badge{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600}}
.bg-green{{background:#dcfce7;color:#166534}}
.bg-blue{{background:#dbeafe;color:#1e40af}}
.bg-orange{{background:#ffedd5;color:#9a3412}}
.bg-red{{background:#fee2e2;color:#991b1b}}
.bg-gray{{background:#f1f5f9;color:#475569}}
.near-name{{font-size:11px;color:#7c3aed}}
.page-hint{{font-size:10px;color:#94a3b8}}
.ico{{font-size:10px;color:#64748b}}
.conf{{font-size:10px;color:#94a3b8}}
.ctx{{background:#f8fafc;padding:5px 8px;border-radius:4px;font-size:11px;color:#64748b;margin-top:6px;max-height:36px;overflow:hidden}}
.empty{{color:#94a3b8;font-size:12px;font-style:italic;padding:4px 0}}
</style></head><body>
<div class="hdr">
<h1>Wector v6.16 &mdash; UI Preview Report</h1>
<p>Ako budu vyzerat data v UI: Registry | Telefony | Emaily | Triedenie &bull; {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}</p>
</div>
<div class="stats">
<div class="stat green"><div class="v">{total}/{len(URLS)}</div><div class="l">Uspesne</div></div>
<div class="stat blue"><div class="v">{reg_count}</div><div class="l">S registrom</div></div>
<div class="stat orange"><div class="v">{total_ph}</div><div class="l">Telefony spolu</div></div>
<div class="stat"><div class="v">{total_em}</div><div class="l">Emaily spolu</div></div>
</div>
<div class="grid">
{cards_html}
</div>
</body></html>"""


async def main():
    print("=" * 60)
    print("Wector v6.16 — UI Preview Report (12 shops)")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        for attempt in range(10):
            try:
                r = await client.get("http://localhost:8000/health", timeout=3)
                if r.status_code == 200:
                    print("Server OK.\n")
                    break
            except Exception:
                pass
            print(f"  Cakam na server... ({attempt+1}/10)")
            await asyncio.sleep(2)
        else:
            print("Server nie je dostupny na localhost:8000")
            return

    results = []
    async with httpx.AsyncClient() as client:
        for url in URLS:
            res = await test_one(client, url)
            if res:
                results.append(res)

    html_path = Path("test_report_ui_preview.html")
    html_path.write_text(generate_html(results), encoding="utf-8")
    print(f"\nReport: {html_path}")
    print(f"Uspesne: {len(results)}/{len(URLS)}")


if __name__ == "__main__":
    asyncio.run(main())
