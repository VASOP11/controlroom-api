# WECTOR-MAP — Audit kódu (z kódu, nie z predpokladov)

Stav: `main.py` 4408 riadkov, `wector/index.html` 1549 riadkov. Čítané kompletne.

---

## 1. BACKEND (main.py)

### 1.1 API endpointy

| Metóda | Path | Funkcia | Čo robí |
|--------|------|---------|---------|
| GET | `/health` | `health()` | `{"status":"ok"}` |
| POST | `/api/leads` | `create_lead()` | Uloží lead, ohodnotí cez `evaluate_lead()` |
| GET | `/api/leads` | `get_leads()` | Vráti všetky leads z DB |
| GET | `/api/leads/{id}` | `get_lead()` | Jeden lead |
| PUT | `/api/leads/{id}` | `update_lead()` | Update + rescore |
| DELETE | `/api/leads/{id}` | `delete_lead()` | Zmaže |
| POST | `/api/leads/score/bulk` | `bulk_score()` | Scoring pre list leadov |
| POST | `/api/leads/{id}/adjust` | `adjust_lead()` | Manuálny AI adj. ±20 |
| GET | `/api/email/templates` | `list_templates()` | Email templates |
| POST | `/api/email/templates` | `create_template()` | Nová šablóna |
| POST | `/api/leads/{id}/email-draft` | `generate_email_draft()` | String replace v šablóne |
| POST | `/api/leads/scrape` | `scrape_lead()` | Hlavný scrape + AI + skóre + DB |
| POST | `/api/debug/scrape` | `debug_scrape()` | Scrape bez DB uloženia, všetky diagnostické polia |
| POST | `/api/leads/raw-extract` | `raw_extract()` | Surové kontakty: emaily, telefóny, osoby, IČO, jurisdikcia |
| POST | `/api/leads/candidates` | `candidates_endpoint()` | Kandidáti pre UI výber + registry lookup |
| POST | `/api/leads/select` | `select_lead()` | Uloží user-vybraný kontakt, vypočíta skóre |

---

### 1.2 Scoring — PRESNÉ HODNOTY Z KÓDU

#### A) `_calculate_scrape_score()` — volá `/api/leads/scrape` (riadky 2335–2388)

| Podmienka | Body |
|-----------|------|
| `contact_name` + rola je decision-maker (konatel/CEO/riaditel/founder/...) | +25 |
| `contact_name` + iná rola | +15 |
| `phone_type == "personal"` | +25 |
| `phone_type == "predpokladaný_osobný"` | +20 |
| `phone_type` iný (info) | +10 |
| žiadny telefón | **-15** |
| email NOT generic (not in prefix list) | +15 |
| email generic | +5 |
| `registry_source` neprázdny | +15 |
| `employee_category == "solo"` | +10 |
| `employee_category == "micro"` | +5 |
| `employee_category in ("small","medium","large")` | **-5** |
| `name_found_on_web == True` | +10 |
| `other_contacts` neprázdne | +5 |

Tier z tohto scoreru: `HOT ≥ 80`, `WARM ≥ 60`, `COOL ≥ 40`, `DEAD < 40`

Výsledok sa ďalej kombinuje s DB rule_score:
```python
final_score = max(0, min(100, final_score_override + max(0, rule_score - 50)))
```

#### B) `_calculate_score()` — volá `/api/leads/select` + candidates modal (riadky 4163–4220)

Používa `SCORE_CONFIG` (riadky 1109–1121):

| Kľúč | Hodnota |
|------|---------|
| `registry_konatel` | +30 |
| `personal_phone` | +20 |
| `info_phone` | +10 |
| `delivery_phone` | 0 |
| `personal_email` | +15 |
| `generic_email` | +5 |
| `role_decision_maker` | +20 |
| `name_match_registry` | +10 |
| `fallback_high_confidence` | +10 (NIKDY SA NEPOUŽÍVA — pozri sekcia 3) |
| `fallback_low_confidence` | 0 (NIKDY SA NEPOUŽÍVA) |
| `no_personal_phone_penalty` | **-30** (len ak je registry konateľ ALE nie je personal telefón) |

