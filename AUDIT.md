# AUDIT SYSTÉMU — pipeline lead-scrapingu (2026-07-10)

Stav ku dňu auditu: main.py po 9 opravách + DÔKAZ sekcia, pred opravou svihej.cz bugu.
Referencie na riadky platia pre aktuálny working tree (necommitnuté).

---

## 0. Executive summary

Pipeline: scrape (≤30 podstránok + PDF) → extrakcia IČO → registry lookup (ARES/ORSR/RPO)
→ extrakcia kandidátov (telefóny/emaily/mená) → párovanie konateľ↔číslo → skóre/tier.

Hlavné zistenie auditu: **každý krok si vyberie jedného "víťaza" lokálnou heuristikou
a ďalšie kroky mu bezvýhradne veria — neexistuje žiadna spätná krížová validácia.**
Keď prvý krok (výber IČO) siahne vedľa, celý zvyšok reťazca chybu nielen prenesie,
ale aj "potvrdí" (svihej.cz: zlé IČO → ARES vráti živnostníka Šimona Kracíka → jeho
meno je zhodou okolností na tímovej stránke → systém hlási HIGH confidence, skóre 89).

---

## 1. svihej.cz bug — presná diagnóza (2026-07-10)

**Symptóm:** konateľ = "Šimon Kracík" (správca webu / dodávateľ expedície),
skutočný zakladateľ Tomáš Vaněček skončil v `other_contacts`.

**Reťaz príčin (všetky overené reprodukciou):**

1. Web obsahuje 9 rôznych 8-ciferných IČO. Skutočné IČO firmy **10985301**
   (ŠVIHEJ JUMP ROPES s.r.o.) je v texte **12×**; IČO **09808833** (OSVČ Šimon
   Kracík) je tam **2×** — v GDPR podmienkach ako *"zpracovatel podílející se
   na expedici zboží (Šimon Kracík, IČ: 09808833 a PARSLEY TRADE s.r.o., IČO:
   17303354)"*.
2. `extract_ico_from_text` (registry_lookup.py:65) skóruje kandidátov kontextom
   ±50 znakov. 09808833 dostalo conf **9**:
   - +2 za "IČO" v kontexte — ale to "IČO:" patrí susednej firme PARSLEY TRADE;
   - +1 za `dič|dic` — regex **bez word boundary** matchol substring v slove
     "expe**dic**i";
   - +1 za "s.r.o." — opäť od PARSLEY TRADE.
   Skutočné IČO 10985301 dostalo max conf 8 ("IČO 10985301" pri výrobcovi),
   a `if conf > best_conf` je ostrá nerovnosť → **prvý výskyt s max conf vyhráva**.
   Frekvencia výskytu (12× vs 2×) sa neváži vôbec.
3. ARES lookup 09808833 vrátil `obchodniJmeno = "Šimon Kracík"` (živnostník —
   u OSVČ je obchodné meno totožné s menom osoby) → `konatel = "Šimon Kracík"`.
   Žiadna kontrola právnej formy ani zhody obchodného mena s brandom webu.
