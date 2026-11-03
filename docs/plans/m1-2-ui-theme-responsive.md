# Plan — M1.2-UI Professional look, themes, phone layout, Live View reachability

**Milestone:** UI slice before M1.2 (owner, 3 Nov 2026: "this UI slice first, then M1.2 on the new look").
**Marker:** none (no auth, secrets, AI or execution change; CSP unchanged). **Owner approval:** this plan, then the
Phase 0 renders. Planned with the `planner` agent against the code on 3 Nov 2026; the ui-ux-pro-max database was
searched first (results in §"Design sources").

## Goal

Replace the M0.4 soft-UI neumorphism (the owner calls it "glassmorphism") with a flat, professional blue-and-white
system. Add Light / Dark / System themes and 5 accent colours, chosen in the app and remembered. Make every screen
usable from 320 px (no overflowing fields, a menu on phones). Add motion only where it explains testing. Make Live
View reachable from every page, with honest empty and loading states.

## Design sources (ui-ux-pro-max, searched 3 Nov 2026)

- **Kept:** style *Flat Design* (no shadows or gradients, clean lines, 1–2 px strokes, 150–200 ms transitions,
  accessibility risk: low) and *Minimalism & Swiss* (white space, grid, high contrast); palette *SaaS (General)*
  (primary `#2563EB`, bg `#F8FAFC`, text `#1E293B`, muted `#475569`, border `#E2E8F0`, destructive `#DC2626`); UX
  rules: mobile-first breakpoints, tables scroll or become cards, 44 px targets, skeletons rather than spinners for
  waits over 1 s, infinite animation only for loading indicators, reduced-motion respected.
- **Discarded as off-fit:** the generator's *Trust & Authority* landing-page pattern, its navy `#0F172A` primary and
  the EB Garamond / Lato pairing (a product UI, not a law-firm page). IBM Plex Sans + JetBrains Mono stay: the owner
  chose them twice in M0.4.
- **No database entry** exists for theme switchers or accent pickers; that part is general practice and MASTER.md
  labels it so.

## What the code says that changes the direction (recorded so nobody re-learns it)

1. **The Live View link is never shown, on any page.** `Shell.tsx:14` reads `useParams().slug`, but Shell is the
   element of the parent `/*` route (`App.tsx:33-48`), so its params are only `{"*": …}`. Fix: `useMatch("/projects/
   :slug/*")`, excluding `new`. The first RED test proves it.
2. **The no-flash theme script cannot be inline.** `APP_CSP` is `script-src 'self'` (`api/__init__.py:28`). The boot
   script is a static file `frontend/public/theme-boot.js`, loaded synchronously in `<head>` and served from `/app/`.
3. **Overflow arithmetic.** `input, select` and `textarea` are `width:100%` plus 24 px of padding with no `box-sizing`,
   so every field is 24 px wider than its container's content box and crosses the card edge by 8 px (measured on the
   sign-in card: 738.5 px vs 730.5 px). The global field rule also styles checkboxes and radios, patched today in
   `label.check` and `.choice`. Fix: `*, *::before, *::after { box-sizing: border-box }` and a field rule scoped to
   `input:not([type=checkbox],[type=radio],[type=file],[type=hidden])`.
4. **Text overflow that is not a field:** long mono URLs in `Projects.tsx` rows and `Project.tsx` `.sub` have no
   `min-width: 0` / `overflow-wrap: anywhere`.
5. **No navigation under 760 px**, in the app (`styles.css:149`) and in the mock (`mock/index.html:143`): `.side` is
   hidden and nothing replaces it. M0.4's overflow check passed partly because the nav was hidden.
6. **Uniform accent shades fail contrast.** White on teal-600 is 3.75:1 and on green-600 3.30:1 (need 4.5); teal-500
   and green-500 as focus rings are 2.49 and 2.28 (need 3). Each accent maps its own shades (table below).
7. **`check_contrast.py` only reads top-level `:root`** (lines 70-83). Accent blocks use `:root[data-accent="x"]`,
   which is more specific than `:root` and order-independent; the parser learns that selector.
8. **Phosphor icons are filled outlines, not strokes**, so a stroke draw-in cannot work: the tick uses a `clip-path`
   wipe, the cross a scale-in.
9. **No table has 3 or fewer columns** (runs: 6, requirements: 5), so the "card layout on phones" rule goes into
   MASTER for later; every table keeps `.scroll-x` now.
