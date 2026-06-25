import csv, random
random.seed(42)

rows = [r for r in csv.DictReader(open('batch_300_results.csv', encoding='utf-8-sig'))
        if r['status'] == 'OK']

sk_osoba    = [r for r in rows if r['jurisdiction'] == 'SK' and r['found_osoby'].strip()]
sk_no_osoba = [r for r in rows if r['jurisdiction'] == 'SK' and not r['found_osoby'].strip()]
cz          = [r for r in rows if r['jurisdiction'] == 'CZ']

sel = (random.sample(sk_osoba, 7) +
       random.sample(sk_no_osoba, 7) +
       random.sample(cz, 6))

def t(s, n):
    return (s[:n] + '...') if len(s) > n else s

hdr = f"{'URL':<45} | {'found_emails':<32} | {'found_phones':<22} | {'found_osoby':<42} | jur"
print(hdr)
print('-' * len(hdr))
for r in sel:
    url   = t(r['url'], 44)
    email = t(r['found_emails'], 31)
    phone = t(r['found_phones'], 21)
    osoba = t(r['found_osoby'], 41)
    jur   = r['jurisdiction']
    print(f"{url:<45} | {email:<32} | {phone:<22} | {osoba:<42} | {jur}")
