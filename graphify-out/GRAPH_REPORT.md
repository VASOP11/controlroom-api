# Graph Report - .  (2026-06-25)

## Corpus Check
- Large corpus: 2014 files � ~5,113,672 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 484 nodes · 795 edges · 58 communities (44 shown, 14 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 47 edges (avg confidence: 0.84)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_DB Schema Migrations|DB Schema Migrations]]
- [[_COMMUNITY_Registry Lookup Cache|Registry Lookup Cache]]
- [[_COMMUNITY_Benchmark & Test Regression|Benchmark & Test Regression]]
- [[_COMMUNITY_FastAPI Core Endpoints|FastAPI Core Endpoints]]
- [[_COMMUNITY_Contact Extraction Pipeline|Contact Extraction Pipeline]]
- [[_COMMUNITY_Person-Role Extraction|Person-Role Extraction]]
- [[_COMMUNITY_React Frontend|React Frontend]]
- [[_COMMUNITY_Benchmark Runner|Benchmark Runner]]
- [[_COMMUNITY_Scrape Infrastructure|Scrape Infrastructure]]
- [[_COMMUNITY_System Integration Layer|System Integration Layer]]
- [[_COMMUNITY_Design System Config|Design System Config]]
- [[_COMMUNITY_Domain Utils & Role Scoring|Domain Utils & Role Scoring]]
- [[_COMMUNITY_AI Contact Extraction|AI Contact Extraction]]
- [[_COMMUNITY_Batch Processor|Batch Processor]]
- [[_COMMUNITY_Core Extraction Functions|Core Extraction Functions]]
- [[_COMMUNITY_Phone & ICO Parsing|Phone & ICO Parsing]]
- [[_COMMUNITY_HTTP Fetch Fallbacks|HTTP Fetch Fallbacks]]
- [[_COMMUNITY_Main Backup & Auth|Main Backup & Auth]]
- [[_COMMUNITY_Lead CRUD & Bulk Scoring|Lead CRUD & Bulk Scoring]]
- [[_COMMUNITY_React UI Components|React UI Components]]
- [[_COMMUNITY_Name Processing|Name Processing]]
- [[_COMMUNITY_Source Channels|Source Channels]]
- [[_COMMUNITY_PWA Manifest|PWA Manifest]]
- [[_COMMUNITY_Scoring Module|Scoring Module]]
- [[_COMMUNITY_Phone-Person Pairing|Phone-Person Pairing]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]

## God Nodes (most connected - your core abstractions)
1. `_scrape_all_pages()` - 38 edges
2. `associate_persons_with_roles()` - 28 edges
3. `extract_all_candidates()` - 23 edges
4. `_extract_cisla_ico()` - 16 edges
5. `candidates_endpoint()` - 13 edges
6. `run_one()` - 11 edges
7. `Lead` - 10 edges
8. `OrganizationConfig` - 10 edges
9. `lookup_orsr()` - 10 edges
10. `main.py — SQLAlchemy engine + async_session + models` - 10 edges

## Surprising Connections (you probably didn't know these)
- `frontend/src/App.js — React CRM frontend` --semantically_similar_to--> `Wector Index HTML (single-file SPA)`  [INFERRED] [semantically similar]
  frontend/src/App.js → wector/index.html
- `Wector v6.16 Test Report (HTML)` --references--> `main.py — SQLAlchemy engine + async_session + models`  [INFERRED]
  test_report_v6.16.html → main.py
- `update()` --semantically_similar_to--> `update_rules()`  [INFERRED] [semantically similar]
  update_contact_scoring.py → update_scoring_rules1.py
- `update_rules()` --semantically_similar_to--> `contact_level scoring rule`  [INFERRED] [semantically similar]
  update_scoring_rules1.py → update_contact_scoring.py
- `batch_run.py - batch web scraper without ground truth` --semantically_similar_to--> `benchmark_run.py - benchmarking against ground truth`  [INFERRED] [semantically similar]
  batch_run.py → benchmark_run.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Design skills ecosystem for B2B dashboard** — design_impeccable_system, design_emil_design_eng, design_taste_skill [INFERRED]
