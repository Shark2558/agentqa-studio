# AgentQA Studio — design system (MASTER)

*Source of truth for every screen. First generated with the ui-ux-pro-max method on 3 Nov 2026 (M0.4, soft-UI
neumorphism) and **replaced the same day by the flat system below (M1.2-UI)** after the owner rejected the soft look
in the real app. The generator's raw outputs stay beside this file as `MASTER.generated.md`. Page-specific overrides
go in `pages/<page>.md` and win over this file.*

## 1. Direction

**Flat, professional blue and white, with Data-Dense Dashboard rules wherever data is shown, five accent colours the
person can choose, light and dark.** Product type: QA test-automation platform (desktop/laptop monitoring and review;
phone for a glance and for starting or checking a run). Audience: a non-technical owner first, testers and viewers
second. Stack: React + TypeScript + Vite (PRD D9).

Point of view (ECC web/design-quality, which bans "flat layouts with no layering" and "gray-on-white with one
accent"): this flat system earns its place through **hierarchy by scale** (a 44 px verdict number over 12 px labels),
**semantic colour** (status colour always paired with a glyph and a word; the accent is brand, status is never
the accent), **designed states** (hover, focus ring, active press, selected tint with a 3 px bar, dashed "queued",
disabled as dashed outline), **motion that explains testing** (a running agent pulses, a finished one draws its
tick, a frame shows a scan line) and **data visualisation as part of the system** (bullet chart, stacked bars,
timeline bars in the same tokens). Depth comes from one elevated layer (menus, drawer) and the white-on-near-white
contrast of cards on the page, never from soft shadows.

## 2. What the database said, what we kept, what we discarded (3 Nov 2026 searches)

| Search | Database match | Decision |
|---|---|---|
| `--design-system` ("QA test automation platform … clean flat professional blue white") | Pattern *Trust & Authority* (a landing page); style *Accessible & Ethical*; palette "professional navy + blue CTA" (`#0F172A` primary); type EB Garamond / Lato | **Discarded** the landing-page pattern, the navy primary and the serif pairing (a product UI, not a law-firm page). **Kept** the accessibility rules: 3–4 px focus rings, 44 px targets, reduced motion, 375/768/1024/1440. |
| `style: flat design clean enterprise saas` | **Flat Design**: no shadows or gradients, 1–2 px strokes, clean lines, 150–200 ms transitions, risk: low; best for SaaS and dashboards | **Kept** as the base style. |
| `style: minimalism professional dashboard` | **Minimalism & Swiss**: white space, grid, high contrast, "sharp shadows if any" | **Kept** for layout rhythm and the single overlay shadow. |
| `color: enterprise saas blue white trust` | **SaaS (General)**: primary `#2563EB`, bg `#F8FAFC`, fg `#1E293B`, muted `#475569`, border `#E2E8F0`, destructive `#DC2626`, accent orange | **Kept** the blue/slate system as the default accent; orange discarded (amber is for warnings and gates only). |
| `ux: responsive dashboard mobile sidebar collapse` | Mobile first; tables scroll or become cards; touch-sized targets; viewport meta | **Kept**: the shell is mobile-first (top bar + drawer under 760 px); tables scroll inside their panel. |
| `ux: loading progress animation status` | Step indicators; skeletons over blank screens; infinite animation only for loading indicators | **Kept**: skeleton cards, progress bars, the pulse only on a running (loading) card. |
| `ux: theme switcher dark mode user preference` | **No entry** (results were unrelated) | The Appearance menu (§8) is **general practice, not a database match**, and is labelled so. |
| `typography: enterprise saas dashboard` | Plus Jakarta Sans; Fira Sans + Fira Code | **IBM Plex Sans + JetBrains Mono kept** (the owner chose them twice in M0.4; bundled locally, no CDN). |
| M0.4 searches still in force | Data-Dense Dashboard rules; Phosphor icons; chart guidance (bullet for KPI-vs-target, stacked bars, lines; no pie) | **Kept** unchanged (see `docs/plans/m0-4-design-system.md`). |

## 3. Tokens

`tokens.css` is the single source. Every colour is declared once with `light-dark(light, dark)`; `color-scheme` on
the root picks the side (OS preference by default, `data-theme` when a person chose). The five **accent slots**
(`--accent`, `--accent-hover`, `--accent-soft`, `--accent-ink`, `--accent-focus`) are set for Blue in `:root` and
overridden by `:root[data-accent="indigo|teal|green|slate"]`; `--color-primary*` and `--color-focus` read the slots,
so no component knows which accent is on. Layers: primitive scales (blue, indigo, teal, green, slate, amber, red,
violet) → semantic roles → component recipes.

- **Surfaces (light):** page `#F8FAFC` · card `#FFFFFF` · overlay `#FFFFFF` · sunken `#F1F5F9` (table header, row hover,
  wells, skeletons). **Dark:** `#0F172A` · `#151D31` · `#1A2338` · `#0C1324`. Lines `#E2E8F0` / `#2A3650`; control
  boundaries and pending tracks `#64748B` (≥ 3:1 in both themes).
- **Text:** ink `#1E293B` / `#E2E8F0`, ink-2, muted `#475569` / `#94A3B8`. **Never dim text with opacity**: a queued or
  disabled state uses `--color-muted` and a dashed boundary.
- **Accents (light solid / hover · tint + ink · focus; dark in brackets):** Blue 600/700 · 100+700 · 500 (400/300 ·
  900+200 · 400) · Indigo 600/700 · 100+700 · 500 (400/300 · 900+200 · 400) · Teal **700**/800 · 100+800 · **600**
  (400/300 · 900+200 · 400) · Green **700**/800 · 100+800 · **700** (400/300 · 900+200 · 400) · Slate **700**/800 ·
  **200**+800 · 500 (**300**/200 · 700+100 · 400). Bold shades depart from the Blue pattern because the lighter ones
  measured below 4.5:1 for white text or below 3:1 as a focus ring. On-primary text is white in light and `#0B1120`
  in dark for every accent.
- **Status:** ok `#166534`, warn `#92400E`, bad `#C2271D`, info `#1D4ED8` (info stays blue in every accent), visual
  `#6D28D9`, each with a `-soft` tint and `-ink` text for badges, and a glyph (`check-circle`, `x-circle`, `prohibit`,
  `circle-dashed`, `eye`, `spinner`, `hand-palm`).
- **Elevation:** none on cards (1 px line); `--elev-overlay` on the one floating layer (menus, drawer).
- **Type scale:** 12 (min) / 13 (tables) / 14 (body) / 16 / 18 / 22 / 28 (KPI numbers), 44 for the verdict; line-height
  1.5; tabular numbers on every figure.
- **Spacing (density 8):** 4 / 8 / 12 / 16 / 24 / 32. **Radii:** 12 / 10 / 8 / 6 / pill. Controls 40 px, hit area ≥ 44 px,
  rows 36 px, sidebar 248 px, header 56 px, drawer 280 px.
- **Motion:** press 150 ms, UI 200 ms, draw 200 ms, panels 300 ms, pulse 1.2 s, scan 1.6 s, ease `cubic-bezier(.2,.8,.2,1)`;
  every duration zero and every animation off under `prefers-reduced-motion`.
- **Base rules in tokens.css:** `box-sizing: border-box` everywhere (so a `width: 100%` field never crosses its card),
  the focus ring, `.sr-only`.

**Contrast (measured by `check_contrast.py`, 45 pairs: 31 theme-only × 2 themes + 14 accent pairs × 2 themes × 5
accents = 202 checks): 202/202 pass.** The checker reads the accent blocks, fails closed when an accent block is
missing, and runs in `make lint`; its own tests are `backend/tests/test_check_contrast.py`.

## 4. Components (recipes; the React components follow these, `frontend/src/styles/*.css`)

| Component | Surface | States |
|---|---|---|
| Shell / sidebar (≥ 760 px) | card surface, 1 px right line, sticky, own scroll | nav item: hover sunken; current = accent tint + accent ink + 3 px accent bar |
| Top bar + drawer (< 760 px) | 56 px bar; the drawer is a modal panel on the overlay layer with a backdrop | menu button `aria-expanded`; Escape / backdrop / link closes; focus returns to the button |
| Card | white, 1 px line, radius 10 | — (the verdict card carries a 4 px accent top border) |
| Button primary | solid accent, on-primary text | hover darker, active 1 px down, 150 ms; disabled dashed |
| Button secondary | white, 1 px strong line | hover sunken; active 1 px down |
| Input / select / textarea | white, 1 px strong line, 40 px, label above (never placeholder-only) | focus ring; read-only sunken + muted |
| Status pill | `-soft` tint, `-ink` text, glyph 14 px, no wrap | — |
| Agent card | 1 px line; running = accent border + pulsing ring; waiting = amber border; failed = red border; done = green tick; queued = dashed + muted | tick / cross draw in once when the state changes after first paint |
| Event row | white, 1 px line; kind in mono caps | — |
| Table | sticky uppercase header on sunken, 36 px rows, one-line cells, scrolls inside `.scroll-x` | row hover sunken |
| Progress bar | 8 px sunken track, accent fill by `transform: scaleX` | 300 ms fill |
| Skeleton | sunken blocks that pulse only inside an `aria-busy` region | — |
| Appearance menu | 44 px button; panel on the overlay layer: theme as three segments, accent as five 44 px swatches, a preview strip | selected = accent tint + accent ring; Escape / outside click closes |
| Stepper (wizard) | numbers in a row under 1100 px (current step shows its title; others `.sr-only`), a rail beside the form above | done = green tick drawn in; current = accent tint |

## 5. Rules every screen follows

1. Text ≥ 4.5:1, non-text ≥ 3:1, in both themes and every accent, measured. Never colour alone: glyph + label with
   every status.
2. Keyboard: every control reachable, visible 2 px focus ring, nothing obscures the focused element, the drawer and
   menus close on Escape and return focus. Hit areas ≥ 44 px even when the control is drawn smaller.
3. Semantic HTML first (`nav`, `main`, `section` with headings, `button`, `table`); icon buttons carry an accessible
   name; decorative icons are `aria-hidden`.
4. One atomic live-status message per region, never a bare number.
5. Compact labels never wrap (pills, severities, ids); long values (URLs) wrap anywhere rather than overflow.
6. Loading keeps layout (skeletons with reserved space, `aria-busy`); every list has an honest empty state that says
   what to do next; live data says when it last updated.
7. Density: dense scale on monitoring and data screens; the wizard may breathe but never exceeds the token scale.
8. Typography: 14 px app body, 13 px in tables, 12 px minimum; two families only; local fonts.
9. Motion only on transform, opacity and clip-path; durations from tokens; nothing moves when idle; reduced motion
   honoured (the global rule in tokens.css).
10. Forms: visible labels, helper text, inline errors next to the field.
11. Charts: legend + keyboard values + data-table fallback; bullet for KPI-vs-target; stacked bars for part-to-whole; no pie.
12. Responsive, mobile first: 320 / 375 / 768 / 1024 / 1440 with no horizontal scroll; under 760 px the sidebar
    becomes a top bar with a drawer; every field and button stays inside its card (measured by `check_app.py`).

## 6. Pre-delivery checklist (run before every screen ships)

- [ ] `make lint` (232/232 contrast) and `make ui-check` (the built app at six widths, both themes) are green; a
      screen with a stream also passes `make live-check` (live, reload, replay and the SSE fallback end at one picture).
- [ ] Columns are sized by the room left beside the 248 px sidebar, not by the window: the sidebar and gutters take
      311 px from 760 px up (M1.3 Phase C: the Live View's middle column was 186 px in a 1149 px window).
      `check_app.py` holds the Live View's middle column at 360 px or more whenever it shares its row.
- [ ] A replay is checked partway through, not only at its end: what the screen says must be true of the moment shown.
- [ ] No emoji as icons; one icon family (Phosphor regular); consistent sizes 16/20/24.
- [ ] Hover / focus / active / disabled states designed, 150–300 ms, no layout shift.
- [ ] Light **and** dark looked at, with at least Blue and one other accent.
- [ ] 375 px and a laptop width rendered and looked at; the drawer opened and closed by keyboard.
- [ ] Reduced motion tried; nothing animates when idle.
- [ ] At least four of the ten design-quality qualities present (§1 names ours).

## 7. Evidence

- M0.4 (superseded): `docs/design/m0-4-*.png`, 80/80 pairs, kept as the record of the look this replaced.
- M1.2-UI mock: `docs/design/m1-2ui-{dash,live}-{light,dark}-{blue,teal}-{desktop,phone}.png`, `m1-2ui-drawer-phone.png`
  from `render_mock.py` (no overflow at 320–1440, fields inside cards, drawer, theme and accent switches, reduced
  motion asserted).
- M1.2-UI app: `docs/design/m1-2ui-app-<page>-<theme>-<width>.png` from `check_app.py` against a throwaway server:
  seven pages, five widths light, two widths dark, all measurements green.
- M1.3 Live View: `check_app.py` measures a `live-run` page (the recorded fixture as a finished run) at six widths in
  both themes, `check_live.py` streams the fixture live over WebSocket and over SSE and checks reload and replay end
  at the same picture. Owner acceptance on 4 Nov 2026 (plan `docs/plans/m1-3-live-view-v2.md`, Phase C): a No-AI run
  watched live and replayed, a Cloud run with each card's model and cost, and a Viewer look; three fixes came from it
  (replay states, the player's end state, the column breakpoints).

## 8. Themes and accents (general practice: no database entry)

- The choice lives on `<html>`: `data-theme="light|dark"` (absent = follow the OS) and `data-accent="<name>"`.
- Saved per browser under `localStorage["agentqa.theme"]` as `{mode, accent}`; `public/theme-boot.js` applies it
  before the first paint (a separate file: the CSP allows no inline script). Team logins (M2.1) move it to the
  account.
- The Appearance menu sits in the sidebar foot, the phone top bar and the sign-in page; the five accents are named
  (Blue, Indigo, Teal, Green, Slate) and chosen by name, never by colour alone.
- Info stays blue in every accent; Green is an accent, pass is a status: the glyph and the word tell them apart.

## 9. Motion that explains testing

| Name | Trigger | Property | Duration | Reduced motion |
|---|---|---|---|---|
| agent-pulse | a running agent card (a loading indicator, so it may repeat) | `::after` ring scale + opacity | 1.2 s, repeats | static ring |
| tick-in / cross-in | a card whose state became done / failed after it first appeared | clip-path wipe / scale-in | 200 ms, once | glyph shown |
| bar-fill | a progress bar's value | `transform: scaleX` | 300 ms | jumps |
| skeleton | placeholders inside an `aria-busy` region | opacity | 1.2 s, repeats while loading | static |
| drawer | the phone menu opening | translateX | 200 ms | instant |
| scan-line | a running browser frame (Live View v2, M1.3; in `motion.css`, only while that agent is running at the moment shown, live or in replay) | `::after` translateY | 1.6 s, repeats | none |
