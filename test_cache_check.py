import json

with open("registry_cache.json", "r", encoding="utf-8") as f:
    cache = json.load(f)

sk_keys = [k for k in cache.keys() if k.startswith("sk_")]
print(f"SK entries: {len(sk_keys)}")
for k in sk_keys:
    v = cache[k]
    d = v.get("data", {})
    kon = d.get("konatelia", [])
    meno = d.get("obchodne_meno", "?")
    print(f"  {k}: {meno} | konatelia={len(kon)} | found={d.get('found')}")

# Vymaz SK cache entries aby sa urobil fresh lookup
print("\nMazem SK cache entries...")
for k in sk_keys:
    del cache[k]
with open("registry_cache.json", "w", encoding="utf-8") as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)
print(f"Vymazanych: {len(sk_keys)} SK entries")