- **Core design principles** — product_design_principles_clarity, product_design_principles_professional, product_design_principles_performance [INFERRED]
- **Web scraping and data extraction pipeline family** — batch_run_scraper, benchmark_run_ground_truth, bulk_scrape_missing_script, diag_names_test_script [INFERRED]
- **Core data extraction functions** — batch_run_extract_email_function, batch_run_extract_phone_function, batch_run_person_association, batch_run_jurisdiction_detection [INFERRED]
- **Design system components (colors, typography, spacing)** — product_color_palette_neutral, product_typography_system, product_spacing_system_4px_grid [INFERRED]
- **Benchmark Pipeline: ground truth CSV -> benchmark_run -> analyze_v7/v7b** — ground_truth_csv, benchmark_run, analyze_v7, analyze_v7b [EXTRACTED 0.95]
- **Batch Scrape Pipeline: batch_300.txt -> batch_run -> batch_summary** — batch_run, batch_summary, main_engine [EXTRACTED 0.95]
- **Wector UI Family: index + dashboard + bundle_v2 share design system** — wector_index, wector_dashboard, wector_bundle_v2 [INFERRED 0.85]
- **Core test suite calling main.py extraction functions (_scrape_all_pages, associate_persons_with_roles, extract_all_candidates)** — test_martin, test_minilove, test_phone_pairing, test_subpage_discovery, test_jurisdiction, test_false_positives [EXTRACTED 1.00]
- **All tests exercising /api/leads/candidates endpoint against localhost:8000** — test_candidates, test_candidates_batch, test_report_ui_preview [EXTRACTED 1.00]
- **ORSR registry lookup debug and verification pipeline** — test_orsr_debug, test_orsr_fresh, registry_lookup, concept_registry_cache [EXTRACTED 0.95]

## Communities (58 total, 14 thin omitted)

### Community 0 - "DB Schema Migrations"
Cohesion: 0.08
Nodes (25): add(), Base, extract_contact_info(), rate_contact(), Vráti (telefón, email, meno_osoby, level, body)., Vráti (body, úroveň) podľa zistených kontaktov.     level 0: nič     level 1:, update_all_leads(), Contact Quality Level (0-3: none/email/phone+name/direct+phone+name) (+17 more)

### Community 1 - "Registry Lookup Cache"
Cohesion: 0.12
Nodes (28): _cache_get(), _cache_set(), _load_cache(), lookup_ares(), lookup_cz(), _lookup_finstat_sk(), lookup_orsr(), lookup_registry() (+20 more)

### Community 2 - "Benchmark & Test Regression"
Cohesion: 0.12
Nodes (21): AsyncClient, False Positive Name Filter (courier/delivery brands), Lead Scoring Tiers (HOT/WARM/DEAD), v6.16 vs v6.15 Benchmark Regression Tracking, generate_html_report(), main(), Test v6.16 candidates endpoint — batch 37 shopov. Output: CSV tabuľka + HTML rep, test_one() (+13 more)

### Community 3 - "FastAPI Core Endpoints"
Cohesion: 0.11
Nodes (15): JSONResponse, adjust_lead(), AdjustRequest, create_template(), EmailDraftRequest, EmailTemplateCreate, generate_email_draft(), _get_employee_count() (+7 more)

### Community 4 - "Contact Extraction Pipeline"
Cohesion: 0.10
Nodes (22): candidates_endpoint(), _classify_email_type(), _classify_phone_type(), _email_is_ignored(), _estimate_firm_size(), _find_email_near_name(), is_generic_email(), is_ignored_contact() (+14 more)

### Community 5 - "Person-Role Extraction"
Cohesion: 0.17
Nodes (15): main(), associate_persons_with_roles(), _extract_pdf_text(), _find_candidate_subpages(), Nájde mená osôb a priradí im roly podľa okolitého textu.      Smer asociácie u, Skenuje VŠETKY <a href> na stránke — nie len nav/header.     Hľadá URLs s kľúčo, Stiahne PDF cez httpx a extrahuje text cez pdfplumber.     Max 5 MB, max 20 str, Optimalizované scrapovanie pre Render free tier.      Stratégia (poradí kroky) (+7 more)

### Community 6 - "React Frontend"
Cohesion: 0.10
Nodes (20): browserslist, development, production, dependencies, axios, react, react-dom, react-scripts (+12 more)

### Community 7 - "Benchmark Runner"
Cohesion: 0.19
Nodes (17): main(), match_email(), match_golden(), match_name(), match_phone(), match_rola(), norm_email(), norm_name() (+9 more)

### Community 8 - "Scrape Infrastructure"
Cohesion: 0.14
Nodes (17): API endpoint /api/leads/raw-extract, API endpoint /api/leads/scrape, get_leads_without_name(), main(), Získa ID a URL leadov, ktoré nemajú meno, ale majú URL., Odošle URL na scrapovací endpoint., scrape_lead(), Radar Ping — HOT row CSS animation signature (+9 more)

### Community 9 - "System Integration Layer"
Cohesion: 0.14
Nodes (17): axios_http_client, azure_openai_llm, bulk_scoring_workflow, email_template_model, fastapi_backend_framework, frontend_app_js_component, frontend_index_html_document, frontend_index_js_bootstrap (+9 more)

