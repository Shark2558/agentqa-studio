# AgentQA Studio — design system (MASTER)

*Source of truth for every screen from M0.5 on. Generated with the ui-ux-pro-max method on 3 Nov 2026 and reconciled
with PRD §11; the generator's raw output is kept beside this file as `MASTER.generated.md`. Page-specific overrides go
in `pages/<page>.md` and win over this file.*

## 1. Direction

**Soft-UI neumorphism in professional blue and white, with Data-Dense Dashboard rules wherever data is shown.**
Product type: QA test-automation platform (desktop/laptop monitoring and review; phone for a glance). Audience: a
non-technical owner first, testers and viewers second. Stack: React + TypeScript + Vite (PRD D9).

Point of view (ECC web/design-quality: no "dashboard by numbers"): the interface is organised around **the next
thing a person must do** — the "Your turn" banner and the agent board sit above everything; numbers explain, they do
not lead. Depth comes from the neumorphic surfaces; information density comes from the Data-Dense rules; status is
always glyph + label + colour.

## 2. What the database said, what we kept, what we discarded

| Search | Database match | Decision |
|---|---|---|
| `--design-system` (density 8) | Pattern *Real-Time / Operations Landing*; style **Glassmorphism**; dark-tech palette (`#0F172A` bg, green CTA); type *Plus Jakarta Sans* | **Discarded** the landing-page pattern (this is a product UI, not a marketing page), Glassmorphism (owner chose neumorphism) and the dark-tech palette (owner chose blue and white). **Kept** its live-telemetry rules: label data as live only with an update time and a stale state; pause/update-frequency controls; static snapshot under reduced motion. Plus Jakarta Sans is offered as the alternative font in the mock. |
| `style: neumorphism` | Soft UI, 12–16 px radius, two-layer soft shadows, 150 ms press; **risk: high**, "do not use for data-heavy dashboards / high contrast" | **Kept** for surfaces and controls only (shell, cards, buttons, inputs, toggles, agent cards). **Discarded** its pastel palette and its use on text, tables, charts and status. |
| `style: data dense dashboard` | 12-column grid, 8 px gap, 12 px card padding, 12–14 px type, 36 px rows, sticky headers, 240 px sidebar, 56 px header | **Kept** for Live View, tables, results, KPI rows (tokens `--row-h`, `--sidebar-w`, `--header-h`, `--text-sm`). |
| `color: enterprise saas blue trust` | **SaaS (General)**: primary `#2563EB`, bg `#F8FAFC`, fg `#1E293B`, muted fg `#475569`, border `#E2E8F0`, destructive `#DC2626`, accent orange `#EA580C` | **Kept** the blue/slate system. Shell background lowered one tone (`#EDF2F8`) so soft shadows read; cards `#F8FAFC`, raised tops `#FFFFFF`. **Discarded** the orange accent: amber `#B45309` is used for *warnings and gates* only, never as a decorative CTA. |
| `typography: dashboard data monospace` | *Dashboard Data* (Fira Sans + Fira Code); *Terminal CLI* (JetBrains Mono); *Science/Tech* | **Chose IBM Plex Sans + JetBrains Mono** (PRD §11; Plex is designed for UI text, JetBrains Mono for ids/logs/tokens). Fira is a close second. Fonts are bundled locally in the product (no CDN at runtime; offline mode). |
| `chart: test results pass fail trend` / `real-time dashboard` | Line chart for trends (solid/dashed/dotted per series, direct labels); **bullet chart** for KPI-vs-target; streaming area for live; part-to-whole as stacked bar, not pie | **Kept**: readiness = bullet chart with threshold bands + target marker (mock); pass/fail/blocked = stacked bars; trends = line charts with distinct line styles; no pie charts. Every chart gets a data table fallback and keyboard-reachable values. |
| `icons` (outcome queries) | **Phosphor** (primary) + Heroicons (fallback); decorative icons `aria-hidden`; meaningful icons get a text alternative; icon buttons get an accessible name and state | **Kept** for the product (M0.5 installs `@phosphor-icons/react`, regular weight): one family, sizes 16/20/24 as tokens; status glyphs in `--glyph-*`. The mock's inline sprite is a hand-drawn placeholder in the same style, not Phosphor. |
| `ux` rules | Contrast 4.5:1 (3:1 non-text), compact labels never wrap, one atomic live-status message, loading states that keep layout, focus not obscured, WCAG 2.2 focus appearance | **Kept** (see §5 rules). |
| `--stack react` | Semantic HTML (`button`, `nav`), focus management in dialogs, labels with `htmlFor`, profile before optimising | **Kept** for M0.5+. |

