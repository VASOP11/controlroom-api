"""
batch_run.py — hromadný scraper bez ground truth
Vstup:  batch_300.txt (jeden URL per riadok)
Výstup: batch_300_results.csv
Log:    batch_300_log.txt (append)
"""
import asyncio, csv, os, re, time
import concurrent.futures

os.environ["FORCE_PLAYWRIGHT"] = os.environ.get("FORCE_PLAYWRIGHT", "0")

from main import (
    _scrape_all_pages,
    _extract_cisla_ico,
    associate_persons_with_roles,
    extract_all_candidates,
    detect_jurisdiction,
)

IN_FILE   = "batch_300.txt"
OUT_FILE  = "batch_300_results.csv"
LOG_FILE  = "batch_300_log.txt"

TIMEOUT      = 80    # asyncio.wait_for timeout
HARD_TIMEOUT = 100   # ThreadPoolExecutor záchranná sieť
PROGRESS_EVERY = 10  # výpis každých N URL

FIELDNAMES = [
    "url", "status", "found_emails", "found_phones",
    "found_osoby", "ico", "jurisdiction", "error_reason",
]


# ── helpers ────────────────────────────────────────────────────────────────

def _log(msg: str, log_fh):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_fh.write(line + "\n")
    log_fh.flush()


def _sync_scrape(url: str):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            asyncio.wait_for(_scrape_all_pages(url), timeout=TIMEOUT)
        )
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()


def _error_row(url: str, reason: str) -> dict:
    return {
        "url": url, "status": "ERROR",
        "found_emails": "", "found_phones": "",
        "found_osoby": "", "ico": "", "jurisdiction": "",
        "error_reason": reason[:200],
    }


# ── main beh ───────────────────────────────────────────────────────────────

async def run_one(url: str) -> dict:
    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = loop.run_in_executor(executor, _sync_scrape, url)
        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=HARD_TIMEOUT)
        except asyncio.TimeoutError:
            future.cancel()
            executor.shutdown(wait=False)
            return _error_row(url, f"HARD_TIMEOUT_{HARD_TIMEOUT}s")
    except Exception as e:
        executor.shutdown(wait=False)
        return _error_row(url, str(e)[:200])
    finally:
        executor.shutdown(wait=False)

    try:
        combined  = result.get("text", "") if isinstance(result, dict) else ""
        jsonld    = result.get("jsonld", {}) if isinstance(result, dict) else {}

        norm_text = re.sub(r'\n+', ' ', combined.replace('\xa0', ' '))
        norm_text = re.sub(r' {2,}', ' ', norm_text)

        candidates = extract_all_candidates(combined)

        # Emaily
        seen_e, emails_out = set(), []
        if jsonld.get("email"):
            v = jsonld["email"].strip().lower()
            seen_e.add(v); emails_out.append(jsonld["email"].strip())
        for e in candidates.get("emails", []):
            k = e["value"].lower()
            if k not in seen_e:
                seen_e.add(k); emails_out.append(e["value"])

        # Telefóny + IČO
        cisla_out, ico_out = _extract_cisla_ico(
            candidates, norm_text, jsonld_phone=jsonld.get("phone")
        )
        phones_out = [c["cislo"] for c in cisla_out]
        ico_val    = ico_out[0] if ico_out else ""

        # Osoby — prvá osoba ako "meno|rola|conf"
        osoby = associate_persons_with_roles(combined)
        if osoby:
            o = osoby[0]
            found_osoby = f"{o.get('meno','?')}|{o.get('rola') or ''}|{o.get('confidence', 0)}"
        else:
            found_osoby = ""

        # Jurisdikcia
        jur_dict     = detect_jurisdiction(combined, url)
        jurisdiction = jur_dict.get("jurisdiction", "UNKNOWN")

        return {
            "url":          url,
            "status":       "OK",
            "found_emails": ", ".join(emails_out[:5]),
            "found_phones": ", ".join(phones_out[:5]),
            "found_osoby":  found_osoby,
            "ico":          ico_val,
            "jurisdiction": jurisdiction,
            "error_reason": "",
        }

    except Exception as e:
        return _error_row(url, str(e)[:200])


async def main():
    # Načítaj URL zoznam
    with open(IN_FILE, encoding="utf-8") as f:
        urls_raw = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    urls = []
    for u in urls_raw:
        if not u.startswith("http"):
            u = "https://" + u
        urls.append(u)

    total = len(urls)

    # Zisti, ktoré URL už sú v CSV (resume podpora)
    done_urls: set = set()
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("url"):
                    done_urls.add(row["url"])

    write_header = not os.path.exists(OUT_FILE) or os.path.getsize(OUT_FILE) == 0

    with open(LOG_FILE, "a", encoding="utf-8") as log_fh, \
         open(OUT_FILE, "a", encoding="utf-8-sig", newline="") as csv_fh:

        writer = csv.DictWriter(csv_fh, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()

        _log(f"START — {total} URL celkom, {len(done_urls)} už spracovaných", log_fh)

        ok_count = err_count = 0

        for i, url in enumerate(urls, 1):
            if url in done_urls:
                if i % PROGRESS_EVERY == 0:
                    _log(f"[{i}/{total}] SKIP (already done): {url}", log_fh)
                continue

            domain = re.sub(r'^https?://(www\.)?', '', url).split('/')[0]
            t0 = time.time()
            res = await run_one(url)
            elapsed = time.time() - t0

            status = res["status"]
            if status == "OK":
                ok_count += 1
            else:
                err_count += 1

            writer.writerow(res)
            csv_fh.flush()

            if i % PROGRESS_EVERY == 0 or i == total:
                _log(
                    f"[{i}/{total}] {domain} -> {status} ({elapsed:.1f}s) "
                    f"| OK={ok_count} ERR={err_count}",
                    log_fh,
                )

    print(f"\nHotovo. OK={ok_count}, ERROR={err_count}, CSV={OUT_FILE}", flush=True)


asyncio.run(main())