10. **`.choice.disabled { opacity: .7 }`** (`styles.css:141`) breaks MASTER's "never dim text with opacity"; fixed
    with muted text and a dashed border.
11. **Scan line + pulse on one running card would be two endless animations on one element.** The scan line ships as
    a recipe on the mock's browser frame only; M1.3 wires it into the app. Agent cards get the pulse only.
12. **ECC `web/design-quality.md` bans "flat layouts with no layering" and "gray-on-white with one accent".** MASTER
    must name the qualities this flat system shows: hierarchy by scale, semantic colour, designed states, clarifying
    motion, data visualisation as part of the system.

## What is built

### Tokens (`design-system/tokens.css`, 113 → ~190 lines; every semantic name kept)

| | Tokens |
|---|---|
| **Removed** | `--shadow-hi`, `--shadow-lo`, `--shadow-glow`, `--shadow-primary`, `--neu-raised`, `--neu-raised-sm`, `--neu-pressed`, `--neu-flat`, `--neu-primary`, `--shell-light`, `--sunken-light` |
| **Re-valued (light)** | bg `#F8FAFC`, surface `#FFFFFF`, surface-raised `#FFFFFF`, surface-2 `#F1F5F9` (table header, row hover). Inputs: white with a 1 px `--color-line-strong` border (slate-500, ≥ 3:1). Radii 12 / 10 / 8 / 6. Dark keeps the M0.4 values. |
| **Added** | `--elev-overlay` (the one soft shadow: menus, drawer); `--accent`, `--accent-hover`, `--accent-soft`, `--accent-ink`, `--accent-focus` (each `light-dark()`), with `--color-primary*` / `--color-focus` = `var(--accent*)`; 50–900 primitives for indigo, teal, green; `--dur-draw: 200ms`, `--dur-scan: 1600ms`, `--drawer-w: 280px`; `.sr-only` |
| **Kept** | `--color-info` stays blue in every accent (status, not brand); glyph, type, spacing and motion tokens |

### Accent shade map (light | dark; on-primary is white in light, `--night` in dark)

| Accent | solid / hover | soft + ink | focus | dark solid / hover | dark soft + ink | dark focus |
|---|---|---|---|---|---|---|
| **Blue** (default) | 600 `#2563EB` / 700 | 100 + 700 | 500 | 400 / 300 | 900 + 200 | 400 |
| Indigo | 600 `#4F46E5` / 700 `#4338CA` | 100 `#E0E7FF` + 700 | 500 `#6366F1` | 400 `#818CF8` / 300 | 900 `#312E81` + 200 | 400 |
| Teal | **700** `#0F766E` / 800 `#115E59` | 100 `#CCFBF1` + 800 | **600** | 400 `#2DD4BF` / 300 | 900 `#134E4A` + 200 | 400 |
| Green | **700** `#15803D` / 800 `#166534` | 100 `#DCFCE7` + 800 | **700** | 400 `#4ADE80` / 300 | 900 `#14532D` + 200 | 400 |
| Slate | **700** `#334155` / 800 | **200** + 800 | 500 | **300** `#CBD5E1` / 200 | 700 + 100 | 400 |

Bold cells depart from the Blue pattern, which is why the map is per accent. Final numbers come from the checker.

### Theme storage and switching

- `lib/theme.ts` (pure): `MODES = light|dark|system`, `ACCENTS = blue|indigo|teal|green|slate` (labels and swatch
  tokens), `STORAGE_KEY = "agentqa.theme"`. `parsePreference(raw: unknown)` checks against the allow-lists; anything
  else gives `{mode: "system", accent: "blue"}`. `applyPreference(pref, el = document.documentElement)` sets
  `data-theme` and `data-accent` on `<html>` (the accent slots resolve on the same element as `:root`).
  `savePreference` wraps `localStorage` in try/catch. `useTheme()` uses `useSyncExternalStore` + the `storage` event
  so other tabs follow.
- `public/theme-boot.js` (~25 lines, plain ES5): same key and allow-lists, sets both attributes before first paint,
  never throws. `index.html` loads it in `<head>` (Vite prefixes the `/app/` base). A drift test imports it `?raw`.
- `ThemeMenu.tsx`: an "Appearance" button (Phosphor `Palette`, 44 px, `aria-expanded`) opening a non-modal panel with
  two `fieldset`s of native radios: Mode (Light / Dark / System) and Accent (5 named swatches, never colour alone). A
  preview strip shows a primary button, a pill, a link and a focus ring. Applies at once with no colour transition
  (no whole-page repaint). Escape or an outside click closes it and returns focus. Sits in the sidebar footer, the
  phone top bar and (decision 2) the Sign-in page.
