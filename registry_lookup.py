"""
ARES (CZ) and ORSR (SK) registry lookup for konateľ/jednateľ extraction.

Flow:
  1. extract_ico_from_text(text) → IČO + country hint
  2. CZ → lookup_ares(ico) → ARES REST API + or.justice.cz scrape
  3. SK → lookup_orsr(ico) → orsr.sk scrape
  4. Results cached in registry_cache.json (keyed by IČO)
"""

import re
import json
import os
import time
from typing import Dict, Any, Optional, List
import httpx
from bs4 import BeautifulSoup

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "registry_cache.json")
_CACHE_TTL = 30 * 24 * 3600  # 30 days


def _load_cache() -> dict:
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Registry cache write error: {e}")


def _cache_get(ico: str) -> Optional[dict]:
    cache = _load_cache()
    entry = cache.get(ico)
    if entry and (time.time() - entry.get("_ts", 0)) < _CACHE_TTL:
        print(f"[CACHE] Registry cache hit: {ico}")
        return entry
    return None


def _cache_set(ico: str, data: dict) -> None:
    cache = _load_cache()
    data["_ts"] = time.time()
    cache[ico] = data
    _save_cache(cache)


# ---------------------------------------------------------------------------
# 1. IČO extraction from scraped text
# ---------------------------------------------------------------------------

_ICO_RE = re.compile(
    r'(?:IČO|IČ|ICO|IC)\s*[:\s]\s*(\d[\d\s]{5,9}\d)',
    re.IGNORECASE,
)


def extract_ico_from_text(text: str) -> dict:
    """Find IČO in scraped text. Returns {ico, country, confidence, context}."""
    if not text:
        return {"ico": None, "country": None, "confidence": 0, "context": ""}

    best = None
    best_conf = 0

    for m in _ICO_RE.finditer(text):
        raw = m.group(1).replace(" ", "")
        if len(raw) != 8 or not raw.isdigit():
            continue
        if len(set(raw)) <= 2:
            continue

        start = max(0, m.start() - 50)
        end = min(len(text), m.end() + 50)
        ctx = text[start:end].strip()

        conf = 5
        ctx_lower = ctx.lower()
        if "ičo" in ctx_lower or "ico" in ctx_lower:
            conf += 2
        if re.search(r'dič|dic|ič dph|ic dph', ctx_lower):
            conf += 1
        if re.search(r's\.?\s*r\.?\s*o|a\.?\s*s\.', ctx_lower):
            conf += 1

        country = None
        if re.search(r'\bSK\d{10}\b', text[max(0, m.start()-200):m.end()+200]):
            country = "sk"
        elif re.search(r'\bCZ\d{8,10}\b', text[max(0, m.start()-200):m.end()+200]):
            country = "cz"

        if conf > best_conf:
            best_conf = conf
            best = {"ico": raw, "country": country, "confidence": conf, "context": ctx}

    return best or {"ico": None, "country": None, "confidence": 0, "context": ""}


# ---------------------------------------------------------------------------
# ARES employee category mapper
# ---------------------------------------------------------------------------

_ARES_EMP_SOLO = {"NULA"}
_ARES_EMP_MICRO = {"JEDNA_AZ_CTYRI", "PET_AZ_DEVET"}
_ARES_EMP_SMALL = {"DESET_AZ_DEVATENACT", "DVACET_AZ_CTYRICIT_DEVET", "PADESAT_AZ_DEVATDESATDEVET"}


def _map_ares_emp_category(raw: Optional[str]) -> Optional[str]:
    """Map ARES kategoriePoctuZamestnancu enum to scoring category."""
    if not raw:
        return None
    u = raw.upper().replace(" ", "_")
    if u in _ARES_EMP_SOLO:
        return "solo"
    if u in _ARES_EMP_MICRO:
        return "micro"
    if u in _ARES_EMP_SMALL:
        return "small"
    if u:
        return "large"
    return None


# ---------------------------------------------------------------------------
# 2. ARES lookup (CZ)
# ---------------------------------------------------------------------------

_ARES_BASE = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty"
_JUSTICE_SEARCH = "https://or.justice.cz/ias/ui/rejstrik-$firma"
_JUSTICE_EXTRACT = "https://or.justice.cz/ias/ui/rejstrik-firma.vysledky"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
    "Accept-Language": "cs-CZ,cs;q=0.9,sk;q=0.8,en;q=0.7",
}


