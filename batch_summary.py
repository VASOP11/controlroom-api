import csv, collections

rows = list(csv.DictReader(open('batch_300_results.csv', encoding='utf-8-sig')))
ok  = [r for r in rows if r['status'] == 'OK']
err = [r for r in rows if r['status'] != 'OK']

jur       = collections.Counter(r['jurisdiction'] for r in ok)
has_email = sum(1 for r in ok if r['found_emails'])
has_phone = sum(1 for r in ok if r['found_phones'])
has_osoba = sum(1 for r in ok if r['found_osoby'])
has_ico   = sum(1 for r in ok if r['ico'])

print("=== BATCH 344 - FINAL SUMMARY ===")
print(f"Total:   {len(rows)}")
print(f"OK:      {len(ok)}")
print(f"ERROR:   {len(err)}")
print()
print("--- Najdene data (z OK) ---")
print(f"Email:   {has_email}/{len(ok)} ({100*has_email//len(ok)}%)")
print(f"Telefon: {has_phone}/{len(ok)} ({100*has_phone//len(ok)}%)")
print(f"Osoba:   {has_osoba}/{len(ok)} ({100*has_osoba//len(ok)}%)")
print(f"ICO:     {has_ico}/{len(ok)} ({100*has_ico//len(ok)}%)")
print()
print("--- Jurisdikcia ---")
for k, v in sorted(jur.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")
print()
print("--- ERRORy ---")
for r in err:
    print(f"  {r['url']} | {r['error_reason'][:80]}")