## 3. Tokens

`tokens.css` is the single source. Every colour is declared once with `light-dark(light, dark)`; `color-scheme` on the
root picks the side (OS preference by default, `data-theme` when a person chose), so there is no duplicated dark block
to drift. Layers: primitive scales (blue, slate, green, amber, red, violet) → semantic roles → component recipes; a
few one-off surfaces (`--shell-light`, `--card-dark`…) are named primitives rather than a full scale. Highlights:

- **Surfaces (light):** bg `#EDF2F8` · surface `#F8FAFC` · raised `#FFFFFF` · sunken `#EAF0F7`. **Dark:** bg `#0F172A` ·
  surface `#151D31` · raised `#1A2338` · sunken `#0C1324`.
- **Text:** ink `#1E293B` / `#E2E8F0`, ink-2, muted `#475569` / `#94A3B8` (muted is still ≥ 6.1:1 in both themes).
  **Never dim text with opacity** (the checker cannot see it): a queued/disabled state uses `--color-muted` and a
  dashed boundary.
- **Brand:** primary `#2563EB` (dark `#60A5FA`), hover `#1D4ED8`, tint `#DBEAFE` with primary-ink `#1D4ED8` for text on
  the tint (plain primary on the tint measures 4.24:1 light / 4.07:1 dark, so it is never used that way). The brand mark
  is `--color-primary` with `--color-on-primary` (no gradient: the gradient measured 3.68:1).
- **Status:** ok `#166534`, warn `#92400E`, bad `#C2271D`, info `#1D4ED8`, visual `#6D28D9` for text (the lighter
  `#15803D` / `#B45309` measured 4.37:1 on hovered rows), each with a `-soft` tint and a `-ink` text colour for badges,
  and a glyph (`check-circle`, `x-circle`, `prohibit`, `circle-dashed`, `eye`, `spinner`, `hand-palm`).
  `--color-track` (`#64748B`) draws pending bars and empty tracks at ≥ 3:1.
- **Neumorphic recipes:** `--neu-raised` (cards, buttons), `--neu-raised-sm`, `--neu-pressed` (inputs, active nav,
  selected switch, wells), `--neu-flat` (dense panels, tables, event rows), `--neu-primary` (primary button lift).
  Light source top-left in both themes; only the two shadow colours (`--shadow-hi`, `--shadow-lo`) change per theme.
- **Type scale:** 12 (min) / 13 (tables) / 14 (body) / 16 / 18 / 22 / 28 (KPI numbers); line-height 1.5; tabular
  numbers on every figure.
- **Spacing (density 8):** 4 / 8 / 12 / 16 / 24 / 32. **Radii:** 16 / 14 / 10 / 8 / pill. Controls 40 px high, hit area
  ≥ 44 px, rows 36 px, sidebar 248 px, header 56 px.
- **Motion:** press 150 ms, UI 200 ms, panels 300 ms, pulse 1.2 s, ease `cubic-bezier(.2,.8,.2,1)`; all zero and every
  animation off under `prefers-reduced-motion`. Layout properties never animate; `transform`/`opacity` are the
  compositor-friendly choices, `box-shadow` and `color` transitions are accepted on small controls only.

**Contrast (measured by `check_contrast.py`, 40 pairs × 2 themes, every combination the mock uses): 80/80 pass.**
Lowest: light focus ring on page background 3.27:1 (non-text, min 3), light link on page background 4.59:1 (text,
min 4.5). The checker has its own tests (`backend/tests/test_check_contrast.py`) and runs in `make lint`, so a token
change that breaks a pair fails the build.

## 4. Components (recipes; React components in M0.5 follow these)

