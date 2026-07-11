"""
Single source of truth for lead scoring.

lead_data keys:
  name_source       "register+web" | "register+web_distant" | "registry_only"
                    | "web_only" | None
  phone             str | None
  phone_type        "osobny" | "odhad_osobny" | "info" | None
  email             str | None
  email_type        "personal" | "generic" | None
  registry_verified bool
  registry_konatel  str | None
  ico               str | None
  velkost_category  "solo" | "micro" | "small" | "medium" | "large" | "unknown" | None
  jurisdiction      "SK" | "CZ" | None
  other_contacts    list
  phone_confirmed_by_user  bool
"""
import re
import unicodedata
from typing import Optional


# ── is_person_name ────────────────────────────────────────────────────────────

_TITLES_RE = re.compile(r'\b(?:Ing|Mgr|Bc|MUDr|MVDr|PhDr|JUDr|RNDr|Dipl)\.')

_DIACRITICS = frozenset("áéíóúýäčďěľĺňôŕšťůž")

_CITIES = frozenset({
    "bratislava", "praha", "brno", "košice", "žilina", "prešov", "nitra",
    "banská bystrica", "trnava", "trenčín", "martin", "poprad", "ostrava",
    "plzeň", "liberec", "olomouc", "české budějovice", "hradec králové",
    "pardubice", "zlín",
    # partial city phrases that appear as false-positive "person names"
    "nové mesto", "stará ľubovňa", "nová paka", "staré mesto",
    "nové zámky", "dolný kubín", "liptovský mikuláš", "dunajská streda",
    "český těšín", "česká skalice", "nová dedinka",
})

_CONTACT_WORDS = frozenset({
    "kontakt", "info", "eshop", "shop", "obchod", "sklad", "podpora",
    "servis", "reklamacia", "reklamácia", "doprava", "email", "telefon", "telefón",
})

_LEGAL_SUFFIXES = ("s.r.o.", "a.s.", "spol.", "k.s.", "o.z.", "ltd", "gmbh")


def _deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def is_person_name(text: str) -> bool:
    """True iff text looks like a real person name (Meno Priezvisko)."""
    if not text or len(text.strip()) < 5:
        return False
    t = text.strip()

    # FALSE: contains digit
    if any(c.isdigit() for c in t):
        return False

    # FALSE: entirely uppercase (abbreviations, acronyms)
    alpha = [c for c in t if c.isalpha()]
    if alpha and all(c.isupper() for c in alpha):
        return False

    # FALSE: contains special chars beyond letters, spaces, hyphens, diacritics
    if re.search(r'[^a-zA-Z\s\-áéíóúýäčďěľĺňôŕšťůžÁÉÍÓÚÝÄČĎĚĽĹŇÔŔŠŤŮŽ.]', t):
        return False

    tl = t.lower()
    td = _deaccent(tl)

    # FALSE: ends with legal entity suffix
    if any(tl.rstrip(". ").endswith(suf.rstrip(".")) for suf in _LEGAL_SUFFIXES):
        return False

    # FALSE: contains contact/operational word
    words_set = set(tl.split())
    if words_set & _CONTACT_WORDS:
        return False

    # FALSE: is a city name
    if td in {_deaccent(c) for c in _CITIES}:
        return False

    # TRUE: has academic title prefix — treat rest as name even if 1 word
    if _TITLES_RE.match(t):
        return True

    # At least 2 words required without a title
    parts = [p for p in t.split() if p and not p.endswith(".")]
    if len(parts) < 2:
        return False

    # TRUE: two words, both start uppercase, each 3+ chars
    cap_long = [p for p in parts if p[0].isupper() and len(p) >= 3]
    has_diacritic = any(c.lower() in _DIACRITICS for c in t)

    if len(cap_long) >= 2:
        return True

    # TRUE: at least one word with diacritic (Slovak/Czech surnames almost always have it)
    if len(cap_long) >= 1 and has_diacritic:
        return True

    return False


# ── Size bucket ───────────────────────────────────────────────────────────────

def _size_bucket(cat: Optional[str], jurisdiction: Optional[str] = None) -> str:
    """Map velkost_category to scoring bucket."""
    if cat == "solo":
        return "solo"
    if cat in ("micro",):
        return "micro"
    if cat == "small":
        return "small_low"   # 6–9 employees
    if cat in ("medium", "large"):
        return "large"
    # unknown: conservative estimate
    if jurisdiction == "SK" or jurisdiction is None:
        return "micro"
    return "micro"


