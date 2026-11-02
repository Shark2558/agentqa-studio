# Plan — M0.4 Design system

**Milestone:** M0.4 (PRD §9, Phase 0; PRD §11). **Marker:** none. **Owner approval:** owner approved running the
ui-ux-pro-max generator (3 Nov 2026) and must approve a static mock of Dashboard + Live View before screens are built.

## Goal

A design system the new React UI (M0.5 onwards) is built from: tokens for light and dark, component rules, and a
rendered static mock of the two most important screens, all produced with the ui-ux-pro-max method and meeting WCAG
2.2 AA by measurement, not by eye.

## Acceptance (from the PRD)

All text ≥ 4.5:1 measured; owner approves a static mock of Dashboard + Live View.

## Method (ui-ux-pro-max skill, in order)

1. Analyse: product = QA test-automation platform; audience = non-technical owner + testers + viewers; context =
   desktop/laptop monitoring and review, occasional phone glance; style keywords = soft UI neumorphism, professional
   blue and white, data-dense monitoring; stack = React + TypeScript + Vite (PRD D9; nothing in the repo yet).
2. Generate: `search.py "<product keywords>" --design-system -p "AgentQA Studio" --density 8 --persist --output-dir
   frontend` → `frontend/design-system/<slug>/MASTER.md`.
3. Verify fit: keep what suits a data-dense product UI; discard landing-page/marketing patterns and the neumorphism
   defaults the database itself marks as accessibility risks (pastel palette, low-contrast text) — say so.
4. Targeted searches: style (neumorphism, data-dense dashboard), ux (dashboard monitoring, dark mode), chart (test
   results, real-time), color (enterprise SaaS blue), typography (dashboard + monospace), product, icons, stack react.
5. Apply in priority order: Accessibility → Interaction → Performance → Style → Layout → Typography/colour → Animation
   → Forms → Navigation → Charts.
6. Pre-delivery checklist from `references/pro-rules.md`; contrast computed numerically for every text/background pair
   in both themes; render the mock and look at it; test at 375 px and on a laptop width.

## Deliverables

- `frontend/design-system/MASTER.md` — generated file reconciled with PRD §11 (what was kept, what was discarded, why).
- `frontend/design-system/tokens.css` — CSS custom properties for light (`:root`) and dark (`[data-theme="dark"]` and
  `prefers-color-scheme`), neumorphic shadow recipes, type scale, spacing (8–32 px dense scale), radii, motion tokens
  with reduced-motion handling, status colours with icon glyph names.
- `frontend/design-system/check_contrast.py` — **written first** (tests-first for a design system): parses
  `tokens.css`, computes WCAG ratios for every declared text/surface pair in both themes, exits 1 below 4.5:1 (3:1 for
  large text and UI boundaries). Wired into `make lint`.
- `frontend/design-system/mock/index.html` — static Dashboard + Live View mock using only `tokens.css`, rendered in the
  browser pane for the owner's approval (light and dark screenshots kept under `docs/design/`).

## Out of scope

React components, routing, real data, the production build (M0.5+). Logo redesign (keep the "AQ" mark, restyled).

## Risks

- Neumorphism vs. readability: surfaces and controls only; text, tables, charts and status follow Data-Dense rules.
- Owner taste is the acceptance criterion: present light + dark, ask one clear question, iterate once if needed.

## Verification (3 Nov 2026)

- Generator run (owner-approved): `search.py "<QA platform…>" --design-system -p "AgentQA Studio" --density 8` plus
  ten targeted searches (style ×2, ux ×5, chart ×2, color, typography, product, icons ×4, stack react). `--persist`
  to the Drive folder failed (`os.link` → WinError 1 on Google Drive's filesystem), so it was persisted to `%TEMP%`
  and copied in as `MASTER.generated.md`; the reconciled `MASTER.md` is the file the UI is built from.
- Fit verdict: generator proposed a landing-page pattern, Glassmorphism and a dark-tech palette → discarded with
  reasons (MASTER.md §2); targeted searches supplied the SaaS blue palette, Data-Dense rules, Phosphor icons and chart
  guidance → kept. Neumorphism applied to surfaces/controls only (the database rates it accessibility risk: high).
- `check_contrast.py` written first (RED: no tokens; then a parser bug hid the `:root` block behind the file's
  header comment — fixed by stripping comments and reading the selector line). **52/52 pairs pass** in light and dark;
  lowest 3.27:1 (focus ring, non-text) and 4.59:1 (link on page background, text). Wired into `make lint`.
- Mock rendered with Playwright at 375 / 768 / 1024 / 1440, both screens, both themes; three overflow/wrap defects
  found by measurement and fixed (dense tables now scroll inside their panel; top bar and banner wrap under 760 px;
  the two-column dashboard grid collapses under 1100 px); final content width equals the viewport at every size.
  Reference renders in `docs/design/m0-4-*.png`.
- **Owner approval: "Approved"** on the five renders and the live mock; font decision: **IBM Plex Sans** (Plus Jakarta
  Sans was offered as the generator's alternative). Acceptance met.

## Review (fresh context, code-reviewer with the ECC web rules)

Verdict **Warning**: 0 CRITICAL, 6 HIGH, 10 MEDIUM, 7 LOW — a measured review (Playwright geometry, computed colours,
independent ratio implementation). All HIGH and MEDIUM items fixed; the ones that changed what the owner saw:
- HIGH-1 **the font switch was inert**, so the owner's first font choice compared identical renders. Fixed
  (`font-family` now set on `body`); `render_mock.py` fails if the switch stops changing the computed font. The owner
  was told, shown real renders of both fonts, and chose **IBM Plex Sans** again; he re-approved the corrected dashboard.
- HIGH-2 table header no longer aligned with its columns (a `display:block` hack) → `.scroll-x` wrapper instead.
- HIGH-3 queued agent cards dimmed text with opacity (3.67:1) → muted colour + dashed boundary; rule added to MASTER.
- HIGH-4 brand mark text on a gradient 3.68:1 → solid `--color-primary`. HIGH-5 hit areas: buttons/switches extend
  to 44 px with `::before`; tiles are a read-only list. HIGH-6 tiles had no text alternative → `ul`/`li` with labels.
- MEDIUM-7/8/9 checker: `@media` leak closed (brace-depth scan), 14 missed pairs added (now 40 × 2; two real failures
  surfaced — ok/warn text on hovered rows at 4.37:1 — fixed by darkening the light tones), dark duplication removed
  by declaring every colour once with `light-dark()`. MEDIUM-10/11/12/13/14: 12 px floor, donut dropped (bullet is the
  chart), brand name colour/underline, inline styles → classes, focus rule. MEDIUM-15: `tests/test_check_contrast.py`
  (8 tests, RED → GREEN) and `render_mock.py` (overflow + font-switch assertions at 320/375/768/1024/1440).
  MEDIUM-16 and LOW-17/18/19/23: MASTER wording corrected (Phosphor is for M0.5; the sprite is a placeholder; exact
  ratios; motion claim; layer claim; eight renders, 320 px recorded).

## Record of changes

- New: `frontend/design-system/{MASTER.md, MASTER.generated.md, tokens.css, check_contrast.py, render_mock.py,
  mock/index.html}`, `backend/tests/test_check_contrast.py`, `docs/design/m0-4-*.png` (10 renders incl. the two font
  candidates); `make lint` runs the contrast check. No engine changes.
- Follow-ups for M0.5: bundle IBM Plex Sans + JetBrains Mono locally (the mock loads them from Google Fonts);
  turn the mock's recipes into React components; the `pages/` override folder is created on first use.