def _parse_justice_extract(html: str) -> List[dict]:
    """Parse statutory organ members from or.justice.cz extract HTML."""
    members = []
    if not html:
        return members

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    # The extract has sections like "Statutární orgán - Loss" or "Představenstvo:"
    # followed by member entries with name, birth date, address, function
    section_re = re.compile(
        r'(?:Statutární\s+orgán|Představenstvo|Jednatel[ée]?|Dozorčí\s+rada)',
        re.IGNORECASE,
    )

    # Find all person-like patterns in the text
    # Czech OR uses "UPPERCASE NAME" format
    name_re = re.compile(
        r'^([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+)+)',
        re.MULTILINE,
    )
    # Also match ALL-CAPS names like "ALEŠ ZAVORAL"
    caps_name_re = re.compile(
        r'^([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{2,}(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{2,})+)',
        re.MULTILINE,
    )
    # Function pattern
    func_re = re.compile(
        r'(předsed[ak]|místopředsed[ak]|člen|jednatel(?:ka)?|prokurista)',
        re.IGNORECASE,
    )
    # Address/non-name words that appear as Title Case but aren't person names
    _addr_words = {
        "nová", "nova", "nové", "nove", "nový", "novy", "staré", "stare",
        "ulice", "náměstí", "namesti", "třída", "trida", "město", "mesto",
        "edvarda", "beneše", "benese", "sady", "pražská", "prazska",
        "den", "vznik", "zánik", "funkce", "členství", "datum", "adresa",
        "sídlo", "sidlo", "bydliště", "bydliste", "kraj", "okres",
        # CZ prepositions / toponymic fragments that appear as address lines
        "ve", "na", "pod", "nad", "za", "před", "při", "u", "ke", "do",
        "lhotách", "lhotkách", "kopci", "háji", "louce", "potokem",
    }

    lines = text.split("\n")
    in_section = False
    current_func = None

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        if section_re.search(line):
            in_section = True
            # Determine default function from section header
            ll = line.lower()
            if "jednatel" in ll:
                current_func = "jednatel"
            elif "představenstvo" in ll:
                current_func = "člen představenstva"
            elif "dozorčí" in ll:
                current_func = "člen dozorčí rady"
            else:
                current_func = "statutární orgán"
            continue

        if not in_section:
            continue

        # End section markers
        if re.match(r'^(Způsob jednání|Společníci|Základní|Ostatní|Akcie|Předmět)', line):
            in_section = False
            continue

        # Check for function label
        func_m = func_re.search(line)
        if func_m:
            current_func = func_m.group(1).lower()

        # Check for ALL-CAPS name (Czech OR standard)
        caps_m = caps_name_re.match(line)
        if caps_m:
            raw_name = caps_m.group(1)
            # Convert "ALEŠ ZAVORAL" to "Aleš Zavoral"
            parts = raw_name.split()
            nice_name = " ".join(p.capitalize() for p in parts)
            if len(parts) >= 2 and len(nice_name) >= 5:
                if any(p.lower() in _addr_words for p in parts):
                    continue
                # Look for "den vzniku funkce/členství" in nearby lines
                od = None
                for j in range(i+1, min(i+6, len(lines))):
                    dt_m = re.search(r'(\d{1,2}\.\s*\w+\s*\d{4}|\d{1,2}\.\d{1,2}\.\d{4})', lines[j])
                    if dt_m:
                        od = dt_m.group(1).strip()
                        break
                members.append({
                    "meno": nice_name,
                    "funkcia": current_func or "člen",
                    "od": od,
                })
                continue

        # Check for Title Case name
        name_m = name_re.match(line)
        if name_m:
            raw_name = name_m.group(1).strip()
            parts = raw_name.split()
            if any(p.lower() in _addr_words for p in parts):
                continue
            if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
                members.append({
                    "meno": raw_name,
                    "funkcia": current_func or "člen",
                    "od": None,
                })

    return members