# ── Name-source × size scoring matrix ────────────────────────────────────────
# Columns: solo / micro / small_low / large
_NAME_SCORE: dict = {
    "register+web":          {"solo": 35, "micro": 35, "small_low": 35, "large": 35},
    "register+web_distant":  {"solo": 28, "micro": 22, "small_low": 18, "large":  5},
    "registry_only":         {"solo": 28, "micro": 25, "small_low": 10, "large": -10},
    "web_only":              {"solo": 20, "micro": 20, "small_low": 20, "large": 20},
    None:                    {"solo": -5, "micro": -5, "small_low": -10, "large": -15},
}


# ── v8 case-based scorer ──────────────────────────────────────────────────────
# Presné rozsahy podľa veľkosti firmy (pravidlo #3 špecifikácie):
#   tiny_any_phone       1-3 zam. + meno z registra + akékoľvek číslo → 80-100
#   small_match          3-9 zam. + zhoda meno+telefón → 70-90 (podľa vzdialenosti)
#   small_no_match       3-9 zam. bez zhody → 60-80
#   large_name_near      10+ meno na webe + telefón ≤100 znakov → 80-100
#   large_name_far_role  10+ meno na webe, číslo pri inej role → 30-60
#   large_role_only      10+ meno nenájdené, číslo pri role (nie info) → 50-75
#   large_info_only      10+ len info linka → 25-50
#   vop_alt_phone        info v kontakte, iné číslo vo VOP pri IČO → 40-70

def _lin(x, x0, x1, y0, y1):
    """Lineárna interpolácia s clampom."""
    if x is None:
        return (y0 + y1) / 2
    if x <= x0:
        return y0
    if x >= x1:
        return y1
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def _score_by_case(lead_data: dict) -> dict:
    case = lead_data["match_case"]
    dist = lead_data.get("proximity_chars")
    q = lead_data.get("phone_quality") or 2
    name_found = lead_data.get("name_found_on_web", False)
    email_type = lead_data.get("email_type")

    if case == "tiny_any_phone":
        score = 85 + (10 if name_found else 0) - (5 if q <= 1 else 0)
    elif case == "small_match":
        score = _lin(dist, 0, 300, 90, 70)
    elif case == "small_no_match":
        score = 70 + (8 if q >= 3 else 0) - (10 if q <= 1 else 0)
    elif case == "large_name_near":
        score = _lin(dist, 0, 100, 100, 80)
    elif case == "large_name_far_role":
        score = {5: 60, 4: 60, 3: 48}.get(q, 35)
    elif case == "large_role_only":
        score = {5: 75, 4: 75, 3: 62}.get(q, 50)
    elif case == "vop_alt_phone":
        # ponytail: bez presného počtu zamestnancov stred pásma 40-70;
        # škálovanie podľa počtu doplniť keď bude spoľahlivý zdroj
        score = 55
    else:  # large_info_only
        score = 35 + (10 if name_found else 0) + (5 if email_type == "personal" else 0)

    score = int(round(max(0, min(100, score))))
    tier = "HOT" if score >= 70 else "WARM" if score >= 50 else "COOL" if score >= 30 else "DEAD"

    if case in ("small_match", "large_name_near") or (case == "tiny_any_phone" and name_found):
        confidence = "HIGH"
    elif case in ("tiny_any_phone", "small_no_match", "large_role_only", "large_name_far_role"):
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    reasoning = [f"[veľkosť: {lead_data.get('size_bucket', '?')}] prípad: {case} → skóre {score}"]

    if lead_data.get("phone_confirmed_by_user"):
        confidence = "CONFIRMED"
        if tier in ("DEAD", "COOL"):
            tier = "WARM"
        reasoning.append("Telefón potvrdený používateľom → tier zamknutý")

    reasoning.append(f"Tier: {tier} (skóre {score}/100)")
    return {
        "score": score,
        "tier": tier,
        "confidence": confidence,
        "reasoning": reasoning,
        "breakdown": {"match_case": case, "case_score": score,
                      "phone_quality": q, "proximity_chars": dist},
    }


# ── Main scorer ───────────────────────────────────────────────────────────────

