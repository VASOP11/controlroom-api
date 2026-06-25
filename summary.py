import csv, re

with open('benchmark_v6.15_results.csv', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

ok = [r for r in rows if r['status']=='OK']
err = [r for r in rows if r['status']=='ERROR']
em = [r for r in ok if r['email_match'] in ('Y','N')]
ph = [r for r in ok if r['phone_match'] in ('Y','N')]
mn = [r for r in ok if r['meno_match'] in ('Y','N')]
gl = [r for r in ok if r['golden_link'] in ('Y','N')]

def pct(n,d): return str(n)+'/'+str(d)+' ('+str(100*n//d if d else 0)+'%)'

print('='*55)
print('Spracovane: '+str(len(ok))+'/'+str(len(rows))+'  (ERROR: '+str(len(err))+')')
print('-- HLAVNE METRIKY --')
print('Telefon: '+pct(sum(1 for r in ph if r["phone_match"]=="Y"), len(ph)))
print('Email:   '+pct(sum(1 for r in em if r["email_match"]=="Y"), len(em)))
print('-- GOLDEN --')
print('Meno najdene:   '+pct(sum(1 for r in mn if r["meno_match"]=="Y"), len(mn)))
print('Meno + telefon: '+pct(sum(1 for r in gl if r["golden_link"]=="Y"), len(gl)))
print('='*55)
print('ERRORS:')
for r in err: print('  '+r["url"]+' | '+r["error_reason"][:80])
print('TELEFON miss:')
for r in ph:
    if r["phone_match"]=="N": print('  '+r["url"]+' | GT: '+r["gt_phone"]+' | nasli: '+r["found_phones"])
print('MENO miss:')
for r in mn:
    if r["meno_match"]=="N": print('  '+r["url"]+' | GT: '+r["gt_meno"]+' | nasli: '+r["found_osoby"][:80])
