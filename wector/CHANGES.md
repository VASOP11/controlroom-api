# Wector — UI elevation (Part 2)

Baseline restored per request: **electric green** `hsl(145 100% 42%)` primary, **Geist** body +
**JetBrains Mono** headers, **off-white** `#FAFAF7` surface, **square 2–4px** radii, and the
**radar-ping** HOT signature. All work is in the single-file bundle `wector/index.html`
(final size **106 KB**, well under the 350 KB budget; original blue/Inter version preserved as
`index.html.bak`).

---

## taste-skill audit

Audit of the starting point, then the concrete moves made (each justified in one line):

- **Typography hierarchy — make the data the hero.** Headers, the wordmark and every *number*
  (stat values, score cells, the detail score) now render in JetBrains Mono while body copy is
  Geist; mono numerals read as instrument readouts, so firm → score → tier now scans top-down
  instead of competing at one weight.
- **Color discipline — green earns its scarcity.** Primary green is reserved for true actions
  (the Scraping CTA, focus rings, the active sort/tab indicator) and the radar signature; tiers
  keep their own hue ramp (HOT green-leaning, WARM, COOL, DEAD) so the screen isn't a wash of one
  colour and the eye trusts green = "do this".
- **Spacing rhythm — tighten the chrome for a sales workflow.** Square 2–4px radii replace the
  soft 6–10px corners, giving the top bar, tabs and table a denser, tool-like edge that suits
  rapid row scanning rather than a marketing dashboard.
- **Distinctiveness — keep one signature, drop the generic.** The radar ping returns as the HOT
  row tell and the empty-state beacon; that single recurring motif (a Linear/Vercel move — own
  *one* gesture) is what makes the product look authored rather than templated.

---

## emil-design-eng interactions

Five micro-interactions, all CSS / `requestAnimationFrame` (no Framer Motion → bundle stays 106 KB):

- **Score count-up.** New `CountUp` component animates the number from its previous value to the
  new one over 300 ms with an ease-out cubic, on every tier/verification change. Honours
  `prefers-reduced-motion` (snaps instantly). Used in the table score cell and the detail-modal score.
- **Scrape progress shimmer.** While scraping, `.scrape-bar-fill.is-running` runs a Stripe/Linear
  white-gradient sweep (`@keyframes shimmer`, 1.3 s) over the green fill.
- **Lead-row delete fade-in.** The row × is now `opacity:0` and fades in over 150 ms on row hover
  (and on keyboard focus for a11y) instead of being permanently present.
- **Empty-state radar ping.** The empty glyph emits two staggered concentric rings
  (`@keyframes radarRing`) — a continuous, gentle beacon loop.
- **Sliding tab underline.** The subbar tab indicator is a single absolutely-positioned bar whose
  `transform`/`width` are measured from the active tab (`useSlidingUnderline`, layoutId-style) and
  transitioned over 280 ms, so switching tabs slides rather than jumps.

Bonus signature: HOT table rows emit the radar ping from the tier dot (`@keyframes radarPing`).

---

## impeccable polish

Pre-shipping dashboard-quality pass:

- **Loading skeleton (single-lead scrape).** While the scrape runs, the modal shows shimmering
  skeleton cards (avatar + 2 lines + chip) for each still-pending URL — no blank wait.
- **Error state + retry CTA.** Each failed URL renders an error card with the URL, the message,
  and a **Retry** button that re-scrapes just that URL (`retryOne`, shared `buildLead`), moving it
  from errors to results on success.
- **Sortable headers.** Firma / Tier / Skóre / Fáza are clickable; 1st click **DESC**, 2nd **ASC**,
  3rd clears, with a ▼/▲ indicator and brand-coloured active header. (Tier sorts by HOT>WARM>COOL>DEAD.)
- **Filtered empty state.** Distinct states: no leads at all → radar + scrape CTA; a tier filter
  with no matches → "Žiadne leady v tieri HOT" + *Zrušiť filter* / *Scraping*; a search with no
  matches → "Nič sa nenašlo" + *Zrušiť filter*.
- **Keyboard shortcuts panel.** `⌘/Ctrl+K` focuses search, `N` opens a new scrape, `?` toggles the
  panel, `Esc` closes. A ⌘ button in the header opens the panel listing all shortcuts.
- **Double-click a row → open the site.** Single click opens the detail modal; a 200 ms click/dblclick
  discriminator routes a double-click to `window.open(url)` in a new tab.

---

## HARD constraints — kept

- 4 languages (SK/CZ/PL/EN) — every new string is translated in all four locales.
- localStorage keys `wector_leads`, `wector_lang` — untouched.
- API endpoints `/api/leads/scrape`, `/api/leads/raw-extract` — untouched.
- Electric green primary · radar ping signature · square radius — restored as above.
- No Inter font, no blanket `rounded-2xl`, no purple — verified absent.
- Bundle 106 KB < 350 KB.

---

## Verification

Rendered and exercised in the live preview browser (Chromium, `python -m http.server`); the page
mounts with **zero console errors** (only Babel's standard in-browser-transformer notice).

**Empty state** — accessibility snapshot (no leads):

```
banner: "W Wector" · "0 leadov" · [SK][CZ][PL][EN] · ⌘ "Klávesové skratky" · Cenník · Export · Scraping
tabs:   Všetky 0 · HOT 0 · WARM 0 · COOL 0 · DEAD 0      search: "Hľadať firmy, kontakty, segment…"
main:   [radar glyph] "Žiadne leady — pridaj URL firiem pomocou Scraping" + Scraping CTA
footer: Obchodné podmienky · Ochrana osobných údajov · Cookies · Kontakt
```

**Populated CRM** — seeded 6 leads (2 HOT, 2 WARM, 1 COOL, 1 DEAD):

```
rows: 6   row-hot: 2 (radar ping)   stat-values: 6 / 2 / 2 / 1 / 1
sortable headers: Firma↕  Tier↕  Skóre↕  Fáza↕
sort Skóre 1st click → DESC ▼ (88,84,72,64,46,31)   2nd click → ASC ▲ (31,46,64,72,84,88)
```

**Computed tokens (live):** `--bg #FAFAF7` · `--brand hsl(145 100% 42%)` · primary button
`rgb(0,214,89)` · `--r-2 3px / --r-3 4px` · brand wordmark `JetBrains Mono` · row-× `opacity:0`.
Keyboard: `⌘`-button + `?` open the panel, `Esc` closes, `N` opens scrape — all confirmed.

> **Note on image screenshots:** the preview `screenshot` tool times out in this environment
> (it waits for network-idle that never fires while the page holds keep-alive connections to the
> Google Fonts / unpkg CDNs). The DOM accessibility snapshot + live computed-style readouts above
> are the verification of record. To view the populated CRM yourself, open the `wector` preview —
> the 6 demo leads are seeded in its localStorage (clear with `localStorage.removeItem('wector_leads')`).