#### C) `TIER_RANGES` (riadky 1123–1128)

```python
HOT:  (80, 100)
WARM: (60, 79)
COOL: (40, 59)
DEAD: (0, 39)
```

#### D) DB scoring (`evaluate_lead()`) — `OrganizationConfig` seed (riadky 114–129)

| Podmienka | Body |
|-----------|------|
| `len(platforms) >= 2` | +25 |
| hodnota €5 000–30 000 | +20 |
| vertikála in Home&Garden/Beauty/Pet/Sport/Auto-moto | +20 |
| rola obsahuje ceo/riaditeľ/konateľ/director | +20 |
| má `contact_name` | +10 |
| vertikála mimo target (a nie je None) | **-25** |

---

### 1.3 Tier prahy — súhrn

| Zdroj | HOT | WARM | COOL | DEAD |
|-------|-----|------|------|------|
| Backend `TIER_RANGES` + `_calculate_scrape_score` | ≥80 | ≥60 | ≥40 | <40 |
| DB tier_thresholds v seed | ≥80 | ≥60 | ≥40 | <40 |
| **Frontend `tierFromScore()`** | ≥80 | ≥60 | **≥30** | <30 |

**KONFLIKT:** Frontend má COOL od 30, backend od 40.

---

### 1.4 phone_type logika — ako sa rozhoduje

Funkcia `_smart_phone_assignment()` (riadky 2239–2332):

1. **KROK 1–2:** Hľadaj `contact_name` v ±300 znakov od telefónu v texte.
   - Nájdené → `phone_type = "personal"`, confidence = "high"

2. **KROK 3:** Hľadaj iné mená s rolou + telefónom → pridá do `other_contacts` (max 3).

3. **KROK 4:** Ak meno nebolo nájdené pri čísle:
   - `employee_category in ("solo","micro")` → `"predpokladaný_osobný"`, confidence = "medium"
   - inak → `"info"`, confidence = "low"

Funkcia `_classify_phone_type()` pre `/api/leads/candidates` (riadky 3804–3821):
- delivery kontext (packeta/gls/dpd/...) → `"delivery"`
- `dist_to_konatel < 50` AND `near_name` AND email nie je generic → `"personal"`
- kontext/zákaznícky/servis/info → `"info"`
- `near_name` AND `dist < 150` → `"personal"`
- inak → `"unknown"`

---

### 1.5 Blocklists — obsah

**`_NOT_A_NAME_WORD`** (riadky 941–967, ~55 slov):
Email, Mail, Telefón, Mobil, Phone, Tel, Web, Adresa, Sídlo, Kontakt, Contact, Firma, Spoločnosť, Pondelok–Nedeľa, Monday–Friday, Wi, Sk, Cz, Eu, Id, Ok, Sr, Kvatro, Sro, Ltd, Inc, As, Zs, Prihlásenie, Hľadať, Darčeky, Nákupný, Košík, Novinky, Zákaznícka, Zákaznícky, Podpora, Doprava, Platba, Reklamácia, Vrátenie, Podmienky, Ochrana, Údajov, Program, Veľkoobchodný, Informácie, Kontaktné, Horúce, Prázdny, Tovar, Zľavy, Akcia, Nový, Výpredaj, Kategória, Produkt, Objednávka, Dopravné, Platobné, Faktúra, Doklad, Záručný, Servis, Technická, Slovensko, Česko, Praha, Bratislava, Žilina, Košice, mesiace, Registrácia, Odhlásenie, Nastavenia, Profil, Kontakty, Odoslať, Zavrieť, Outdoor, Republic, Dotaz, Specialist, Manager, Consultant, Coordinator, Analyst, Som, Vám, Vás, Sme, Ste, Môžem...