| Component | Surface | States |
|---|---|---|
| Shell / sidebar | bg; nav items flat, hover raised-sm, current pressed + primary-ink | focus ring 2 px |
| Card (hero: verdict, KPI, agents) | surface, `--neu-raised`, radius 14 | — |
| Panel (table, stream, dense data) | surface, `--neu-flat` + 1 px line, radius 14 | row hover sunken |
| Sunken well (timeline, gauge, project chip) | bg, `--neu-pressed` | — |
| Button primary | primary bg, on-primary text, `--neu-primary` | hover darker, active pressed + 1 px down, 150 ms |
| Button secondary | surface, `--neu-raised-sm` | hover ink, active pressed |
| Switch / segmented | pressed track, raised-sm thumb with primary-ink | `aria-pressed` |
| Input | sunken, 40 px, label above (never placeholder-only), error text below the field | focus ring; error = bad-ink text + bad line |
| Status pill | `-soft` tint, `-ink` text, glyph 14 px, no wrap | — |
| Severity | mono, uppercase short form (CRIT/HIGH/MED/LOW) in status colour **and** the word | — |
| Agent card | raised-sm; running = pressed + 2 px primary ring + spinning glyph; waiting = 2 px warn ring + hand glyph; done = check; queued = muted text + dashed boundary (never opacity) | click opens the agent's stream |
| Event row (thought / action / result) | flat; kind in mono caps coloured visual / info / ok-or-bad; time + evidence in mono muted | — |
| Table | sticky uppercase header on sunken; 36 px rows; numbers right-aligned tabular; one-line cells | row hover |
| Readiness | the score as the hero number + verdict pill, then a bullet chart: bands bad/warn/ok tints, primary bar, ink target marker (no donut/pie) | `role="img"` with a full text label |
| Live frame | sunken; url bar; acting element outlined in warn colour; action label pill | — |
| Test tiles | 26 px squares, status tint + glyph, a list with one accessible label per tile ("TC-0003 failed"); a read-only summary — opening a test goes through the results table (44 px rows) | — |
| Timeline | sunken well; stages as bars (done primary, pending `--color-track`, **gates amber**) | — |

## 5. Rules every screen follows

1. Text ≥ 4.5:1, non-text ≥ 3:1, in both themes, measured. Never colour alone: glyph + label with every status.
2. Keyboard: every control reachable, visible 2 px focus ring, nothing obscures the focused element, dialogs trap and
   return focus. Hit areas ≥ 44 px even when the control is drawn smaller (40 px buttons and 32 px small buttons
   extend their hit box with a `::before`; nav rows are 44 px tall).
3. Semantic HTML first (`nav`, `main`, `section` with headings, `button`, `table`); icon buttons carry an accessible
   name; decorative icons are `aria-hidden`.
4. One atomic live-status message per region (`role="status"`, `aria-atomic`), never a bare number.
5. Compact labels never wrap (pills, severities, ids); long values get a shrinkable label and a keyboard-reachable
   full text.
6. Loading keeps layout (skeletons with reserved space, `aria-busy`); live data says when it last updated and marks
   itself stale; tickers have pause/update controls; a static final frame under reduced motion.
7. Density: dense scale on monitoring and data screens (Live View, Execution, Results, Defects); the onboarding wizard
   and reports may breathe (24–32 px) but never exceed the token scale.
8. Typography: 14 px app body, 13 px in tables, 12 px minimum; two families only; local fonts with `font-display: swap`.
9. Motion only on compositor-friendly properties; durations from tokens; reduced-motion honoured.
10. Forms: visible labels, helper text, inline errors next to the field plus an error summary on multi-error submits.
11. Charts: legend + tooltip + keyboard values + data-table fallback; line styles distinguish series; bullet for
    KPI-vs-target; stacked bars for part-to-whole; no pie.
12. Responsive: 375 / 768 / 1024 / 1440; no horizontal scroll; sidebar collapses to a top bar under 760 px.

## 6. Pre-delivery checklist (from the repo, run before every screen ships)

- [ ] Only relevant searches run; `quick-reference.md` §1–§3 (CRITICAL + HIGH) re-read.
- [ ] No emoji as icons; one icon family; consistent stroke and sizes.
- [ ] Hover / focus / active / disabled states designed, 150–300 ms, no layout shift.
- [ ] Light **and** dark checked separately; dividers and states visible in both; `check_contrast.py` green.
- [ ] 375 px and a laptop width rendered and looked at; no overflow.
- [ ] Reduced motion and largest text size tried.
- [ ] Would it pass as a real product screenshot? Four of the ten design-quality qualities present (hierarchy by scale,
      rhythm, depth, type pairing, semantic colour, designed states, bento composition, motion that clarifies, data
      viz as part of the system).

## 7. Mock and evidence

`frontend/design-system/mock/index.html` renders Dashboard and Live View from `tokens.css` alone, with theme and font
switches (preview only; it loads fonts from Google Fonts — the product bundles them). `render_mock.py` writes the
reference renders in `docs/design/m0-4-*.png` (desktop 1440 and phone 375, light and dark, plus the two font
candidates) and fails on horizontal overflow at 320 / 375 / 768 / 1024 / 1440 px or an inert font switch.