### Community 10 - "Design System Config"
Cohesion: 0.12
Nodes (17): Emil Design Engineering, Impeccable Design System, Linear/Stripe Dashboard aesthetic, Taste Skill, B2B Sales Intelligence & Outreach Dashboard, SK/CZ e-commerce target market, Single accent color (professional blue #0066CC), Neutral color palette (white, grays, near-black) (+9 more)

### Community 11 - "Domain Utils & Role Scoring"
Cohesion: 0.14
Nodes (16): debug_scrape(), _domain_of(), is_personal_email(), Bodovanie podľa role_category z AI výstupu (nová logika)., Vytiahne holú doménu z URL alebo emailu (bez www., bez cesty)., True ak je email priamy menný/firemný:     - časť pred @ obsahuje časť mena/pri, Bodovanie kontaktu. Ak AI vrátila role_category, použije novú logiku (Fáza 3)., Diagnostický endpoint – vráti surový text, encoding diagnostiku a AI extrakciu b (+8 more)

### Community 12 - "AI Contact Extraction"
Cohesion: 0.15
Nodes (15): Any, _context(), extract_all_candidates(), extract_jsonld_contacts(), extract_with_ai(), has_good_contacts(), is_valid_phone(), Vráti text okolo [start:end] s ±width znakov. (+7 more)

### Community 13 - "Batch Processor"
Cohesion: 0.19
Nodes (12): _error_row(), _log(), main(), batch_run.py — hromadný scraper bez ground truth Vstup:  batch_300.txt (jeden UR, run_one(), _sync_scrape(), ThreadPoolExecutor Hard Timeout Pattern (Windows Playwright kill), Jurisdiction Detection (SK vs CZ cross-border) (+4 more)

### Community 14 - "Core Extraction Functions"
Cohesion: 0.19
Nodes (13): extract_all_candidates function for email extraction, _extract_cisla_ico function for phone and ICO extraction, detect_jurisdiction function, associate_persons_with_roles function, _scrape_all_pages function, batch_run.py - batch web scraper without ground truth, batch_summary.py - results analysis script, benchmark_run.py - benchmarking against ground truth (+5 more)

### Community 15 - "Phone & ICO Parsing"
Cohesion: 0.19
Nodes (12): _all_phone_positions(), _ctx_score(), _extract_cisla_ico(), _is_ico_context(), Vráti True ak kontext okolo čísla naznačuje že ide o IČO/DIČ/IBAN, nie telefón., Skóre kontextu: +3 role keyword, +2 meno osoby, +1 tel/mobil label., Vráti všetky pozície telefónu v texte — formátovaná aj kompaktná verzia (bez med, Context-aware deduplikácia telefónov pre raw_extract endpoint.      Rovnaké no (+4 more)

### Community 16 - "HTTP Fetch Fallbacks"
Cohesion: 0.17
Nodes (12): fetch_html_playwright(), fetch_html_scrapling(), fetch_text_with_fallback(), HeurekaSourceRequest, is_garbled_content(), _is_market(), Nájde e-shopy v Heureka kategórii., Vráti True ak je text binárny garbage (Cloudflare blokoval request).     Prah: (+4 more)

### Community 17 - "Main Backup & Auth"
Cohesion: 0.24
Nodes (7): HTTPAuthorizationCredentials, chat(), LeadScoreRequest, OpenAIChatRequest, score_lead(), verify_jwt(), verify_jwt()

### Community 18 - "Lead CRUD & Bulk Scoring"
Cohesion: 0.31
Nodes (9): BaseModel, bulk_score(), BulkLeadItem, BulkScoreRequest, BulkScoreResponseItem, create_lead(), evaluate_lead(), LeadCreate (+1 more)

### Community 19 - "React UI Components"
Cohesion: 0.36
Nodes (3): AddLeadForm(), Dashboard(), EmailTemplates()

### Community 20 - "Name Processing"
Cohesion: 0.25
Nodes (8): _de_accent(), _extract_klucove_slova(), _first_name_known(), _is_blocked_name(), True ak prvé slovo mena je v _SK_FIRST_NAMES (bez diakritiky)., Vráti True ak raw string vyzerá ako UI token, mesto alebo produkt — nie reálna o, Vráti zoznam kľúčových slov a mien nájdených v kontexte telefónneho čísla., Odstráni diakritiku — 'Nákupný' → 'Nakupny'. Umožní porovnanie blacklistu     a

### Community 21 - "Source Channels"
Cohesion: 0.25
Nodes (8): fetch_html_cloudscraper_with_ua(), fetch_html_httpx(), _is_agency(), ProfesiaSourceRequest, Získa HTML ako RAW BYTES pomocou httpx s rotáciou User-Agent headerov., Nájde firmy inzerujúce na profesia.sk pre daný keyword a vráti ich URL na scrape, Cloudscraper s rotáciou UA a retry 3x pri failure.     Jeden scraper instance (, source_profesia()

### Community 22 - "PWA Manifest"
Cohesion: 0.25
Nodes (7): background_color, display, icons, name, short_name, start_url, theme_color

### Community 23 - "Scoring Module"
Cohesion: 0.32
Nodes (7): calculate_lead_score(), _deaccent(), is_person_name(), Single source of truth for lead scoring.  lead_data keys:   name_source       "r, Map velkost_category to scoring bucket., True iff text looks like a real person name (Meno Priezvisko)., _size_bucket()

### Community 24 - "Phone-Person Pairing"
Cohesion: 0.53
Nodes (5): Phone-to-Person Proximity Pairing Algorithm, main(), Mirrors the logic in main.py _telefon_pre_osobu, strip_accents(), telefon_pre_osobu()

### Community 25 - "Community 25"
Cohesion: 0.47
Nodes (5): main(), norm_phone(), Benchmark test: 40 URL scraping cez nasadený debug endpoint na Renderi. Porovnáv, Normalizuj telefón na holé lokálne číslo pre porovnanie.     +421908761091 → 908, scrape_one()

### Community 26 - "Community 26"
Cohesion: 0.40
Nodes (5): _generate_action_note(), Generate action note — what user should do with this contact., User selected the correct values from candidates UI — score + save., select_lead(), SelectRequest

### Community 27 - "Community 27"
Cohesion: 0.50
Nodes (4): extract_text_from_html(), filter_boilerplate(), Prijíma bytes – explicitne dekódujeme UTF-8 pred BS4 aby sme obišli     Unicode, Zahodí vety obsahujúce cookie/GDPR/legal boilerplate.     Uvoľní miesto v 8000-

### Community 28 - "Community 28"
Cohesion: 0.83
Nodes (3): get_leads_with_url(), main(), scrape_lead()

### Community 30 - "Community 30"
Cohesion: 0.67
Nodes (3): _deaccent(), v7 benchmark test — spusti po naplnení benchmark_groundtruth.csv  Použitie:, run()

### Community 33 - "Community 33"
Cohesion: 0.67
Nodes (3): Control Room API scrape endpoint, SQLAlchemy database engine with PostgreSQL, bulk_scrape_missing.py - scrape leads without names

### Community 35 - "Community 35"
Cohesion: 0.67
Nodes (3): confirm_lead(), ConfirmRequest, Potvrdenie telefónu používateľom → tier sa zamkne na HOT/WARM, confidence = CONF

## Knowledge Gaps
- **53 isolated node(s):** `proxy`, `name`, `version`, `private`, `axios` (+48 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `main.py — SQLAlchemy engine + async_session + models` connect `DB Schema Migrations` to `Scrape Infrastructure`, `Person-Role Extraction`, `Batch Processor`, `Benchmark Runner`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Why does `_scrape_all_pages()` connect `Person-Role Extraction` to `FastAPI Core Endpoints`, `Contact Extraction Pipeline`, `Benchmark Runner`, `Community 42`, `Domain Utils & Role Scoring`, `AI Contact Extraction`, `Batch Processor`, `Phone & ICO Parsing`, `HTTP Fetch Fallbacks`, `Source Channels`, `Phone-Person Pairing`, `Community 27`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **What connects `batch_run.py — hromadný scraper bez ground truth Vstup:  batch_300.txt (jeden UR`, `Spustí _scrape_all_pages vo vlastnom event loope v threade.`, `Vráti (body, úroveň) podľa zistených kontaktov.     level 0: nič     level 1:` to the rest of the system?**
  _145 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `DB Schema Migrations` be split into smaller, more focused modules?**
  _Cohesion score 0.08205128205128205 - nodes in this community are weakly interconnected._
- **Should `Registry Lookup Cache` be split into smaller, more focused modules?**
  _Cohesion score 0.11612903225806452 - nodes in this community are weakly interconnected._
- **Should `Benchmark & Test Regression` be split into smaller, more focused modules?**
  _Cohesion score 0.11904761904761904 - nodes in this community are weakly interconnected._
- **Should `FastAPI Core Endpoints` be split into smaller, more focused modules?**
  _Cohesion score 0.1067193675889328 - nodes in this community are weakly interconnected._