def calculate_lead_score(lead_data: dict) -> dict:
    # v8: keď pairing určil match_case, platí presná matica podľa veľkosti
    if lead_data.get("match_case"):
        return _score_by_case(lead_data)

    score = 0
    breakdown: dict = {}
    reasoning: list = []

    cat = lead_data.get("velkost_category")
    jurisdiction = lead_data.get("jurisdiction")
    bucket = _size_bucket(cat, jurisdiction)
    hiring_signal = lead_data.get("hiring_signal", False)

    # --- Registry verification ---
    if lead_data.get("registry_verified"):
        score += 15
        breakdown["ico_verified"] = 15
        konatel = lead_data.get("registry_konatel")
        ico = lead_data.get("ico", "")
        reasoning.append(
            f"IČO {ico} overené v registri → konateľ: {konatel or 'neznámy'} (+15)"
        )

    # --- Name source × size ---
    name_source = lead_data.get("name_source")
    row = _NAME_SCORE.get(name_source, _NAME_SCORE[None])
    name_pts = row[bucket]
    score += name_pts
    breakdown["name_source"] = name_pts

    ns_label = name_source or "žiadne meno"
    reasoning.append(f"[veľkosť: {bucket}] [{ns_label}] → {name_pts:+d} bodov")

    # --- Phone ---
    phone = lead_data.get("phone")
    phone_type = lead_data.get("phone_type")
    if not phone:
        score -= 15
        breakdown["no_phone"] = -15
        reasoning.append("Žiadny telefón nenájdený (-15)")
    elif phone_type == "osobny":
        score += 25
        breakdown["phone_personal"] = 25
        reasoning.append("Telefón klasifikovaný ako osobný (+25)")
    elif phone_type == "odhad_osobny":
        score += 20
        breakdown["phone_est_personal"] = 20
        reasoning.append("Telefón odhadovaný ako osobný — malá firma (+20)")
    elif phone_type == "info":
        score += 10
        breakdown["phone_info"] = 10
        reasoning.append("Telefón pravdepodobne info linka (+10)")

    # --- Email ---
    email = lead_data.get("email")
    email_type = lead_data.get("email_type")
    if email:
        if email_type == "personal":
            score += 15
            breakdown["email_personal"] = 15
            reasoning.append(f"Osobný email {email} (+15)")
        else:
            score += 5
            breakdown["email_generic"] = 5
            reasoning.append(f"Generický email {email} (+5)")

    # --- Company size bonus ---
    _ARES_RAW_LABEL = {
        "NULA": "0", "JEDNA_AZ_CTYRI": "1–4", "PET_AZ_DEVET": "5–9",
        "DESET_AZ_DEVATENACT": "10–19", "DVACET_AZ_CTYRICIT_DEVET": "20–49",
        "PADESAT_AZ_DEVATDESATDEVET": "50–99",
    }
    velkost_raw = (lead_data.get("velkost_firmy_raw") or "").upper().replace(" ", "_")
    ares_label = _ARES_RAW_LABEL.get(velkost_raw)
    if cat == "solo":
        score += 10
        breakdown["size_solo"] = 10
        reasoning.append("Firma: solo/jednoosobová (+10)")
    elif cat == "micro":
        score += 5
        breakdown["size_micro"] = 5
        if jurisdiction == "CZ" and ares_label:
            reasoning.append(f"Firma: micro (ARES: {ares_label} zamestnancov) (+5)")
        elif jurisdiction == "CZ":
            reasoning.append("Firma: micro (ARES) (+5)")
        else:
            reasoning.append("Firma: SK (odhad micro, počet neznámy) (+5)")
    elif cat in ("small", "medium", "large"):
        score -= 5
        breakdown["size_large"] = -5
        if jurisdiction == "CZ" and ares_label:
            reasoning.append(f"Firma: {cat} (ARES: {ares_label} zamestnancov) (-5)")
        else:
            reasoning.append(f"Firma: {cat} (-5)")

    # --- Other contacts ---
    if lead_data.get("other_contacts"):
        score += 5
        breakdown["other_contacts"] = 5
        reasoning.append("Nájdené ďalšie kontakty s rolou (+5)")

    # --- Hiring signal (registry-only leads only) ---
    # +25 namiesto +20: cat=None defaultuje na micro bucket ale bez +5 size bonus,
    # takže 25+15-15+0+25=50 → WARM pre neznámu/micro firmu ako požadované
    if hiring_signal and lead_data.get("name_source") == "registry_only":
        score += 25
        breakdown["hiring_signal"] = 25
        reasoning.append("Firma aktívne hľadá obchodníka na profesii (+25)")

    score = max(0, min(100, score))

    # --- Tier ---
    tier = "HOT" if score >= 70 else "WARM" if score >= 50 else "COOL" if score >= 30 else "DEAD"

    # --- Confidence ---
    if name_source == "register+web":
        confidence = "HIGH"
    elif name_source in ("register+web_distant", "web_only"):
        confidence = "MEDIUM-HIGH"
    elif name_source == "registry_only":
        confidence = "MEDIUM"
    elif phone_type == "odhad_osobny":
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # --- phone_confirmed_by_user lock ---
    if lead_data.get("phone_confirmed_by_user"):
        confidence = "CONFIRMED"
        if tier in ("DEAD", "COOL"):
            tier = "WARM"
        reasoning.append("Telefón potvrdený používateľom → tier zamknutý")

    reasoning.append(f"Tier: {tier} (skóre {score}/100)")

    return {
        "score": score,
        "tier": tier,
        "confidence": confidence,
        "reasoning": reasoning,
        "breakdown": breakdown,
    }
