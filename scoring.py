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


# ── Main scorer ───────────────────────────────────────────────────────────────

def calculate_lead_score(lead_data: dict) -> dict:
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
    if cat == "solo":
        score += 10
        breakdown["size_solo"] = 10
        reasoning.append("Firma: solo/jednoosobová (+10)")
    elif cat == "micro":
        score += 5
        breakdown["size_micro"] = 5
        reasoning.append("Firma: 1–9 zamestnancov (+5)")
    elif cat in ("small", "medium", "large"):
        score -= 5
        breakdown["size_large"] = -5
        reasoning.append("Firma: 10+ zamestnancov (-5)")

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
