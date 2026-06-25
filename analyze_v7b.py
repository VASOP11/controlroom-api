import json

with open("benchmark_v7_results.json", encoding="utf-8") as f:
    d = json.load(f)

sites = ["tuli.sk", "dekorbymirka.sk", "citycomp.sk", "zeniqo.sk", "indarceky.sk"]
for r in d:
    if r["url"] not in sites:
        continue
    print(f"\n=== {r['url']} ===")
    print(f"  exp: {r['expected']}  got: {r['got']}  score={r.get('score')}  reg={r.get('registry_konatel')}")
    print(f"  reasoning:")
    for line in (r.get("reasoning") or []):
        print(f"    {line}")