**`_UI_BLOCKLIST`** (riadky 979–1008, ~60 slov):
heslo, prispôsobiť, povoliť, pokračovať, prihlásiť, registrovať, odmietnuť, zavrieť, odoslať, uložiť, vyhľadávanie, objednávky, košík, pokladňa, reklamácie, showroom, realizácie, katalógy, veľkoobchod, vypredaj, facebook, google, instagram, pinterest, youtube, twitter, linkedin, whatsapp, prev, next, menu, footer, header, sidebar, error, loading, spinner, novinky, akcie, blog, kariéra, recenzie, newsletter, subscribe, gtm, analytics, datalayer, tracking, kupujúci, predávajúci, spotrebiteľ, objednávateľ, podnikateľ, dodávateľ, prevádzkovateľ, zhotoviteľ, obchodník, právnická, fyzická, zmluvná, strana, subjekt

**`_CITY_BLOCKLIST`** (riadky 1011–1032, ~55 miest):
Bratislava, Košice, Prešov, Žilina, Banská Bystrica, Nitra, Trnava, Trenčín, Martin, Poprad, Piešťany, Zvolen, Považská Bystrica, Prievidza, Topoľčany, Lučenec, Komárno, Levice, Michalovce, Humenné, Bardejov, Ružomberok, Čadca, Galanta, Dunajská Streda, Stará Turá, Nové Zámky, Dolný Kubín, Liptovský Mikuláš, Spišská Nová Ves, Praha, Brno, Ostrava, Plzeň, Olomouc, Liberec, České Budějovice, Hradec Králové, Pardubice, Zlín, Jihlava, Blansko, Karlovy Vary, Opava, Frýdek Místek + mestské časti + Česko/Slovensko

**`_PRODUCT_TOKENS`** (riadky 1035–1046, ~25 slov):
collagen, serum, cream, vitamin, gel, mask, skin, hair, oil, lotion, spray, shampoo, conditioner, moisturizer, cleanser, toner, liftactiv, retinol, hyaluron, peptide, niacinamide, keratin, biotin, fotopapier, format, produkt, tovar, material, papier, cartridge, kancelaria, jollein, cottelli, satisfyer, dillio, fleshlight

**`_DELIVERY_BLOCKLIST`** (riadky 1049–1056, ~15 firiem):
packeta, zásielkovňa, geis, dpd, gls, slovenská pošta, česká pošta, ppl, toptrans, fofr, spring courier, shipmonk, balíkovo, depo, expres kurier

**`_INGREDIENT_BLOCKLIST`** (riadky 1100–1105):
panax ginseng, ginkgo biloba, služba účel, knieradl táta, aloe vera, tea tree, shea butter, perfect fit, little dutch, happy horse

**`IGNORED_CONTACT_DOMAINS`** (riadky 891–904, ~20 domén):
soi.sk, coi.cz, dpd.com/sk/cz, gls domény, ups.com/sk/cz, sps-sro.sk, packeta/packetery domény, zasilkovna.sk/cz, heureka.sk/cz, slsp.sk, vub.sk, tatrabanka.sk, csas.cz, csob.sk/cz, sberbank.sk, unicreditbank, raiffeisen, kb.cz, moneta.cz, airbank.cz

**`BOILERPLATE_KEYWORDS`** (riadky 803–808):
cookies, cookie, súhlasím, prehliadač, gdpr, ochrana osobných údajov, spracovanie osobných údajov

**`GENERIC_EMAIL_PREFIXES`** (riadky 2129–2134):
info, podpora, support, office, kontakt, contact, sales, obchod, reklamacia, admin, hello, ahoj, objednavky, eshop, shop, mail, post, noreply, marketing, reklama, helpdesk, dotazy, servis, info2

---

### 1.6 registry_lookup — kedy sa volá, prečo môže byť prázdny

`registry_lookup.py` (import) sa volá **LEN v `/api/leads/candidates`** (riadok 3839):
```python
from registry_lookup import extract_ico_from_text, lookup_registry
reg = lookup_registry(ico, country=country)
```

