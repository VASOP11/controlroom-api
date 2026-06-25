import json

with open("benchmark_v7_results.json", encoding="utf-8") as f:
    d = json.load(f)

print(f"{'URL':30s} {'exp':4s} {'got':4s} {'sc':3s} | {'exp_name':20s} | {'got_name':20s} | {'reg_konatel':20s} | reasoning_last")
print("-" * 140)
for r in d:
    exp_t = r["expected"]["tier"]
    got_t = r["got"]["tier"]
    exp_n = r["expected"]["name"]
    got_n = r["got"]["name"]
    reg = str(r.get("registry_konatel") or "")
    score = str(r.get("score") or "")
    reasons = r.get("reasoning", [])
    last = reasons[-1] if reasons else ""
    ok = "OK" if r.get("tier_match") and r.get("name_match") else "  "
    print(f"{r['url']:30s} {exp_t:4s} {got_t:4s} {score:3s} | {exp_n[:20]:20s} | {got_n[:20]:20s} | {reg[:20]:20s} | {last[:60]}")

print()
print("Name matches:")
for r in d:
    if r.get("name_match"):
        print(f"  OK  {r['url']:30s} exp={r['expected']['name']} got={r['got']['name']}")