def lookup_ares(ico: str) -> dict:
    """CZ registry lookup: ARES REST API + or.justice.cz statutory organ scrape."""
    ico = ico.strip().replace(" ", "")
    if len(ico) != 8 or not ico.isdigit():
        return {"found": False, "error": f"Invalid IČO format: {ico}"}

    cached = _cache_get(f"cz_{ico}")
    if cached:
        return cached

    result = {
        "found": False,
        "obchodne_meno": None,
        "adresa": None,
        "konatelia": [],
        "spolocnici": [],
        "source": "ares",
    }

    # Step 1: ARES REST API — basic company info
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(f"{_ARES_BASE}/{ico}", headers=_HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                result["found"] = True
                result["obchodne_meno"] = data.get("obchodniJmeno")
                # Employee count category — ARES v3 field
                kat_raw = data.get("kategoriePoctuZamestnancu") or data.get("kategorieVelkosti")
                result["velkost_firmy_raw"] = kat_raw
                result["velkost_category"] = _map_ares_emp_category(kat_raw)
                result["raw_response"] = data
                sidlo = data.get("sidlo", {})
                if sidlo:
                    addr_parts = [
                        sidlo.get("nazevUlice", ""),
                        str(sidlo.get("cisloDomovni", "")),
                        sidlo.get("nazevObce", ""),
                        str(sidlo.get("psc", "")),
                    ]
                    result["adresa"] = ", ".join(p for p in addr_parts if p and p != "None")
                result["raw_response"] = data
            elif resp.status_code == 404:
                result["error"] = f"IČO {ico} not found in ARES"
                _cache_set(f"cz_{ico}", result)
                return result
            else:
                print(f"[WARN] ARES HTTP {resp.status_code} for {ico}")
    except Exception as e:
        print(f"[WARN] ARES lookup error for {ico}: {e}")
        result["error"] = str(e)

    # Step 2: or.justice.cz — statutory organ scrape
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            # Search by IČO
            search_resp = client.get(
                _JUSTICE_SEARCH,
                params={"ico": ico, "jenPlatne": "PLATNE"},
                headers=_HEADERS,
            )
            if search_resp.status_code == 200:
                search_soup = BeautifulSoup(search_resp.text, "html.parser")
                # Find subjektId from result links
                subjekt_id = None
                for a in search_soup.find_all("a", href=True):
                    href = a["href"]
                    m = re.search(r'subjektId=(\d+)', href)
                    if m and "typ=PLATNY" in href:
                        subjekt_id = m.group(1)
                        break
                    if m and "vysledky" in href:
                        subjekt_id = m.group(1)
                        break

                if subjekt_id:
                    # Fetch extract
                    extract_resp = client.get(
                        _JUSTICE_EXTRACT,
                        params={"subjektId": subjekt_id, "typ": "PLATNY"},
                        headers=_HEADERS,
                    )
                    if extract_resp.status_code == 200:
                        members = _parse_justice_extract(extract_resp.text)
                        if members:
                            result["konatelia"] = members
                            print(f"[OK] Justice.cz: {len(members)} members for IČO {ico}")
                        else:
                            print(f"[WARN] Justice.cz: no members parsed for IČO {ico}")
                else:
                    print(f"[WARN] Justice.cz: no subjektId found for IČO {ico}")
    except Exception as e:
        print(f"[WARN] Justice.cz scrape error for {ico}: {e}")

    _cache_set(f"cz_{ico}", result)
    return result


# ---------------------------------------------------------------------------
# 3. ORSR lookup (SK)
# ---------------------------------------------------------------------------

_ORSR_SEARCH = "https://www.orsr.sk/hladaj_ico.asp"
_ORSR_BASE = "https://www.orsr.sk"


def _parse_orsr_detail(html: str) -> List[dict]:
    """Parse statutory organ members from orsr.sk detail page.

    ORSR structure: Štatutárny orgán section has <a class="lnm"> links
    with href containing PR=Priezvisko&MENO=Krstne. The link also contains
    <span class="ra"> tags with the name parts and "Vznik funkcie:" date.
    """
    members = []
    if not html:
        return members

    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: Extract from <a class="lnm" href="hladaj_osoba.asp?..."> links
    # These appear inside Štatutárny orgán / Konatelia sections
    seen = set()
    in_stat_section = False

    for td in soup.find_all("td"):
        td_text = td.get_text(strip=True)

        # Detect section labels
        td_lower = td_text.lower()
        if any(kw in td_lower for kw in [
            "štatutárny orgán", "statutarny organ", "konatelia", "konateľ",
            "predstavenstvo", "dozorná rada",
        ]):
            in_stat_section = True
            continue

        # End-of-section markers
        if any(kw in td_lower for kw in [
            "konanie menom", "základné imanie", "predmet činnosti",
            "ďalšie právne", "splnomocnenie", "prokúra",
        ]):
            in_stat_section = False
            continue

    # Parse all lnm links (they only appear in statutory sections)
    for a_tag in soup.find_all("a", class_="lnm"):
        href = a_tag.get("href", "")
        if "hladaj_osoba" not in href:
            continue

        # Extract from href: PR=Priezvisko&MENO=Krstne
        pr_match = re.search(r'PR=([^&]+)', href)
        meno_match = re.search(r'MENO=([^&]+)', href)
        if pr_match and meno_match:
            from urllib.parse import unquote
            priezvisko = unquote(pr_match.group(1))
            krstne = unquote(meno_match.group(1))
            full_name = f"{krstne} {priezvisko}".strip()
        else:
            # Fallback: get text from spans inside the link
            spans = a_tag.find_all("span", class_="ra")
            name_parts = [s.get_text(strip=True) for s in spans
                          if s.get_text(strip=True) and not any(
                              kw in s.get_text(strip=True).lower()
                              for kw in ["vklad", "eur", "vznik", "peňažn", "splaten"]
                          )]
            full_name = " ".join(name_parts).strip()

        if not full_name or full_name.lower() in seen:
            continue

        # Skip addresses masquerading as names
        parts = full_name.split()
        if len(parts) < 2:
            continue

        skip_words = {"bydlisko", "adresa", "ulica", "číslo", "vklad", "splaten"}
        if any(p.lower() in skip_words for p in parts):
            continue

        seen.add(full_name.lower())

        # Extract "Vznik funkcie" date from parent context
        parent_td = a_tag.find_parent("td")
        od = None
        if parent_td:
            parent_text = parent_td.get_text()
            dt_m = re.search(r'Vznik\s+funkcie:\s*(\d{1,2}\.\d{1,2}\.\d{4})', parent_text)
            if dt_m:
                od = dt_m.group(1)

        members.append({"meno": full_name, "funkcia": "konateľ", "od": od})

    # Strategy 2: Fallback text-based parsing if no links found
    if not members:
        text = soup.get_text(separator="\n")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        name_re = re.compile(
            r'(?:Ing\.|Mgr\.|Bc\.|JUDr\.|MUDr\.|PhDr\.|prof\.|doc\.)?\s*'
            r'([A-ZÁČĎÉÍĽĹŇÓÔŔŘŠŤÚŮÝŽ][a-záčďéíľĺňóôŕřšťúůýž]{2,}'
            r'(?:\s+[A-ZÁČĎÉÍĽĹŇÓÔŔŘŠŤÚŮÝŽ][a-záčďéíľĺňóôŕřšťúůýž]{2,})+)',
        )
        in_section = False
        for line in lines:
            ll = line.lower()
            if any(kw in ll for kw in ["štatutárny", "konatelia", "konateľ"]):
                in_section = True
                continue
            if in_section and any(kw in ll for kw in ["konanie menom", "základné imanie", "predmet"]):
                break
            if in_section:
                nm = name_re.match(line)
                if nm:
                    name = nm.group(1).strip()
                    if len(name.split()) >= 2 and name.lower() not in seen:
                        seen.add(name.lower())
                        members.append({"meno": name, "funkcia": "konateľ", "od": None})

    return members


def lookup_orsr(ico: str) -> dict:
    """SK registry lookup: orsr.sk scrape."""
    ico = ico.strip().replace(" ", "")
    if len(ico) != 8 or not ico.isdigit():
        return {"found": False, "error": f"Invalid IČO format: {ico}"}

    cached = _cache_get(f"sk_{ico}")
    if cached:
        return cached

    result = {
        "found": False,
        "obchodne_meno": None,
        "adresa": None,
        "konatelia": [],
        "spolocnici": [],
        "source": "orsr",
    }

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            # Step 1: Search by IČO
            search_resp = client.get(
                _ORSR_SEARCH,
                params={"ICO": ico, "SID": "0", "T": "f0", "R": "on"},
                headers={
                    **_HEADERS,
                    "Accept-Language": "sk-SK,sk;q=0.9,cs;q=0.8,en;q=0.7",
                },
            )
            search_resp.encoding = "windows-1250"
            if search_resp.status_code != 200:
                result["error"] = f"ORSR search HTTP {search_resp.status_code}"
                _cache_set(f"sk_{ico}", result)
                return result

            search_soup = BeautifulSoup(search_resp.text, "html.parser")

            # Find detail link
            detail_url = None
            for a in search_soup.find_all("a", href=True):
                href = a["href"]
                if "vypis.asp" in href and "ID=" in href:
                    detail_url = _ORSR_BASE + "/" + href.lstrip("/")
                    # Get company name from link text
                    name_text = a.get_text(strip=True)
                    if name_text and len(name_text) > 2:
                        result["obchodne_meno"] = name_text
                    break

            if not detail_url:
                result["error"] = f"IČO {ico} not found in ORSR"
                _cache_set(f"sk_{ico}", result)
                return result

            result["found"] = True

            # Step 2: Fetch detail page
            detail_resp = client.get(detail_url, headers=_HEADERS)
            detail_resp.encoding = "windows-1250"
            if detail_resp.status_code == 200:
                # Extract address from detail
                detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
                detail_text = detail_soup.get_text()

                # Company name from detail (more reliable)
                for td in detail_soup.find_all("td"):
                    td_text = td.get_text(strip=True)
                    if "Obchodné meno:" in td_text:
                        next_td = td.find_next_sibling("td")
                        if next_td:
                            result["obchodne_meno"] = next_td.get_text(strip=True)
                        break

                # Address
                addr_match = re.search(
                    r'Sídlo[:\s]*(.+?)(?=IČO|Deň|Právna|$)',
                    detail_text,
                    re.DOTALL,
                )
                if addr_match:
                    addr = re.sub(r'\s+', ' ', addr_match.group(1)).strip()
                    if len(addr) > 5:
                        result["adresa"] = addr[:200]

                # Step 3: Parse statutory organs
                members = _parse_orsr_detail(detail_resp.text)
                if members:
                    result["konatelia"] = members
                    print(f"[OK] ORSR: {len(members)} members for IČO {ico}")
                else:
                    print(f"[WARN] ORSR: no members parsed for IČO {ico}")
            else:
                print(f"[WARN] ORSR detail HTTP {detail_resp.status_code}")

    except Exception as e:
        print(f"[WARN] ORSR lookup error for {ico}: {e}")
        result["error"] = str(e)

    _cache_set(f"sk_{ico}", result)
    return result


# ---------------------------------------------------------------------------
# 4. Unified lookup
# ---------------------------------------------------------------------------

def lookup_registry(ico: str, country: Optional[str] = None) -> dict:
    """Lookup IČO in the appropriate registry based on country hint.
    If country is None, tries both (CZ first, then SK).
    """
    if country == "cz":
        return lookup_ares(ico)
    if country == "sk":
        return lookup_orsr(ico)

    # Unknown country — try CZ first (more reliable API), then SK
    cz = lookup_ares(ico)
    if cz.get("found") and cz.get("obchodne_meno"):
        return cz

    sk = lookup_orsr(ico)
    if sk.get("found"):
        return sk

    return cz if cz.get("found") else sk


# ---------------------------------------------------------------------------
# 5. v7 wrappers — return normalised format for pair_contact_with_phone
# ---------------------------------------------------------------------------

_FINSTAT_NAME_RE = re.compile(
    r'^([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚŮÝŽ][a-záčďéíľĺňóôŕšťúůýž]{2,}'
    r'(?:\s+[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚŮÝŽ][a-záčďéíľĺňóôŕšťúůýž]{2,})+)',
)


def _lookup_finstat_sk(ico: str) -> dict:
    """Fallback for živnostníci not in ORSR — scrape finstat.sk."""
    try:
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            resp = client.get(
                f"https://finstat.sk/{ico}",
                headers={**_HEADERS, "Accept-Language": "sk-SK,sk;q=0.9"},
            )
            if resp.status_code != 200:
                return {}
            soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "html.parser")
            # h1 usually has "Firstname Lastname - BusinessName" or just company name
            h1 = soup.find("h1")
            if not h1:
                return {}
            title = h1.get_text(strip=True)
            # For SZČO: "Renáta Zacharová - EZAL" → extract person name before " - "
            person = title.split(" - ")[0].strip() if " - " in title else title
            # Validate it looks like a person name (2+ words, title case)
            if not _FINSTAT_NAME_RE.match(person):
                person = None
            # Employee count from finstat text
            text = soup.get_text(separator=" ")
            emp_cat = None
            m = re.search(r'Počet\s+zamestnancov[^<\d]*?(\d+)\s*[-–]\s*(\d+)', text)
            if m:
                high = int(m.group(2))
                emp_cat = "solo" if high <= 1 else "micro" if high <= 9 else "small" if high <= 49 else "large"
            return {"konatel": person, "obchodne_meno": title, "emp_cat": emp_cat, "found": bool(person)}
    except Exception as e:
        print(f"[WARN] finstat fallback error {ico}: {e}")
        return {}