V `/api/leads/scrape` sa `registry_lookup` **NEVOLÁ**. Pole `registry_source` v scrape výsledku pochádza z **AI odpovede** (`extracted.get("registry_source", "")`), nie z registry lookupu.

`registry_source` môže byť prázdny keď:
- IČO sa nenašlo v texte stránky (regex `\bIČ[OQ]?\s*:?\s*(\d[\s\d]{5,8})` nevyhovuje)
- AI nevrátila `registry_source` v JSON
- IČO má ≠ 8 číslic (validácia na riadku 2989)
- Ide o `.sk`/`.cz` stránku bez IČO v texte (živnostník bez VOP stránky)

---

### 1.7 Polia output JSON z `/api/leads/scrape`

Pole `extracted` (riadky 3103–3115):
```
email, phone, all_phones, contact_name, contact_role, role_category,
priority_score, contact_points, ico, phone_type, phone_confidence,
employee_count, employee_category, name_found_on_web, reasoning,
other_contacts, score_breakdown, registry_source
```

Vonkajšia štruktúra odpovede:
```
action ("created"|"updated"|"scrape_only"), lead_id, primary_identifier,
score, tier, extracted {...}, [warning]
```

Pole `extracted` v `/api/leads/candidates`:
```
url, firma, jurisdiction, ico, registry {source, konatelia, lookup_ok, lookup_error},
phones [{cislo, kontext_pred, kontext_po, vzdialenost_od_konatela, blizke_meno,
          blizky_email, stranka, typ_pravdepodobne}],
emails [{email, kontext_pred, kontext_po, stranka, typ_pravdepodobne}],
kandidati_meno [{meno, rola, zdroj, confidence, kontext}],
scraped_pages, scrape_warnings
```

---

### 1.8 Fetch fallback reťaz

`fetch_text_with_fallback()` (riadky 769–800):
1. `fetch_html_httpx()` — sync httpx, 8s timeout, UA rotácia
2. `fetch_html_cloudscraper_with_ua()` — cloudscraper, 2 pokusy, 10s
3. `fetch_html_playwright()` — headless Chromium, wait domcontentloaded + 1.5s
4. `fetch_html_scrapling()` — StealthyFetcher → AsyncFetcher fallback

V `_scrape_all_pages()`: Playwright bežia vždy (aj keď httpx stačí) pre podmienky/VOP stránky. Max 6 Playwright stránok (riadok 4872: `if len(_pw_fetched_urls) >= 6: break`).

---

### 1.9 Ďalšie dôležité funkcie

**`associate_persons_with_roles()`** (riadky 1383–1727) — hlavný person extractor:
- Rozpozná smer asociácie podľa `:` (meno za rolou) alebo `–/-/,` (meno pred rolou)
- Typ 1: `_ZIVNOSTNIK_ACTION_RE` — "prevádzkovateľom je", "pod obchodným menom"
- Typ 2: `_ICO_POSITIONAL_RE` — meno tesne pred IČO
- Typ 3: `_STATUTAR_SRO_RE` — meno tesne za "s.r.o./a.s."
- Typ 4: `_SELF_INTRO_RE` + `_OWNER_INTENT_RE` — "volám sa Erika" + kontext majiteľa
- Role levels: 3.3 (konateľ/CEO/majiteľ) > 3.2 (gen.riaditeľ) > 3.1 (riaditeľ) > 2 (zodpovedn.vedúci) > 1 (manažér)
- Filter: conf≤2 bez roly sa zahodí; neznáme meno (nie v `_SK_FIRST_NAMES`) s conf<5 zahodí

**`detect_jurisdiction()`** (riadky 3512–3672):
- Signály: TLD (+1), DIČ prefix SK/CZ (+4 autoritatívny), štát name (+3), mesto (+2), PSČ rozsah (+1)
- Dvojfázové: IČO/DIČ z full textu, ostatné z posledných 50k znakov