- "Saved per person" means **per browser** until team logins (M2.1); then it follows the account.

### Responsive (mobile-first; `min-width` queries at 760 and 1100; `100dvh` replaces `100vh`)

| Width | Shell | Content |
|---|---|---|
| < 760 (tested 320, 375) | 56 px top bar: brand, menu button (`List`, `aria-expanded`, `aria-controls`), ThemeMenu. Nav in a `<dialog>` drawer (`showModal`, so the page is inert; Escape closes; focus returns to the menu button; closes on link click or when widened past 760). One `NavLinks` component shared with the sidebar. | KPI grid 1 column; Live grid stacked; wizard rail becomes a horizontal stepper (numbers, titles `.sr-only`, ≥ 44 px targets); `.review` dl stacks; tables in `.scroll-x`; topbar actions wrap; all targets ≥ 44 px |
| 760–1099 (768, 1024) | Sidebar 248 px | KPI 2 columns; `g-two`, `g-live` and wizard 1 column; role grid 2 columns |
| ≥ 1100 (1440) | Sidebar 248 px | KPI 4 columns; `g-two` 1.4/1; Live 320 px + stream; wizard rail 240 px; role grid 3 columns |

### Motion (durations from tokens; only transform, opacity, clip-path; all off under `prefers-reduced-motion`)

| Name | Trigger | Property | Duration | Reduced motion |
|---|---|---|---|---|
| agent-pulse | `.agent.running` (a loading indicator, so it may repeat) | `::after` ring scale 1→1.06 + opacity .6→0 | `--dur-pulse` 1200 ms, repeats while running | static 2 px ring |
| bar-fill | `ProgressBar` value change (upload, wizard progress) | `transform: scaleX(var(--p))`, origin left | `--dur-panel` 300 ms | jumps to value |
| tick-in | glyph enters done / failed (agent card, done wizard step) | check: `clip-path inset(0 100% 0 0 → 0)`; cross: scale .6→1 + opacity | `--dur-draw` 200 ms, once, only for cards whose state changed after mount | glyph shown |
| scan-line | `.frame.running` (mock only now; the app in M1.3) | `::after` 2 px line translateY 0→100 % | `--dur-scan` 1600 ms, repeats while running | none |
| skeleton | `aria-busy` placeholders | opacity .55↔1 | 1200 ms, repeats while loading | static block |
| drawer | dialog open | translateX(-100 % → 0) | `--dur-ui` 200 ms | instant |

Nothing moves when idle; the existing running-glyph spin stays (a loading indicator).

### Live View reachability

The sidebar and drawer always list **Live View**. Inside a project it goes to `/projects/:slug/live`; elsewhere to a
new route `/live` (`LivePicker.tsx`: "Live View shows one project's run — choose a project", built from a shared
`ProjectList`; an empty list links to New project). `Live.tsx`: skeleton agent cards with `aria-busy` while sessions
load; with no sessions "No run yet — start one from the project page" with a button and the run selector hidden;
with a session but no events "Waiting for the first event…"; an error notice when sessions fail to load. The `.evt`
and `.agent` class names stay (`e2e/acceptance.spec.ts` uses them).

### Files

