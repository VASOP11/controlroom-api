"""
Benchmark test: 40 URL scraping cez nasadený debug endpoint na Renderi.
Porovnáva expected vs actual email, telefón, meno.
"""
import requests
import csv
import sys
import time
import re

API_BASE = "https://controlroom-api.onrender.com"
ENDPOINT = f"{API_BASE}/api/debug/scrape"
HEADERS = {
    "Authorization": "Bearer test-token",
    "Content-Type": "application/json"
}
TIMEOUT = 300

BENCHMARK = [
    {"url": "https://www.indarceky.sk/", "email": "podpora@indarceky.sk", "phone": "0222205919", "name": "Rastislav Fiala"},
    {"url": "https://ema-elektro.sk/", "email": "servis@ema-elektro.sk", "phone": "317804046", "name": "Tomáš Konečná"},
    {"url": "https://www.zeniqo.sk/", "email": "eshop@zeniqo.sk", "phone": "908761091", "name": "Peter Šimko"},
    {"url": "https://www.fgym.sk/", "email": "ferenci.ladislav@gmail.com", "phone": "0911489439", "name": "Ladislav Ferenci"},
    {"url": "https://www.domoss.sk/", "email": "marketing@domoss.sk", "phone": "33774800", "name": None},
    {"url": "https://www.stylin.sk/", "email": "info@stylin.sk", "phone": "777592979", "name": "Martin Kašpar"},
    {"url": "https://lomax.sk/", "email": "info@lomax.sk", "phone": "0903768771", "name": None},
    {"url": "https://www.velkykosik.cz/", "email": "info@velkykosik.cz", "phone": "245008200", "name": None},
    {"url": "https://www.zuriel.cz/", "email": "info@zuriel.cz", "phone": "602191636", "name": None},
    {"url": "https://www.fermatshop.sk/", "email": "info@fermatshop.sk", "phone": "918570777", "name": None},
    {"url": "https://www.vsetkonaradie.sk/", "email": "objednavky@vsetkonaradie.sk", "phone": "948255085", "name": "Eduard Slobodnik"},
    {"url": "https://www.profiledziarovky.sk/", "email": "info@profiledziarovky.sk", "phone": "0902248611", "name": None},
    {"url": "https://www.citycomp.sk/", "email": "eshop@citycomp.sk", "phone": "0514525360", "name": None},
    {"url": "https://www.florasystem.sk/", "email": "lukacova@florasystem.sk", "phone": "918521056", "name": None},
    {"url": "https://www.hodiny-na-stenu.sk/", "email": "obchod@hodiny-na-stenu.sk", "phone": "908962505", "name": None},
    {"url": "https://www.pomocnik.sk/", "email": "info@pomocnik.sk", "phone": "0434554433", "name": "Ján Buchanec"},
    {"url": "https://www.stavbaeu.cz/", "email": "info@stavbaeu.cz", "phone": None, "name": None},
    {"url": "https://www.goodio.sk/", "email": "info@goodio.cz", "phone": "266266325", "name": None},
    {"url": "https://www.kokiskashop.cz/", "email": "info@kokiska.cz", "phone": "776150650", "name": None},
    {"url": "https://www.esvit.cz/", "email": "esvit@esvit.cz", "phone": "773977937", "name": None},
    {"url": "https://eshop.globo-lighting.sk/", "email": None, "phone": "0362300225", "name": None},
    {"url": "https://www.megaknihy.sk/", "email": "info@megaknihy.sk", "phone": None, "name": None},
    {"url": "https://www.margaretkashop.sk/", "email": None, "phone": "0948236042", "name": None},
    {"url": "https://www.mpm-time.cz/", "email": "info@mpm-time.cz", "phone": "558441190", "name": None},
    {"url": "https://www.sterix.cz/", "email": "info@sterix.cz", "phone": "604580017", "name": None},
    {"url": "https://www.feim.sk/", "email": "svietidla@feim.sk", "phone": "0347743228", "name": None},
    {"url": "https://www.inlea.sk/", "email": "info@inlea.sk", "phone": "482304811", "name": None},
    {"url": "https://www.tvojregal.sk/", "email": "info@tvojregal.sk", "phone": "905923673", "name": None},
    {"url": "https://www.kidero.sk/", "email": "info@kidero.cz", "phone": "266266325", "name": None},
    {"url": "https://www.harahu.com/", "email": "info@harahu.com", "phone": "918212326", "name": None},
    {"url": "https://www.svet-svitidel.cz/", "email": "helpdesk@svet-svitidel.cz", "phone": "515555111", "name": None},
    {"url": "https://www.pohodlne-nakupy.sk/", "email": "obchod@pohodlne-nakupy.sk", "phone": None, "name": None},
    {"url": "https://www.svet-trampolin.cz/", "email": "info@svet-trampolin.cz", "phone": "775775472", "name": None},
    {"url": "https://www.imago.cz/", "email": "info@imago.cz", "phone": "774421641", "name": None},
    {"url": "https://www.bestbaby.sk/", "email": "info@nejbaby.cz", "phone": "222205982", "name": None},
    {"url": "https://www.nejhracka.cz/", "email": "nejhracka@nejhracka.cz", "phone": "315559688", "name": None},
    {"url": "https://www.medhelp-shop.cz/", "email": "obchod@medhelp-shop.cz", "phone": "325610462", "name": None},
    {"url": "https://www.profimed.eu/", "email": "info@profimed.eu", "phone": "907908316", "name": None},
    {"url": "https://www.pilulka.cz/", "email": "dotazy@pilulka.cz", "phone": "222703000", "name": None},
    {"url": "https://www.holime.eu/", "email": "info@holime.eu", "phone": "380831830", "name": None},
    {"url": "https://www.hairbook.sk/", "email": "info@hairbook.sk", "phone": "948381589", "name": None},
]