**`extract_with_ai()`** (riadky 1944–2084):
- Azure OpenAI, GPT deployment z env `OPENAI_DEPLOYMENT_NAME` (default `gpt-4o-mini`)
- `temperature=0.1`, `response_format={"type":"json_object"}`
- Post-AI phone korekcia: ak AI vybrala telefón ktorý nie je blízko mena, nahradí lepším

---

## 2. FRONTEND (wector/index.html)

### 2.1 UI Sekcie

| Sekcia | CSS class | Čo obsahuje |
|--------|-----------|-------------|
| Navbar | `.navbar` | Logo, HOT/WARM/Total stats, lang button, theme toggle |
| Sidebar | `.sidebar` | Filter: All leads, Tier (HOT/WARM/COOL/DEAD), Status |
| Quick Add | `.quick-add` | URL input, Scrape button, Import/Batch button |
| Bulk bar | `#bulkBar` | Zmeniť status, Export CSV, Zmazať (zobrazí sa pri výbere riadkov) |
| Table | `.table-wrap` | Hlavná tabuľka leadov |
| Candidates modal | `#modalRoot` | 3 stĺpce: Registry, Telefóny, Emaily + score preview |
| Drawer | `#drawerRoot` | Pravý panel: kontakty, analýza, timeline, aktivity |
| Email composer | `#modalRoot` | mailto form |
| Batch modal | `#modalRoot` | Textarea pre URL, CSV upload, progress bar |
| Toast | `#toastWrap` | Notifikácie (ok/err/warn) |

---

### 2.2 Tabuľka — stĺpce a backend polia

| # | Hlavička | CSS | Backend pole | Poznámka |
|---|----------|-----|--------------|---------|
| 1 | ☐ | `.chk` | — | Checkbox pre bulk |
| 2 | # | `.col-num` | index (i+1) | Poradové číslo |
| 3 | Shop | `.shop-cell` | `l.shop` + `l.ico` | domain + "IČO: 12345678" |
| 4 | Konateľ | `.cell-name` | `l.konatel` + `l.rola` | Obe editovateľné inline |
| 5 | Telefón | `.mono` | `l.telefon` + `l.phone_type` | phone_type badge |
| 6 | Email | `.truncate` | `l.email` | Editovateľný inline |
| 7 | Skóre | `.score-chip[data-tier]` | `l.score` | Farba podľa tier |
| 8 | Tier | `.tier.tier-{X}` | `l.tier` | HOT/WARM/COOL/DEAD |
| 9 | Status | `.status-select` | `l.status` | Select dropdown |
| 10 | Akcie | `.actions` | — | 5 buttonov |

**Sub-riadky** (pod každým lead-row):
- `.reasoning-row` — `l.reasoning` (sivý text, celý colspan 10)
- `.other-row` — `l.other_contacts` (modrý text: "Ďalší kontakt: Meno (rola) +421...")

**Akcie buttony** (order): Kandidáti (users), Volaj (phone), Email (mail), LinkedIn, More (...)

---

### 2.3 Drawer — sekcie a polia

| Sekcia | Backend pole |
|--------|-------------|
| **Head — meno** | `l.konatel || l.shop` (editovateľný) |
| **Head — rola** | `l.rola` (editovateľný) |
| **Head — score** | `l.score` (číslo, farba podľa tier) |
| **Head — url** | tier badge + `l.shop` + `l.ico` |
| **Kontakty — tel** | `l.telefon` (editovateľný, copy button) |
| **Kontakty — email** | `l.email` (editovateľný, copy button) |
| **Kontakty — linkedin** | generovaný URL z `l.konatel + l.shop` |
| **Ďalšie kontakty** | `l.other_contacts` (name, role, phone) |
| **Analýza — score circle** | `l.score + l.tier` (SVG kruh) |
| **Analýza — breakdown** | `l.score_breakdown` (array stringov, +/- prefix) |
| **Analýza — text** | `l.reasoning` |
| **Analýza — zamestnanci** | `l.employee_count + l.employee_category` |
| **Timeline** | `l.timeline` (array {type, date, text}) |
| **Aktivita** | lokálne — uloží do `l.timeline + l.notes` |
| **Ďalší krok** | tier-based text (na_hot/warm/cool/dead z i18n) |

