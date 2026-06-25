"""
Test scoring engine — validate score calculation and tier assignment.
Requires server running on localhost:8000.
"""
import asyncio
import httpx
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_URL = os.getenv("API_URL", "http://localhost:8000")
TOKEN = os.getenv("API_TOKEN", "test-token")

TEST_CASES = [
    {
        "name": "minilove.sk — HOT (85 bodov)",
        "payload": {
            "url": "https://www.minilove.sk/",
            "selected": {
                "meno": "Erika Blíziková",
                "rola": "konateľ",
                "telefon": "+421 903 928 140",
                "email": "info@minilove.sk",
            },
            "metadata": {
                "zdroj": "orsr",
                "phone_type": "personal",
                "registry_konatelia": [{"meno": "Erika Blíziková"}],
                "registry_source": "orsr",
            },
        },
        "expected_score_min": 80,
        "expected_tier": "HOT",
    },
    {
        "name": "elmishop.sk — WARM (registry + info tel, no name match)",
        "payload": {
            "url": "https://elmishop.sk/",
            "selected": {
                "meno": "Erika Matulová",
                "rola": "konateľ",
                "telefon": "+421 907 581 791",
                "email": "info@elmishop.sk",
            },
            "metadata": {
                "zdroj": "orsr",
                "phone_type": "info",
                "registry_konatelia": [{"meno": "Ján Novák"}],
                "registry_source": "orsr",
            },
        },
        "expected_score_min": 60,
        "expected_tier": "WARM",
    },
    {
        "name": "sedooz.sk — WARM (60-79 bodov) — info tel, no name match",
        "payload": {
            "url": "https://www.sedooz.sk/",
            "selected": {
                "meno": "Peter Ďurák",
                "rola": "konateľ",
                "telefon": "+421904530656",
                "email": "sedooz@sedooz.sk",
            },
            "metadata": {
                "zdroj": "orsr",
                "phone_type": "info",
                "registry_konatelia": [{"meno": "Ján Novák"}],
                "registry_source": "orsr",
            },
        },
        "expected_score_min": 60,
        "expected_tier": "WARM",
    },
    {
        "name": "unknown-shop.sk — DEAD (no registry, info phone only)",
        "payload": {
            "url": "https://unknown-shop.sk/",
            "selected": {
                "meno": "Neznámy",
                "rola": None,
                "telefon": "+421 900 000 000",
                "email": "info@unknown-shop.sk",
            },
            "metadata": {
                "zdroj": "web",
                "phone_type": "info",
                "registry_konatelia": [],
                "registry_source": None,
            },
        },
        "expected_score_min": 0,
        "expected_tier": "DEAD",
    },
]


async def run_test(client: httpx.AsyncClient, test_case: dict) -> bool:
    name = test_case["name"]
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    try:
        r = await client.post(
            f"{API_URL}/api/leads/select",
            json=test_case["payload"],
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=30,
        )

        if r.status_code != 200:
            print(f"  ERROR {r.status_code}: {r.text[:300]}")
            return False

        data = r.json()
        score = data.get("score", {}).get("total", 0)
        tier = data.get("tier", {}).get("name", "?")

        score_ok = score >= test_case["expected_score_min"]
        tier_ok = tier == test_case["expected_tier"]

        s_icon = "PASS" if score_ok else "FAIL"
        t_icon = "PASS" if tier_ok else "FAIL"

        print(f"  Score: [{s_icon}] {score}/100 (expected >= {test_case['expected_score_min']})")
        print(f"  Tier:  [{t_icon}] {tier} (expected {test_case['expected_tier']})")

        breakdown = data.get("score", {}).get("breakdown", "")
        if breakdown:
            print(f"\n  Breakdown:")
            for line in breakdown.split("\n"):
                if line.strip():
                    print(f"    {line}")

        action_note = data.get("action_note", "")
        if action_note:
            print(f"\n  Action Note:")
            for line in action_note.split("\n"):
                if line.strip():
                    print(f"    {line}")

        return score_ok and tier_ok

    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return False


async def main():
    print("\n" + "=" * 60)
    print("  SCORING ENGINE TEST")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        results = []
        for tc in TEST_CASES:
            result = await run_test(client, tc)
            results.append(result)

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"  SUMMARY: {passed}/{total} passed")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
