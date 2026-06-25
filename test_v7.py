"""
v7 benchmark test — spusti po naplnení benchmark_groundtruth.csv

Použitie:
    python test_v7.py [--url http://localhost:8000] [--csv benchmark_groundtruth.csv]

Stĺpce CSV:
    url, konatel_meno, ocakavany_tier
"""
import csv
import json
import re
import sys
import argparse
import unicodedata
import requests


def _deaccent(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def run(base_url: str, csv_path: str):
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results = []
    for i, row in enumerate(rows, 1):
        url = row["url"].strip()
        full_url = url if url.startswith("http") else f"https://{url}"
        print(f"[{i}/{len(rows)}] {url} ...", end=" ", flush=True)

        try:
            r = requests.post(
                f"{base_url}/api/leads/scrape",
                json={"url": full_url},
                headers={"Authorization": "Bearer test-token"},
                timeout=120,
            )
            data = r.json()
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"url": url, "error": str(e)})
            continue

        expected_name = row.get("expected_name", "").strip().lower()
        pc = data.get("primary_contact") or {}
        got_name = (pc.get("name") or "").lower()
        if not expected_name:
            name_match = True  # not tracked → skip
        else:
            name_match = _deaccent(expected_name) in _deaccent(got_name)

        expected_tier = row.get("expected_tier", "").strip()
        got_tier = data.get("tier", "")
        tier_match = expected_tier == got_tier

        registry = data.get("registry") or {}
        registry_verified = registry.get("verified", False)

        print(
            f"name={'OK' if name_match else 'FAIL'} "
            f"tier={'OK' if tier_match else f'FAIL({got_tier})'} "
            f"reg={'OK' if registry_verified else 'FAIL'}"
        )

        results.append({
            "url": url,
            "name_match": name_match,
            "tier_match": tier_match,
            "expected": {"name": expected_name, "tier": expected_tier},
            "got": {"name": got_name, "tier": got_tier},
            "expected_phone": row.get("expected_phone", ""),
            "expected_role": row.get("expected_role", ""),
            "registry_verified": registry_verified,
            "registry_konatel": registry.get("konatel"),
            "score": data.get("score"),
            "confidence": data.get("confidence"),
            "reasoning": data.get("reasoning", []),
        })

    total = len(results)
    valid = [r for r in results if "error" not in r]
    n = len(valid)

    print(f"\n{'='*50}")
    print(f"Name match:       {sum(r['name_match'] for r in valid)}/{n}")
    print(f"Tier match:       {sum(r['tier_match'] for r in valid)}/{n}")
    print(f"Registry verified:{sum(r['registry_verified'] for r in valid)}/{n}")
    print(f"Errors:           {total - n}/{total}")
    print(f"{'='*50}")
    print("Targets: name>=80%, tier>=75%, registry>=90%")

    out_path = "benchmark_v7_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nDetaily: {out_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--csv", default="benchmark_v2.csv")
    args = p.parse_args()
    run(args.url, args.csv)