_RPO_BASE = "https://api.statistics.sk/rpo/v1/search"


def _lookup_rpo(ico: str) -> Optional[dict]:
    """Primary SK lookup via Štatistický úrad RPO API. Covers both s.r.o. and živnostníci.
    Returns None on error/not-found. Returns dict with is_sole_trader flag."""
    cached = _cache_get(f"rpo_{ico}")
    if cached:
        return cached if cached.get("verified") else None

    try:
        r = httpx.get(
            _RPO_BASE,
            params={"identifier": ico},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
        if not results:
            _cache_set(f"rpo_{ico}", {"verified": False})
            return None
        subj = results[0]

        # Current name (no validTo = still active)
        full_names = subj.get("fullNames", [])
        name = next(
            (n["value"] for n in full_names if not n.get("validTo")),
            full_names[0]["value"] if full_names else None,
        )

        # Register type: code "2" = Živnostenský register → živnostník
        reg = subj.get("sourceRegister", {}).get("value", {})
        is_szco = reg.get("code") == "2" or "živnost" in reg.get("value", "").lower()

        if is_szco:
            # Person name is before " - brand" in fullName
            person = name.split(" - ")[0].strip() if name and " - " in name else name
            out = {
                "source": "RPO",
                "verified": True,
                "konatel": person,
                "konatelia_count": 1,
                "velkost_category": "solo",
                "obchodne_meno": name,
                "is_sole_trader": True,
                "error": None,
            }
        else:
            # s.r.o./a.s. — RPO has no statutory organ members, need ORSR for konatelia
            out = {
                "source": "RPO",
                "verified": True,
                "konatel": None,
                "konatelia_count": 0,
                "velkost_category": None,
                "obchodne_meno": name,
                "is_sole_trader": False,
                "error": None,
            }

        _cache_set(f"rpo_{ico}", out)
        return out

    except Exception as e:
        print(f"[WARN] RPO lookup error {ico}: {e}")
        return None


def lookup_sk(ico: str) -> dict:
    """SK registry lookup → v7 format.
    Chain: RPO (živnostníci) → ORSR (s.r.o. konatelia) → FinStat fallback."""

    # 1. RPO — fast API, covers živnostníci that ORSR lacks
    rpo = _lookup_rpo(ico)
    if rpo and rpo.get("is_sole_trader"):
        # Živnostník identified — no ORSR scrape needed
        print(f"[RPO] Živnostník: {rpo.get('konatel')} ({rpo.get('obchodne_meno')})")
        return rpo

    # 2. ORSR — existing scrape for s.r.o./a.s. konatelia (unchanged)
    raw = lookup_orsr(ico)
    konatelia = raw.get("konatelia", [])
    first = konatelia[0]["meno"] if konatelia else None

    # 3. FinStat fallback
    finstat = {}
    if not raw.get("found") or not first:
        finstat = _lookup_finstat_sk(ico)
        if finstat.get("konatel"):
            first = finstat["konatel"]

    verified = raw.get("found", False) or bool(finstat.get("konatel"))
    source = "ORSR" if raw.get("found") else ("FinStat" if finstat.get("konatel") else "ORSR")
    emp_cat = finstat.get("emp_cat")

    return {
        "source": source,
        "verified": verified,
        "konatel": first,
        "konatelia_count": len(konatelia),
        "velkost_category": emp_cat,
        "obchodne_meno": raw.get("obchodne_meno") or finstat.get("obchodne_meno"),
        "error": raw.get("error") if not verified else None,
        "is_sole_trader": False,
    }


def lookup_cz(ico: str) -> dict:
    """ARES lookup → v7 format: {source, verified, konatel, konatelia_count, velkost_category}."""
    import scoring as _scoring
    raw = lookup_ares(ico)
    konatelia = raw.get("konatelia", [])
    first = konatelia[0]["meno"] if konatelia else None
    # Živnostník/OSVČ: ARES has no statutory organ — obchodniJmeno IS the person
    if not first:
        om = raw.get("obchodne_meno") or ""
        if _scoring.is_person_name(om):
            first = om
    return {
        "source": "ARES",
        "verified": raw.get("found", False),
        "konatel": first,
        "konatelia_count": len(konatelia),
        "velkost_category": raw.get("velkost_category"),
        "velkost_firmy_raw": raw.get("velkost_firmy_raw"),
        "obchodne_meno": raw.get("obchodne_meno"),
        "error": raw.get("error"),
    }
