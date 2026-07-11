# -*- coding: utf-8 -*-
"""Selfcheck v8 case-based scoring matice — spusti: python test_v8_scoring.py"""
from scoring import calculate_lead_score


def case(mc, **kw):
    d = {"match_case": mc, "size_bucket": kw.pop("bucket", "10+")}
    d.update(kw)
    return calculate_lead_score(d)


# tiny: 80-100
r = case("tiny_any_phone", bucket="1-3", name_found_on_web=False, phone_quality=2)
assert 80 <= r["score"] <= 100, r
r2 = case("tiny_any_phone", bucket="1-3", name_found_on_web=True, phone_quality=5)
assert r2["score"] > r["score"]

# small_match: 70-90 podľa vzdialenosti
assert case("small_match", bucket="4-9", proximity_chars=0)["score"] == 90
assert case("small_match", bucket="4-9", proximity_chars=300)["score"] == 70
assert case("small_match", bucket="4-9", proximity_chars=150)["score"] == 80

# small_no_match: 60-80
r = case("small_no_match", bucket="4-9", phone_quality=1)
assert 60 <= r["score"] <= 80, r

# large_name_near: 80-100
assert case("large_name_near", proximity_chars=0)["score"] == 100
assert case("large_name_near", proximity_chars=100)["score"] == 80

# large_name_far_role: 30-60
assert 30 <= case("large_name_far_role", phone_quality=4)["score"] <= 60
assert 30 <= case("large_name_far_role", phone_quality=2)["score"] <= 60

# large_role_only: 50-75
assert 50 <= case("large_role_only", phone_quality=4)["score"] <= 75

# large_info_only: 25-50
assert 25 <= case("large_info_only")["score"] <= 50
assert 25 <= case("large_info_only", name_found_on_web=True, email_type="personal")["score"] <= 50

# vop_alt_phone: 40-70
assert 40 <= case("vop_alt_phone")["score"] <= 70

# confirmed lock
r = case("large_info_only", phone_confirmed_by_user=True)
assert r["confidence"] == "CONFIRMED" and r["tier"] in ("WARM", "HOT")

# legacy path stále funguje (bez match_case)
r = calculate_lead_score({"name_source": "registry_only", "registry_verified": True,
                          "registry_konatel": "Ján Novák", "phone": None})
assert "score" in r and "tier" in r

print("test_v8_scoring: OK")
