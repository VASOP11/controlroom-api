import csv

old = {}
with open('benchmark_v6.15_results.csv', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        old[r['url']] = r

new = {}
with open('benchmark_v6.15_final.csv', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        new[r['url']] = r

zhoršené = []
zlepšené = []

for url in old:
    if url not in new:
        continue
    o, n = old[url], new[url]

    # Porovnaj email, phone, meno
    for metrika in ['email_match', 'phone_match', 'meno_match']:
        if o.get(metrika) == 'Y' and n.get(metrika) == 'N':
            zhoršené.append(f"{url} | {metrika}: Y→N")
        elif o.get(metrika) == 'N' and n.get(metrika) == 'Y':
            zlepšené.append(f"{url} | {metrika}: N→Y")

print(f"ZHORŠENÉ: {len(zhoršené)}")
for z in zhoršené: print(f"  {z}")
print(f"ZLEPŠENÉ: {len(zlepšené)}")
for z in zlepšené[:10]: print(f"  {z}")
