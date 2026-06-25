import asyncio, csv, os, re, time, unicodedata
import concurrent.futures
os.environ["FORCE_PLAYWRIGHT"] = "1"
from main import _scrape_all_pages, _extract_cisla_ico, associate_persons_with_roles, extract_all_candidates

GT_FILE = "ground_truth.csv"
OUT_FILE = "benchmark_v6.15_final.csv"

# ── OPRAVA 2: Resume od indexu (0-based). 0 = spusti od začiatku. ──
# 32 = preskočí prvých 32 riadkov, začne od riadku 33 (medikament.sk)
START_FROM = 9

TIMEOUT = 60          # asyncio.wait_for timeout pre _scrape_all_pages
HARD_TIMEOUT = 100    # ThreadPoolExecutor hard-kill záchranná sieť

# ── Normalizácia ────────────────────────────────────────────
def norm_email(e): return e.lower().strip()

def norm_phone(p):
    d = re.sub(r'\D', '', p)
    for pfx in ('00421','00420','421','420'):
        if d.startswith(pfx):
            d = d[len(pfx):]
            break
    return d.lstrip('0')

def norm_name(n):
    n = n.lower()
    n = ''.join(c for c in unicodedata.normalize('NFKD', n)
                if unicodedata.category(c) != 'Mn')
    n = re.sub(r'\b(ing|mgr|mvdr|judr|phdr|rndr|mudr|paeddr|dr|bc|prof|doc)\.?\s*', '', n)
    return re.sub(r'\s+', ' ', n).strip()

def split_gt(val):
    return [v.strip() for v in re.split(r'[,;]+', val or '') if v.strip()]

# ── Porovnanie ───────────────────────────────────────────────
def match_email(gt_list, found_list):
    gt_n = {norm_email(e) for e in gt_list}
    found_n = {norm_email(e) for e in found_list}
    return 'Y' if gt_n & found_n else 'N'

def match_phone(gt_list, found_list):
    gt_n = {norm_phone(p) for p in gt_list if re.search(r'\d{6}', p)}
    found_n = {norm_phone(p) for p in found_list if re.search(r'\d{6}', p)}
    return 'Y' if gt_n & found_n else 'N'

def match_name(gt_name, osoby_list):
    if not gt_name: return ''
    gn = norm_name(gt_name)
    for o in osoby_list:
        on = norm_name(o.get('meno',''))
        if gn in on or on in gn:
            return 'Y'
    return 'N'

def match_rola(gt_rola, osoby_list, gt_name):
    GENERIC = {'info','inf','inof','ifno','eshop','obchod','objednavky',
               'podpora','objednavky reklamacie',''}
    if (gt_rola or '').lower() in GENERIC: return ''
    gn = norm_name(gt_name or '')
    for o in osoby_list:
        if gn and (gn in norm_name(o.get('meno','')) or
                   norm_name(o.get('meno','')) in gn):
            return 'Y' if o.get('rola') else 'N'
    return 'N'

def match_golden(gt_phone_list, gt_name, osoby_list, cisla_list):
    if not gt_name: return ''
    gn = norm_name(gt_name)
    matched_osoba = None
    for o in osoby_list:
        on = norm_name(o.get('meno',''))
        if gn in on or on in gn:
            matched_osoba = o
            break
    if not matched_osoba: return ''
    gt_n = {norm_phone(p) for p in gt_phone_list if re.search(r'\d{6}', p)}
    for cislo in cisla_list:
        cn = norm_phone(cislo.get('cislo',''))
        if cn in gt_n:
            ctx = (cislo.get('kontext') or '').lower()
            meno_lower = matched_osoba.get('meno','').lower()
            if any(part in ctx for part in meno_lower.split() if len(part) > 3):
                return 'Y'
    return 'N'