---

### 2.4 CSS farby a fonty

**Dark mode (default):**
```css
--bg: #0b0c0f;          /* hlavné pozadie */
--sidebar: #0e0f13;
--card: #141519;
--card-2: #16171c;
--surface: #1a1c22;
--border: #23252b;
--border-2: #2e3138;
--text: #e6e7ea;
--muted: #8a8f98;
--muted-2: #a8adb8;
--accent: #6366f1;       /* indigo — buttony, focus */
--accent-hover: #5457e5;
--accent-soft: rgba(99,102,241,.14);
--hot: #ef4444;          /* červená */
--warm: #f97316;         /* oranžová */
--cool: #3b82f6;         /* modrá */
--dead: #6b7280;         /* sivá */
--green: #22c55e;
--purple: #a855f7;
```

**Font:** `"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`, 13.5px base, 1.45 line-height.

**Light mode** prepisuje len pozadia a text farby. Tier/accent farby zostávajú rovnaké.

---

### 2.5 Dátový tok: runScrape() → UI

```
User: vloží URL → Enter/Scrape button
  ↓
runScrape() → POST /api/leads/scrape {url}
  ↓ backend response d = {action, primary_identifier, score, tier, extracted:{...}}
  ↓
Mapovanie (riadky 932–951):
  konatel  = nn(ext.contact_name)  || nn(d.meno)  || ""
  telefon  = nn(ext.phone)         || nn(d.telefon) || ""
  email    = nn(ext.email)         || nn(d.email)  || ""
  score    = d.score (alebo estimateScore ak nie je číslo)
  tier     = d.tier || tierFromScore(score)
  ico      = ext.ico || d.ico || ""
  reasoning = ext.reasoning || d.reasoning || ""
  phone_type = ext.phone_type || ""
  phone_confidence = ext.phone_confidence || ""
  employee_count = ext.employee_count || ""
  employee_category = ext.employee_category || ""
  name_found_on_web = ext.name_found_on_web || false
  score_breakdown = ext.score_breakdown || []
  all_phones = ext.all_phones || []
  other_contacts = ext.other_contacts || []
  registry_source = ext.registry_source || ""
  ↓
hydrate(lead) → leads.unshift(lead) → save() → renderTable()
```

**nn() funkcia** (riadok 967): ošetrí `null`, `"null"`, `"None"`, `"N/A"` → `""`

**estimateScore()** (riadok 966) — fallback keď backend nevrátil číslo:
```javascript
let s=0;
if(konatel) s+=50;
if(telefon) s += isPersonalPhone(telefon) ? 20 : 10;
if(email) s+=5;
```
Max 75 bodov, COOL threshold 30 → iný výsledok ako backend.

**isPersonalPhone()** (riadok 690) — frontend detekcia:
```javascript
/^(\+421\s?9|09|\+420\s?[67]|0[67])/.test(...)
```
Len mobily, nie pevné linky.

---

### 2.6 Candidates modal — scorePreview scoring

`maybeRenderScorePreview()` (riadky 1065–1090):
```
+30  Registry konateľ
+20  Personal telefón  ALEBO  +10  Info telefón
+15  Personal email    ALEBO  +5   Generic email
+20  Rola (funkcia konateľa)
```
Max = 85. Toto zodpovedá `SCORE_CONFIG` v backende.

---

### 2.7 Phone_type badge v tabuľke

`phoneTypeBadge()` (riadky 807–813):
- `"personal"` → zelený badge "Osobný"
- `"predpokladaný_osobný"` → oranžový badge "~Osobný"
- `"info"` → sivý badge "Info"
- iné / prázdne → žiadny badge

---

### 2.8 scoreCircle() funkcia

SVG (riadky 969–982): kruh 44×44px, polomer 17, stroke-width 3.5. Dash offset = score/100 × obvod. Farba podľa tier. Číslo score v strede. Použitie: v drawer sekcia Analýza.