| File | New / changed | Responsibility | ~Lines |
|---|---|---|---|
| `design-system/tokens.css` | changed | flat tokens, accent blocks, motion tokens | 190 |
| `design-system/MASTER.md` | changed | §1–§4 rewritten; §5 rule 12; new §8 Themes (general practice), §9 Motion; §7 evidence | 170 |
| `design-system/check_contrast.py` | changed | parse `:root[data-accent]` blocks; themes × accents | 215 |
| `design-system/render_mock.py` | changed | accent pick, `m1-2ui-` prefix (m0-4 renders kept), input-in-container and reduced-motion checks; Jakarta switch dropped | 160 |
| `design-system/mock/index.html` | changed | flat recipes, accent + theme switch, phone top bar and drawer, pulse card, scan-line frame | 380 |
| `design-system/check_app.py` | **new** | Playwright check of the real app against a test server (see Tests first) | 200 |
| `frontend/public/theme-boot.js`, `index.html` | new / changed | no-flash boot | 25 / +1 |
| `src/lib/theme.ts` (+ test) | new | preference model and storage | 80 / 90 |
| `src/components/{ThemeMenu,NavDrawer,NavLinks,ProgressBar,Skeleton,ProjectList}.tsx` (+ tests for the first two) | new | as above | 110 / 80 / 50 / 30 / 25 / 50 |
| `src/components/Shell.tsx` (+ `Shell.test.tsx`) | changed | `useMatch`, Live link always, drawer, ThemeMenu | 95 |
| `src/pages/{LivePicker.tsx, Live.test.tsx, LivePicker.test.tsx}` | new | reachability | 45 / 90 / 50 |
| `src/pages/{Live,Projects,Project,SignIn}.tsx`, `wizard/{NewProject,StepRequirements}.tsx`, `App.tsx` | changed | states, ProjectList, ProgressBar, stepper markup, `/live` route | small each |
| `src/styles.css` → `src/styles/{base,shell,components,live,wizard,motion,theme-menu}.css` | split | `styles.css` becomes a 10-line `@import` index, so `main.tsx` is unchanged | ≤ 150 each |
| `src/test-setup.ts` | changed | `matchMedia` and `HTMLDialogElement.showModal/close` stubs if jsdom lacks them | +15 |
| `backend/tests/test_check_contrast.py` | changed | accent tests | 56 → 120 |
| `Makefile` | changed | `ui-check` target (`check_app.py`, needs `web-build`) | +3 |
| `docs/HANDOFF.md` | changed | design decision line updated | — |

No new dependency; `package.json` unchanged; no backend source change.

## Tests first (each RED before its code)

- **Contrast** (`test_check_contrast.py`, +6): `:root[data-accent="teal"]` blocks parsed and an accent inside
  `@media` ignored; an accent override changes only that accent; a pair failing only in dark/teal is reported as
  `dark/teal: …`; a missing accent block fails closed; accent-free pairs counted once per theme; the shipped
  `tokens.css` passes.
- **Contrast counts.** PAIRS grows from 40 to 45. 14 pairs involve the accent (on-primary/primary, on-primary/
  primary-hover, primary/surface, primary/bg, primary-ink/primary-soft, primary-ink/bg, primary-ink/surface-raised,
  focus/surface, focus/bg, primary/bad-soft, plus new primary-ink/surface, primary-ink/surface-2, focus/surface-
  raised, primary/primary-soft at 3:1); 31 do not (30 existing + line-strong/bg). Checks: 31 × 2 themes + 14 × 2
  themes × 5 accents = **202**. MASTER records "202/202".
- **Vitest** (~30 new on top of today's 25): `theme.test.ts` (defaults on null, bad JSON, unknown or `__proto__`
  values; round-trip; attributes on `<html>`; storage throwing survived; boot-script drift via `?raw`);
  `ThemeMenu.test.tsx` (name "Appearance", `aria-expanded`; Dark sets `data-theme=dark` and saves; Teal sets
  `data-accent=teal`; current values checked on open; Escape and outside click close and return focus);
  `Shell.test.tsx` (at `/projects/demo` Live View goes to `/projects/demo/live` — **RED today**; at `/` and
  `/projects/new` it goes to `/live`; the menu button opens the drawer with the nav; Escape, close or a link click
  closes it and focus returns); `Live.test.tsx` (skeleton with `aria-busy`; "No run yet" with link and no selector;
  "Waiting for the first event…" with a stubbed EventSource; error notice); `LivePicker.test.tsx`; `ProgressBar`
  (clamps 0–1, `aria-valuenow`).
- **`check_app.py`** (the `render_mock.py` pattern on the real app): starts `python -m agentqa ui --port 8790
  --projects-dir <tmp>` with generated `AGENTQA_OWNER_EMAIL`, `AGENTQA_OWNER_PASSWORD_HASH` (via
  `agentqa.api.auth.hash_password`) and `AGENTQA_SECRET_KEY` env vars (env beats `backend/.env`, so the owner's
  sign-in is never read); signs in, creates the demo project through the API, then visits Sign in, Projects (empty
  and filled), Project, Requirements, wizard steps 1–3, Live (empty) and `/live` at 320 / 375 / 768 / 1024 / 1440 in
  light and dark. Asserts: (a) `scrollWidth ≤ innerWidth`; (b) every visible `input`, `select`, `textarea` and `.btn`
  sits inside its nearest `.card`, `form` or `section` (±0.5 px) — **RED today by 8 px**; (c) under 760 the menu
  button is visible, the sidebar hidden, the drawer opens with Live View, Escape closes it and focus returns; (d) nav
  links, menu and Appearance buttons ≥ 44 × 44; (e) computed font is IBM Plex Sans; (f) `data-accent=teal` changes
  `.btn.primary`'s background. Exits 1 on any problem; writes `docs/design/m1-2ui-app-*.png`.