4. Meno "Šimon Kracík" JE na webe (tímová stránka, rola "Správce webu,
   automatizace"), 17 znakov od jeho čísla 723 126 359 a existuje
   simonkracik@svihej.cz → case `small_match`, confidence HIGH, skóre 89.
   **Chyba sa sama potvrdila.**

**Čo bug NIE JE:** nie je to cache problém (cache je kľúčovaná IČO-m, TTL 30 dní,
dáta pre cz_09808833 sú vecne správne — Kracík je reálny živnostník z Ostravy).
Nie je to ani CZ/SK zámena ako pri arno-obuv.sk.

**Zabijácky detail:** na webe je `DIČ: CZ10985301` — DIČ obsahuje IČO firmy.
Krížová kontrola DIČ↔IČO by tento prípad rozhodla deterministicky (viď 5.1).

---

## 2. Ako systém hľadá meno na stránke (4.1)

### Prehľadávané stránky
- Homepage → nav linky (`extract_nav_links`, main.py:2972, cap 20, prioritne
  kontakt/o-nás) + **všetky** `<a href>` s kľúčovými slovami VOP/kontakt/o-nás/
  team/impressum (`_find_candidate_subpages`, main.py:3062, cap 15 + 3 PDF).
- K tomu fixný zoznam ciest (obchodne-podmienky, vop, kontakt…), spolu cap
  **30 podstránok** (main.py:3290). Playwright fallback pre Cloudflare/JS
  stránky, PDF extrakcia pre VOP dokumenty.
- Footer sa nescrapuje osobitne — je súčasťou HTML každej stiahnutej stránky.

### Ako sa hľadá meno konateľa (main.py:2672-2689)
- Presný substring "Meno Priezvisko" (case-insensitive, s word-boundary
  kontrolou), **s diakritikou z registra**. Ak sa plné meno nenájde,
  fallback na samotné priezvisko. Ak sa nájde plné meno, priezvisko sa už nehľadá.
- meno@firma email (jan.novak@, novak@, jnovak@…) sa ráta ako pozícia mena
  (Pravidlo #4, `_find_name_at_email_pattern`, main.py:2456) — táto cesta JE
  diakriticky nezávislá (de-accent).

### Čo NIE JE ošetrené
| Prípad | Stav |
|---|---|
| Poradie "Priezvisko Meno" | čiastočne — plné meno zlyhá, ale priezvisko-fallback ho nájde |
| Tituly (Ing., Mgr.) | pred menom OK (nevadia substring hľadaniu); suffix ("…, PhD.") rozbije priezvisko-fallback (`split()[-1]` = "PhD.") |
| Skloňovanie priezviska ("Novákovej", "s Novákom") | ❌ nenájde sa — hľadá sa len presný tvar z registra |
| Web bez diakritiky ("Jan Novak" pri konateľovi "Ján Novák") | ❌ priame hľadanie zlyhá (zachráni len email pattern) |
| Ženské prechyľovanie CZ/SK (-ová vs -ova) | ❌ |

---

## 3. Ako sa meria vzdialenosť meno↔číslo (4.2)

- `_dist` (main.py:2705) = `min(abs(phone.abs_pos − name_pos))` — **obojsmerné**
  (meno pred aj za číslom). Empiricky overené na familium.sk (meno pred číslom).
- `near_names` pri telefóne (main.py:1851) = okno **±200 znakov na obe strany** →
  label "osoba: X", quality 5.
- Viac mien × viac čísel: pozície sa počítajú len pre meno konateľa z registra;
  vyberá sa globálne najbližší pár (min cez všetky kombinácie). Čísla označené
  menom **inej** osoby vylučuje z kandidátov na majiteľa `_is_owner_candidate`
  (main.py:2727 — oprava "Blanka Trajerová" prípadu).

### Slabiny (nájdené pri audite, zatiaľ neopravené)
1. **`abs_pos` je pozícia PRVÉHO výskytu čísla v texte** (main.py:1841
   `normalized.find(raw)`), nie výskytu najbližšieho k menu. Číslo opakované
   na každej stránke (footer) sa ukotví na prvý výskyt — vzdialenosť môže byť
   nezmyselne veľká alebo malá.
2. **Nekonzistentné súradnicové systémy:** `name_positions` sa počítajú na
   `norm_text` (všetky biele znaky → 1 medzera), `abs_pos` na `normalized`
   (len \n → medzera). Pri texte s množstvom viacnásobných medzier sa údaje
   rozchádzajú — "17 znakov od čísla" je približné, nie presné.

---

## 4. Registry lookup — kde zlyháva priradenie osoby (4.3)

### Známe prípady zlého priradenia
| Prípad | Mechanizmus | Rovnaká príčina? |
|---|---|---|
| arno-obuv.sk | správne IČO, zlý register (CZ IČO validné aj v SK) → opravené country-hintom z DIČ prefixu + cross-registry fallbackom (main.py:3577) | nie — krok 2 (lookup) |
| svihej.cz | zlé IČO vybrané spomedzi 9 na stránke (GDPR zoznam spracovateľov) | nie — krok 1 (extrakcia) |

Spoločný menovateľ: **rozhodnutie sa robí skoro a nikdy sa nevalidluje späť.**

### Cache
`registry_cache.json`, kľúč `cz_/sk_ + IČO`, TTL 30 dní. Nemôže spôsobiť zámenu
osôb (nekešuje sa doména→IČO), môže vrátiť max. 30 dní staré registrové dáta.

### Validácia po lookupe
**Žiadna.** Naopak: `company_name = registry > JSON-LD > doména` (main.py:3609)
— zlý lookup **premenuje celú firmu** (svihej.cz sa v systéme volá "Šimon Kracík").
Nekontroluje sa: právna forma (OSVČ vs s.r.o.), podobnosť obchodného mena
s brandom/doménou, výskyt priezviska konateľa kdekoľvek na webe.

---

## 5. Chronológia bugov v tejto sérii sessionov (4.4)

1. **IČO ako telefón** → guard `ico_digits_set` (main.py:1760)
2. **tel: href vs text** → strip tel:/phone:/mobil: prefixov (main.py:1789)
3. **Country hint bez medzery** ("CZ 12345678") → `CZ\s?\d` (registry_lookup.py:100)
4. **Bankový účet ako telefón** → `_BANK_CTX_RE` + lomka-kód-banky (main.py:1815)
5. **DIČ ako telefón** → prefix check CZ/SK pred číslom (main.py:1834)
6. **Produktový kód/EAN ako telefón s falošnou rolou** → `looks_like_phone` +
   `_PHONE_MARKER_RE` tie-break v `_phone_role_label` a `_sel_key` (main.py:2442, 2718)
7. **Číslo inej osoby vydávané za konateľovo** (Blanka Trajerová) →
   `_is_owner_candidate` (main.py:2727)
8. **svihej.cz: zlá osoba z GDPR zoznamu spracovateľov** → NEOPRAVENÉ (diagnóza hore)

### Spoločný vzor
Všetkých 8 bugov má rovnakú štruktúru: **regex nájde povrchový vzor, lokálne
kontextové okno (±50 až ±200 znakov) ho "potvrdí", a víťaz sa vyberie bez
globálnych signálov** (frekvencia, konzistencia DIČ↔IČO, zhoda brandu, právna
forma). Doterajšie opravy sú lokálne guardy (skip-listy) — každý nový typ
falošného kandidáta vyžaduje nový guard. Druhý opakujúci sa vzor: **substring
regexy bez word boundaries** ("dic" v "expedici", `IC` v `_ICO_RE`).

---

## 6. Čo systém nekontroluje a mal by (4.5) — odporúčania

> **Stav 2026-07-10 (po audite):** implementované 6.1, 6.3, 6.4, 6.6 a 6.7
> (jedna normalizácia + najbližší výskyt čísla). svihej.cz overený: IČO 10985301,
> Tomáš Vaněček, tel 773 655 596. familium.sk bez regresu (vzdialenosť 171→17,
> skóre 79→89). Neimplementované ostávajú: 6.2 (frekvencia), 6.5 (post-lookup
> validácia), 6.8 (skloňovanie).

Zoradené podľa pomeru prínos/náklad:

### 6.1 DIČ↔IČO krížová kontrola (rieši svihej.cz deterministicky)
Ak stránka obsahuje `DIČ: CZ10985301` / `IČ DPH: SK2020...`, číselná časť DIČ
u s.r.o. spravidla = IČO (CZ) alebo obsahuje IČO. Kandidát na IČO, ktorý sa
zhoduje s číslami v DIČ na tej istej stránke, má vyhrať bez ohľadu na conf skóre.

### 6.2 Frekvencia + váha umiestnenia
IČO 12× na webe (footer, fakturačná adresa, výrobca) vs 2× (GDPR odsek) —
počet výskytov pridať do conf. Bonus za kontext "fakturačn|prevádzkovateľ|
provozovatel|výrobce|sídlo".

### 6.3 Penalizácia third-party kontextu
Kontexty "zpracovatel", "dopravce", "přepravce", "zprostředkovatel", "platební
brána", "kurýr" v okolí IČO = takmer isto cudzia firma → conf −5. (GDPR stránky
sú zoznamy CUDZÍCH subjektov — dnes pôsobia ako pasca.)

### 6.4 Word boundaries v conf regexoch
`r'dič|dic|ič dph|ic dph'` → `r'\b(dič|dic)\b|ič dph|ic dph'`. Bonus +2 za
"ičo" viazať na label z vlastného regex matchu, nie na celé ±50 okno (dnes ho
požičiava susedná firma).

### 6.5 Post-lookup validácia (nová vrstva, ~20 riadkov)
Po registry lookupe overiť aspoň jedno z:
- právna forma je právnická osoba, ALEBO obchodné meno (osoba) sa zhoduje
  s brandom webu;
- normalizované obchodné meno zdieľa token s doménou/JSON-LD názvom
  ("ŠVIHEJ JUMP ROPES" ↔ svihej.cz ✓; "Šimon Kracík" ↔ svihej.cz ✗);
- priezvisko konateľa sa vyskytuje na webe mimo GDPR/VOP zoznamov.
Ak nič nesedí → confidence LOW + warning do reasoning, nie tichá dôvera.

### 6.6 Tímová stránka ako prioritný zdroj roly
Osoby s popiskom "Zakladatel/Spoluzakladatel/Majitel/CEO/jednatel/konateľ"
na /o-nas | /nas-tym stránke sú silnejší signál než registrový konateľ
z nevalidovaného IČO. svihej.cz: systém Vaněčka "Zakladatel" NAŠIEL
(other_contacts), ale registrová vetva ho prebila. Pravidlo: ak post-lookup
validácia (6.5) zlyhá a existuje web-osoba s founder/owner rolou → preferovať ju.

### 6.7 Presnosť vzdialenosti
Jedna normalizácia textu pre `name_positions` aj `abs_pos`; vzdialenosť počítať
k najbližšiemu výskytu čísla, nie k prvému.

### 6.8 Skloňovanie priezvisk
Hľadať aj kmeň priezviska (bez koncoviek -ová/-ovej/-ovou/-a/-u/-om) s word
boundary — lacná oprava, pokryje väčšinu pádov v SK/CZ.

---

## 7. Čo funguje dobre (nechať tak)

- Obojsmerné meranie vzdialenosti meno↔číslo (abs, ±200 okno).
- Cross-registry fallback CZ↔SK + country hint z DIČ prefixu.
- Guardy 1-7 z chronológie — každý rieši reálny nájdený prípad.
- `_is_owner_candidate` — správny smer (validácia namiesto slepej dôvery),
  vzor pre 6.5.
- meno@firma email pattern ako signál totožnosti (diakriticky nezávislý).
- Sekcia DÔKAZ (nová) — reasoning je teraz overiteľný proti webu.