---

## 3. KONFLIKTY A DEAD CODE

### 3.1 TIER THRESHOLD MISMATCH (kritický)

**Frontend `tierFromScore()`** (riadok 626): `COOL` začína od **30**
**Backend `TIER_RANGES`**: `COOL` začína od **40**, DEAD = 0–39

Dopad: `estimateScore()` a `recalcScore()` používajú frontend threshold. Lead so skóre 35 → backend: DEAD, frontend recalc: COOL. Nastane keď user edituje pole inline alebo keď backend nevráti score.

---

### 3.2 recalcScore() — iná logika ako backend

```javascript
function recalcScore(l) {
  let s = 0;
  if (l.konatel) s += 50;   // backend: +25 alebo +15
  if (l.telefon) s += isPersonalPhone ? 20 : 10;
  if (l.email) s += 5;
  return s;
}
```
Pri inline editácii sa backend skóre (vrátane registry_source +15, employee +10, name_found +10) zahodí a nahradí jednoduchým frontend vzorcom.

---

### 3.3 fetch_html_scrapingbee() — DEAD CODE (riadky 448–452)

```python
def fetch_html_scrapingbee(url, render_js=True):
    """ScrapingBee — kredity vyčerpané."""
    if not SCRAPINGBEE_API_KEY:
        return b""
    return b""   # ← vždy prázdne
```
Nikdy nič nevráti. Nikde nie je volaná.

---

### 3.4 fetch_raw_bytes_scrapingbee() — ZAVÁDZAJÚCI NÁZOV (riadky 454–456)

```python
def fetch_raw_bytes_scrapingbee(url):
    return fetch_html_httpx(url)  # ← len alias
```
Volá sa v `debug_scrape()` ale robí rovnako ako httpx. Názov naznačuje ScrapingBee.

---

### 3.5 fetch_html_cloudscraper() — NIKDE SA NEVOLÁ (riadky 458–468)

Definovaná (bez UA rotácie), ale vo fetch reťazi sa používa len `fetch_html_cloudscraper_with_ua()`. Dead code.

---

### 3.6 _auto_select_best_contact() — ORPHAN (riadky 4110–4160)

Definovaná, ale nie je volaná z žiadneho endpointu ani inej funkcie.

---

### 3.7 _infer_phone_type() — ORPHAN (riadky 4256–4268)

Definovaná, ale nie je volaná z žiadneho endpointu.

---

### 3.8 SCORE_CONFIG.fallback_high_confidence a fallback_low_confidence — NIKDY NEPOUŽITÉ

Definované na riadkoch 1119–1120 (`10` a `0`), ale `_calculate_score()` ich nečíta. Pravdepodobne zvyšok staršej verzie.

---

### 3.9 SCORE_CONFIG.delivery_phone — BEZ EFEKTU

Hodnota `0` (riadok 1113), ale `_calculate_score()` nemá vetvu pre "delivery" phone_type.

---

### 3.10 registry_source v /api/leads/scrape — AI POLE, NIE REGISTRY (kritické)

**`/api/leads/scrape`**: `registry_source = extracted.get("registry_source", "")` — toto je z AI JSON odpovede, nie z ORSR/ARES. Scrape endpoint **neimportuje** `registry_lookup.py`.

**`/api/leads/candidates`**: Volá `lookup_registry()` z `registry_lookup.py` — skutočný ORSR/ARES lookup.

Dôsledok: Pole `registry_source` v scrape výsledku (a teda +15 bodov v scoring) závisí od toho či AI "rozhodne" vrátiť toto pole. Nie je garantované ani konzistentné.

---

### 3.11 saveLeadFromCandidates() — API MISMATCH (kritický)

Frontend (riadok 1101) volá:
```javascript
api("/api/leads/select", { url:..., konatel:pv.k, phone:pv.p, email:pv.em, ico:... })
```