# ── Core scrape logika (sync wrapper pre ThreadPoolExecutor) ──
def _sync_scrape(url):
    """Spustí _scrape_all_pages vo vlastnom event loope v threade."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            asyncio.wait_for(_scrape_all_pages(url), timeout=TIMEOUT)
        )
    finally:
        try:
            # Zruš pending tasky pred zatvorením loopu
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            pass
        loop.close()

# ── Hlavný beh jednej URL ───────────────────────────────────
async def run_one(row):
    url = row['url']
    if not url.startswith('http'):
        url = 'https://' + url

    def _error(reason):
        return {
            'url': url, 'status': 'ERROR', 'error_reason': reason[:120],
            'gt_email': row.get('emails',''), 'found_emails': '', 'email_match': '',
            'gt_phone': row.get('telefon',''), 'found_phones': '', 'phone_match': '',
            'gt_meno': row.get('meno',''), 'found_osoby': '', 'meno_match': '',
            'gt_rola': row.get('rola',''), 'found_rola': '', 'rola_match': '',
            'golden_link': ''
        }

    # OPRAVA 4: ThreadPoolExecutor ako záchranná sieť —
    # keď asyncio.wait_for nezastaví Playwright na Windowse,
    # executor.shutdown(wait=False) + future.cancel() ukončí thread.
    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = loop.run_in_executor(executor, _sync_scrape, url)
        try:
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout=HARD_TIMEOUT
            )
        except asyncio.TimeoutError:
            future.cancel()
            executor.shutdown(wait=False)
            print(f"  [HARD_TIMEOUT {HARD_TIMEOUT}s] {url}", flush=True)
            return _error(f'HARD_TIMEOUT_{HARD_TIMEOUT}s')
    except Exception as e:
        executor.shutdown(wait=False)
        return _error(str(e))
    finally:
        executor.shutdown(wait=False)

    try:
        combined = result.get('text', '') if isinstance(result, dict) else ''
        jsonld_data = result.get('jsonld', {}) if isinstance(result, dict) else {}

        norm_text = combined.replace('\xa0', ' ')
        norm_text = re.sub(r'\n+', ' ', norm_text)
        norm_text = re.sub(r' {2,}', ' ', norm_text)

        candidates = extract_all_candidates(combined)
        cisla_out, ico_out = _extract_cisla_ico(
            candidates, norm_text, jsonld_phone=jsonld_data.get('phone')
        )

        # Emaily z candidates + jsonld
        emails_found = []
        seen_e = set()
        if jsonld_data.get('email'):
            e_val = jsonld_data['email'].strip().lower()
            if e_val not in seen_e:
                seen_e.add(e_val)
                emails_found.append(jsonld_data['email'].strip())
        for entry in candidates.get('emails', []):
            k = entry['value'].lower()
            if k not in seen_e:
                seen_e.add(k)
                emails_found.append(entry['value'])

        cisla = [{'cislo': c['cislo'], 'kontext': c.get('kontext', '')}
                 for c in cisla_out]
        osoby = associate_persons_with_roles(combined)

        gt_emails = split_gt(row.get('emails',''))
        gt_phones = split_gt(row.get('telefon',''))
        gt_meno = (row.get('meno') or '').strip()
        gt_rola = (row.get('rola') or '').strip()

        em = match_email(gt_emails, emails_found) if gt_emails else ''
        ph = match_phone(gt_phones, [c['cislo'] for c in cisla]) if gt_phones else ''
        mn = match_name(gt_meno, osoby) if gt_meno else ''
        rl = match_rola(gt_rola, osoby, gt_meno)
        gl = match_golden(gt_phones, gt_meno, osoby, cisla)

        found_osoby_str = ' | '.join(
            f"{o.get('meno','?')} ({o.get('rola') or 'bez roly'}, conf={o.get('confidence',0)})"
            for o in osoby[:5])

        return {
            'url': url, 'status': 'OK', 'error_reason': '',
            'gt_email': ', '.join(gt_emails), 'found_emails': ', '.join(emails_found[:5]),
            'email_match': em,
            'gt_phone': ', '.join(gt_phones),
            'found_phones': ', '.join(c['cislo'] for c in cisla[:5]),
            'phone_match': ph,
            'gt_meno': gt_meno, 'found_osoby': found_osoby_str, 'meno_match': mn,
            'gt_rola': gt_rola, 'found_rola': '', 'rola_match': rl,
            'golden_link': gl
        }
    except Exception as e:
        return _error(str(e))


async def main():
    with open(GT_FILE, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    fieldnames = ['url','status','error_reason','gt_email','found_emails','email_match',
                  'gt_phone','found_phones','phone_match','gt_meno','found_osoby',
                  'meno_match','gt_rola','found_rola','rola_match','golden_link']

    # OPRAVA 3: append ak resumujeme, write ak od začiatku
    file_mode = 'a' if START_FROM > 0 else 'w'
    write_header = (START_FROM == 0)

    print(f"START_FROM={START_FROM} -> {'RESUME (append)' if START_FROM > 0 else 'FRESH RUN'}", flush=True)

    results = []
    with open(OUT_FILE, file_mode, encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        for i, row in enumerate(rows, 1):
            # OPRAVA 2: preskočiť spracované riadky
            if i <= START_FROM:
                print(f"[{i}/{len(rows)}] SKIP", flush=True)
                continue

            domain = re.sub(r'^https?://(www\.)?', '', row['url']).split('/')[0]
            print(f"[{i}/{len(rows)}] {domain} ...", flush=True)
            t0 = time.time()
            res = await run_one(row)
            elapsed = time.time() - t0
            print(f"  -> {res['status']} ({elapsed:.1f}s)", flush=True)
            writer.writerow(res)
            f.flush()
            results.append(res)

    # ── SÚHRN ────────────────────────────────────────────────
    ok = [r for r in results if r['status'] == 'OK']
    errors = [r for r in results if r['status'] != 'OK']

    def pct(n, d): return f"{n}/{d} ({100*n//d if d else 0}%)"

    em_rows = [r for r in ok if r['email_match'] in ('Y', 'N')]
    ph_rows = [r for r in ok if r['phone_match'] in ('Y', 'N')]
    mn_rows = [r for r in ok if r['meno_match'] in ('Y', 'N')]
    gl_rows = [r for r in ok if r['golden_link'] in ('Y', 'N')]

    processed = len(rows) - START_FROM
    print("\n" + "="*55)
    print(f"Tento beh: {len(ok)+len(errors)}/{processed}  (OK: {len(ok)}, ERROR: {len(errors)})")
    if START_FROM > 0:
        print(f"(Preskocene: {START_FROM} riadkov — resume mod)")
    print("-- HLAVNE METRIKY (tento beh) --")
    print(f"Telefon: {pct(sum(1 for r in ph_rows if r['phone_match']=='Y'), len(ph_rows))}")
    print(f"Email:   {pct(sum(1 for r in em_rows if r['email_match']=='Y'), len(em_rows))}")
    print("-- GOLDEN --")
    print(f"Meno najdene:   {pct(sum(1 for r in mn_rows if r['meno_match']=='Y'), len(mn_rows))}")
    print(f"Meno + telefon: {pct(sum(1 for r in gl_rows if r['golden_link']=='Y'), len(gl_rows))}")
    print("="*55)

    if errors:
        print("\n[ERROR weby]")
        for r in errors:
            print(f"  {r['url']} | {r['error_reason']}")

    ph_miss = [r for r in ph_rows if r['phone_match'] == 'N']
    if ph_miss:
        print("\n[TELEFON miss]")
        for r in ph_miss:
            print(f"  {r['url']} | GT: {r['gt_phone']} | nasli: {r['found_phones']}")

    mn_miss = [r for r in mn_rows if r['meno_match'] == 'N']
    if mn_miss:
        print("\n[MENO miss]")
        for r in mn_miss:
            print(f"  {r['url']} | GT: {r['gt_meno']} | nasli: {r['found_osoby']}")


asyncio.run(main())