- **`render_mock.py`**: the same overflow and input checks on the mock, plus a reduced-motion emulation asserting the
  running card's `::after` has `animation-name: none`.

## Build order

- **Phase 0 — mock and owner approval (gate, no app change).** Contrast tests RED → `check_contrast.py` → tokens and
  accent map → checker GREEN 202/202. Rewrite the mock flat with accent + theme switch, phone drawer, pulse card and
  scan-line frame. `render_mock.py` writes dash and live × light/dark × Blue and Teal × 1440 and 375. Show the owner
  six renders (light-blue desktop dash, dark-blue desktop live, light-teal desktop dash, phone dash, phone drawer open,
  phone dark live) and the live mock in the browser pane; one question: "Approved?"; iterate once if needed. Since
  `tokens.css` is shared by mock and app, Phase 0 is committed together with Phase 1.
- **Phase 1 — tokens in the app, shell, responsive, overflow (commit 1).** `check_app.py` and `Shell.test.tsx` RED;
  then box-sizing, the scoped field rule, the CSS split, flat recipes, NavLinks / NavDrawer, `useMatch`, `/live` with
  LivePicker, stepper, `dvh`, URL wrapping; then `check_app.py` GREEN, `make lint`, `make web-test`, `tsc -b`, oxlint.
- **Phase 2 — theme menu (commit 2).** `theme.test.ts` and `ThemeMenu.test.tsx` RED; then `theme.ts`, boot script,
  ThemeMenu in shell, top bar and Sign in; `check_app.py` (f).
- **Phase 3 — motion and Live states (commit 3).** `Live.test.tsx` and `ProgressBar` tests RED; then `motion.css`,
  Skeleton, ProgressBar, tick-in, Live empty / loading states. Verify in the browser pane with a real demo run on a
  test-port server (pulse, ticks, empty state before the run).
- **Phase 4 — fresh-context review, verify, commit.** `code-reviewer`, `typescript-reviewer`, `react-reviewer`, plus
  an a11y pass (keyboard through drawer and ThemeMenu, 200 % zoom, reduced motion, both themes × 5 accents spot-
  checked). Fix HIGH and MEDIUM test-first. `tools/check_demo.py` 19/19 unchanged (no engine touch). Update MASTER §7,
  HANDOFF and memory; fill the three sections below.

## Out of scope (named so nobody expects them)

Live View v2 (frames, timeline, stage bars with real data, the scan line in the app: M1.3) · per-account theme
storage (M2.1) · any backend change · the old v0.8 dashboard at `/` (its own CSS in `web/app.py`, retired by M1.4) ·
a phone card layout for the 5-column requirements table (M1.4 rebuilds that page) · new fonts or icon sets.

## Risks

- **Flat can look generic** (an ECC banned pattern). Mitigation: hierarchy by scale, the dark-navy brand mark,
  semantic status colour, designed hover / focus / active states, motion only where testing happens; checked in review
  against the ten design qualities.
- **Green accent next to green "pass".** A green primary button can read like a pass. Status always carries glyph +
  label; the owner sees a Green render before keeping it.
- **Slate accent** brings links close to muted text: Slate uses 700 and links stay underlined in every accent.
- **jsdom lacks `showModal`**: stub in `test-setup.ts`; real behaviour is covered by `check_app.py`.
- **Rate limit** of 240 API requests per IP per minute during `check_app.py`: client-side navigation, one page per
  width, a short pause between widths.
- **Vite base prefix on a `public/` script**: a build assertion checks `dist/index.html` references `/app/theme-boot.js`.
- **Every animation replaying on a revisited page**: tick-in only on cards whose state changed after mount.

## Decisions for the owner

1. Accent names as shown: **Blue (default), Indigo, Teal, Green, Slate**. Blue and Indigo look alike on small
   swatches; keep both?
2. **Appearance menu on the Sign-in page too**: recommended yes (a dark-mode user sees Sign in first).
3. **Old dashboard at `/`**: recommended **not touched** (M1.4 retires it).
4. "Saved per person" means **per browser** until team logins (M2.1); then it follows the account.
5. Renders shown in Phase 0: Blue + Teal (and Green if decision 1 keeps it).

## Verification

_(filled in during the build)_

## Review (fresh context)

_(filled in during the build)_

## Record of changes

_(filled in during the build)_