Backend `SelectRequest` (riadok 4273) očakáva:
```python
class SelectRequest(BaseModel):
    url: str
    selected: dict      # ← chýba!
    metadata: Optional[dict] = None
```

Pydantic odmietne request (HTTP 422 — `selected` je required field bez defaultu). Frontend zachytí chybu v `try/catch(e){}` a ignoruje ju — používa len lokálne vypočítané `pv.score`. Backend select nikdy neprebehne úspešne z Candidates modalu.

---

### 3.12 DIAG kód v produkcii (riadky 2934–2954)

V `/api/leads/scrape` (produkčný endpoint) beží pri KAŽDOM scrape:
```python
_diag_phones = ["420 725 883 611", "421 915 741 895", "420469638570", "420469638558"]
_janota_pos = combined_text.find("Martin Janota")
```
Hľadá konkrétne testovacie čísla a meno "Martin Janota". Debug code.

---

### 3.13 Backend polia ktoré frontend ignoruje (posiela, ale nezobrazí)

| Pole | Uloží sa v lead | Zobrazí sa |
|------|----------------|------------|
| `all_phones` | ÁNO (`l.all_phones`) | NIE |
| `phone_confidence` | ÁNO (`l.phone_confidence`) | NIE |
| `name_found_on_web` | ÁNO (`l.name_found_on_web`) | NIE |
| `registry_source` | ÁNO (`l.registry_source`) | NIE |

`employee_count` a `employee_category` sa zobrazujú v drawer Analysis sekcii.

---

### 3.14 Frontend polia ktoré backend neposiela

| Frontend pole | Backend ekvivalent | Poznámka |
|--------------|-------------------|---------|
| `l.shop` | `primary_identifier` | Frontend robí `domainOnly()` |
| `l.konatel` | `extracted.contact_name` | Mapovanie v runScrape |
| `l.telefon` | `extracted.phone` | Mapovanie |
| `l.rola` | `extracted.contact_role` | Mapovanie |

Polia `timeline`, `status`, `notes`, `archived` sú čisto frontend (localStorage).

---

### 3.15 extract_text_from_html() — limit offset bug

Riadok 695:
```python
return full[:15000] + " ... " + full[-35000:]
```
Funkcia má v docstringu "Limit 25 000 znakov" ale vracia **50 000 + 5** znakov (15k + " ... " + 35k). Limit check na riadku 693: `if len(full) <= 25000: return full` — teda ak text je kratší ako 25k, vráti celý, inak 50k. Komentár je nesprávny.

---

## 4. VERZIA

Toto je najnovšia verzia. Všetky features sú prítomné:

| Feature | Prítomné | Kde |
|---------|----------|-----|
| `scoreCircle()` SVG | ÁNO | index.html riadok 969 |
| `phone_type` logika (personal/predpokladaný/info) | ÁNO | main.py riadok 2239 |
| `nn()` funkcia | ÁNO | index.html riadok 967 |
| `reasoning` pole | ÁNO | tabuľka sub-row + drawer |
| `other_contacts` pole | ÁNO | tabuľka + drawer |
| `score_breakdown` | ÁNO | drawer Analysis |
| Typ 3 (štatutár za s.r.o.) v `associate_persons_with_roles` | ÁNO | main.py riadok 1619 |
| Typ 4 (self-intro cross-reference) | ÁNO | main.py riadok 1646 |
| `FORCE_PLAYWRIGHT=1` env flag | ÁNO | main.py riadok 2631 |
| `osoby` pole v `/api/leads/raw-extract` | ÁNO | main.py riadok 3700 |
| PDF extraction (pdfplumber) | ÁNO | main.py riadok 2551 |
| `detect_jurisdiction()` | ÁNO | main.py riadok 3512 |
| Kandidáti modal (3 stĺpce) | ÁNO | index.html riadok 988 |
| Batch scrape modal | ÁNO | index.html riadok 1399 |
| i18n (SK/CZ/PL/EN) | ÁNO | index.html riadok 517 |
| Dark/Light theme | ÁNO | index.html riadok 1526 |