DELAY_BETWEEN = 15  # sekúnd medzi requestami — Render free tier (0.5 CPU) padá pod záťažou
MAX_RETRIES = 2     # retry pre 502/503


def norm_phone(p: str) -> str:
    """Normalizuj telefón na holé lokálne číslo pre porovnanie.
    +421908761091 → 908761091, 0911489439 → 911489439, 245008200 → 245008200"""
    if not p:
        return ""
    d = re.sub(r'\D', '', p)
    # Odstráň medzinárodné predvoľby
    if d.startswith('00421'):
        d = d[5:]
    elif d.startswith('00420'):
        d = d[5:]
    elif d.startswith('421') and len(d) >= 12:
        d = d[3:]
    elif d.startswith('420') and len(d) >= 12:
        d = d[3:]
    # Odstráň leading 0 pre SK/CZ (09xx → 9xx, 02xx → 2xx)
    if d.startswith('0') and len(d) == 10:
        d = d[1:]
    return d


def scrape_one(url: str) -> dict:
    row = {"url": url, "email": "", "phone": "", "name": "", "error": ""}
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            resp = requests.post(ENDPOINT, json={"url": url}, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code in (502, 503) and attempt <= MAX_RETRIES:
                print(f"  HTTP {resp.status_code}, retry {attempt}...", end=" ", flush=True)
                time.sleep(30)
                continue
            if resp.status_code != 200:
                row["error"] = f"HTTP {resp.status_code}"
                return row
            data = resp.json()
            ai = data.get("ai_extracted") or {}
            fb = data.get("regex_fallback") or {}
            row["email"] = ai.get("email") or fb.get("email") or ""
            row["phone"] = ai.get("phone") or fb.get("phone") or ""
            row["name"] = ai.get("contact_name") or ""
            return row
        except requests.exceptions.Timeout:
            if attempt <= MAX_RETRIES:
                print(f"  TIMEOUT, retry {attempt}...", end=" ", flush=True)
                time.sleep(30)
                continue
            row["error"] = "TIMEOUT"
        except Exception as e:
            row["error"] = str(e)[:80]
            break
    return row


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"=== BENCHMARK TEST: {len(BENCHMARK)} URLs ===")
    print(f"Endpoint: {ENDPOINT}")
    print(f"Timeout: {TIMEOUT}s\n")

    # Wake-up ping
    print("Ping health...", end=" ", flush=True)
    try:
        r = requests.get(f"{API_BASE}/health", timeout=90)
        print(f"OK ({r.status_code})")
    except Exception as e:
        print(f"WARN: {e}")

    results = []
    total_start = time.time()

    for i, bench in enumerate(BENCHMARK, 1):
        url = bench["url"]
        print(f"\n>>> [{i}/{len(BENCHMARK)}] {url} ...", end=" ", flush=True)
        t0 = time.time()
        row = scrape_one(url)
        elapsed = time.time() - t0
        print(f"{elapsed:.1f}s", flush=True)
        results.append((bench, row))
        if i < len(BENCHMARK):
            time.sleep(DELAY_BETWEEN)

    total_elapsed = time.time() - total_start

    # === Porovnanie ===
    email_ok = 0
    phone_ok = 0
    name_ok = 0
    email_total = 0
    phone_total = 0
    name_total = 0

    print(f"\n{'='*130}")
    print(f"{'URL':<28} {'Exp Email':<32} {'Got Email':<32} {'E':>1} {'Exp Phone':<14} {'Got Phone':<14} {'P':>1}")
    print(f"{'-'*130}")

    for bench, row in results:
        url_short = bench["url"].replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")[:26]
        exp_email = bench.get("email") or ""
        got_email = row.get("email") or ""
        exp_phone = bench.get("phone") or ""
        got_phone = norm_phone(row.get("phone") or "")

        e_match = "✓" if exp_email and got_email.lower() == exp_email.lower() else ("−" if not exp_email else "✗")
        p_match = "✓" if exp_phone and got_phone == norm_phone(exp_phone) else ("−" if not exp_phone else "✗")

        if exp_email:
            email_total += 1
            if got_email.lower() == exp_email.lower():
                email_ok += 1
        if exp_phone:
            phone_total += 1
            if got_phone == norm_phone(exp_phone):
                phone_ok += 1

        err = row.get("error", "")
        if err:
            got_email = f"[{err}]"

        print(f"{url_short:<28} {exp_email:<32} {got_email:<32} {e_match:>1} {exp_phone:<14} {got_phone:<14} {p_match:>1}")

    print(f"{'='*130}")
    print(f"\nEmaily: {email_ok}/{email_total} správnych ({100*email_ok/max(email_total,1):.0f}%)")
    print(f"Telefóny: {phone_ok}/{phone_total} správnych ({100*phone_ok/max(phone_total,1):.0f}%)")
    print(f"Čas celkom: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")

    if email_ok >= 30:
        print(f"\n🎯 CIEĽ DOSIAHNUTÝ: {email_ok}/{email_total} emailov!")
    else:
        print(f"\n⚠️ CIEĽ NEDOSIAHNUTÝ: treba {30 - email_ok} ďalších emailov")

    # CSV export
    csv_path = "benchmark_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["url", "exp_email", "got_email", "email_ok", "exp_phone", "got_phone", "phone_ok", "error"])
        for bench, row in results:
            exp_e = bench.get("email") or ""
            got_e = row.get("email") or ""
            exp_p = bench.get("phone") or ""
            got_p = norm_phone(row.get("phone") or "")
            e_ok = "1" if exp_e and got_e.lower() == exp_e.lower() else "0"
            p_ok = "1" if exp_p and got_p == norm_phone(exp_p) else "0"
            writer.writerow([bench["url"], exp_e, got_e, e_ok, exp_p, got_p, p_ok, row.get("error", "")])
    print(f"CSV uložený: {csv_path}")


if __name__ == "__main__":
    main()
