# Plan — oxlint's React rules: proven off, now on

**Why:** the fresh-context review of M1.4 Phase C noticed that `frontend/.oxlintrc.json` listed only the `jsx-a11y`
plugin. In oxlint a `plugins` list replaces the default set, so the React hook rules (`rules-of-hooks`,
`exhaustive-deps`) might never have run. Every "oxlint clean" in the earlier plans would then have said nothing about
hooks. Done 5 Nov 2026 on `main` (118080d), in its own branch.

## What was found (proof first, in a scratch copy outside the repo)

A copy of `frontend/` in the session scratchpad got a deliberate `ZzHookProbe.tsx`: a `useState` inside an `if`
(rules-of-hooks) and a `useEffect` that reads `id` with `[]` as its dependencies (exhaustive-deps). Linted with that
copy's own `local-node.sh run lint`:

| Config | Probe result | Real code |
|---|---|---|
| `plugins: ["jsx-a11y"]` (before) | **nothing**, exit 0 | nothing |
| `plugins: ["react", "jsx-a11y"]` | exhaustive-deps caught; **the conditional hook was not** | 2 warnings |
| + `"react/rules-of-hooks": "error"` | both caught, exit 1 | 2 warnings |

`oxlint --print-config` on the old config listed only ESLint's core correctness rules and `jsx_a11y/*`: no `react/*` at
all. Two facts that were not obvious:
1. Naming a plugin drops oxlint's defaults (`react`, `typescript`, `unicorn`, `oxc`), so the React rules were off.
2. Even with the `react` plugin on, oxlint 1.90 leaves `react/rules-of-hooks` outside its default (correctness)
   category. It has to be named, or a conditional hook still passes.

## The change

`frontend/.oxlintrc.json`: `plugins: ["react", "jsx-a11y"]`, `react/rules-of-hooks: "error"` (a broken hook order is
always a bug; it also makes `run lint` exit non-zero), `react/exhaustive-deps: "warn"` (named so a category change cannot
switch it off). This matches the ECC React rule (`.claude/rules/ecc/react/hooks.md`). Nothing was weakened or turned
off. The `react` plugin also brings React's correctness rules (`set-state-in-effect`, `purity`, `refs`, `immutability`
and others); they stay on.

## What the rules then found, and the fixes (each with a test)

1. **`Shell.tsx` — `react(set-state-in-effect)`.** `useEffect(() => setOpen(false), [pathname])` closed the phone
   drawer one frame after the new page had already appeared under it (Back button, a redirect; a drawer link closes it
   itself). Now `useDrawer` remembers the path it last rendered and closes the drawer while rendering when the path
   changes, React's documented "adjust state when a value changes" pattern. New test in `Shell.test.tsx`: going Back
   with the drawer open closes it, and the new page's first frame is not under the drawer. It failed before the fix
   (`[[true]]`) and passes after. Until now nothing tested the close-on-navigation path, because the existing test
   closes the drawer through a link's own `onClose`.
2. **`ErrorBoundary.tsx` — `react(no-did-update-set-state)`.** The reset on a new `resetKey` ran in
   `componentDidUpdate`, so every reset rendered twice (fallback, then the part). Now `getDerivedStateFromProps`
   compares the key with the one kept in state (`Object.is`) and resets in the same render. What the user sees does not
   change, and the existing reset test pins it. New guard test: a part still broken under the new key shows the message
   again and stays down until the key moves on. It passed on the old code and passes on the new.

No `rules-of-hooks` or `exhaustive-deps` violations exist in today's code.

## Checks

All run through `bash frontend/local-node.sh` on this machine (5 Nov 2026):

| Check | Result |
|---|---|
| `run lint` (oxlint 1.90, now with `react`) | clean: 0 warnings, 0 errors, exit 0 |
| `run typecheck` (`tsc -b`) | clean |
| `test` (full Vitest) | **385 passed in 46 files** (383 before + the 2 new tests) |
| Fresh-context review (`react-reviewer`) | approve: no CRITICAL, HIGH or MEDIUM. Its LOW on the Shell test is taken (assert "never under the drawer" instead of an exact call list, so a StrictMode test setup cannot break it). |

## Combined into main (5 Nov 2026, on the owner's word)

The owner asked for one up-to-date version to test with a real project and on GitHub, and chose to combine the three
finished branches first:
- this lint commit was rebased onto M1.4 Phase C (`888fbc9`, a fast-forward from `main`), giving `1cfeaed`;
- the M1.3 C4/C5 follow-up (`482c887`) was merged on top (`0a46b40`).

What the combine needed:
1. **`Shell.test.tsx` (conflict).** Phase C had replaced the file with a single help-box test, which dropped the six
   navigation and phone-drawer tests, apparently by accident. The resolution keeps all of them, the new Back test and
   Phase C's test. Phase C's file-wide mock (the help box always throws) is now a `vi.hoisted` flag, so only its own
   test breaks the box.
2. **`HANDOFF.md` (conflict).** Both sides' parked items are kept; three that are now done are dropped (credit is
   billing, the switch line, `list_requirements` without a limit).
3. **The React rules on the combined code (`fdfb92d`):**
   - `assist/dockHooks.ts` `useNews` set state inside its effect (Phase C). The words are now worked out while
     rendering; the effect only records them as said and notifies.
   - `live/AgentFocus.tsx` lost a memo to a later `displayState(card, …)` call (C4/C5). The pure call now runs before
     the memo.
4. **Review finding, HIGH (`3de4c8f`).** The fresh-context review of the combine found that the first `useNews` fix
   compared the list itself, and `NeedsYouDock` hands a new empty list on every render while nothing has loaded. With
   the role known, it then set state forever: "Too many re-renders", shown as "The help box could not be shown" on
   every first load and project switch. The full suite had passed. Fixed test-first: the change is now told by the
   project and the question ids. A new dock test failed before the fix ("Too many re-renders") and passes now, and
   `dockHooks.test.ts` pins the empty list and the same question number in another project.

Checks on the combined branch:

| Check | Result |
|---|---|
| `run lint` | 0 warnings |
| `run typecheck` | clean |
| Vitest | **512 passed in 55 files** (after the HIGH fix; 509 in 54 before its three new tests) |
| `pytest` | **877 passed, 1 failed** in the full run (`test_api_live_ws.py::test_resuming_from_a_cursor_sends_only_the_end`, the known load-sensitive test); that file alone, 3 × **24/24** |
| `pyflakes` | clean |
| contrast | 244/244 |
| demo regression (No-AI, fresh copy, `--auto-approve`) | **19/19 seeded bugs found, 0 unexpected** |

## Follow-ups (not done here: outside the task)

- **The other dropped defaults.** `typescript`, `unicorn` and `oxc` are off for the same reason. A scratch run with
  all four plus `jsx-a11y` found nothing beyond the two React warnings fixed above, so restoring them is a one-line
  change today.
- **NavDrawer re-runs its open effect (found by the review; older than this change).** `Shell.tsx` passes an inline
  `onClose`, and `NavDrawer.tsx` lists `onClose` as its effect dependency. So every Shell re-render while the drawer
  is open (for example when the `me` query resolves) focuses the panel again and re-subscribes the Escape listener.
  A `useCallback` in `Shell` fixes it.
- **oxlint is not in CI.** `.github/workflows/agentqa-selftest.yml` runs typecheck, tests and the build for the
  frontend, but not lint, so "oxlint clean" holds only when someone runs it. Adding `npm run lint` (with
  `--deny-warnings`, since the bar is zero warnings) there would keep it true.
- ~~**Branches not yet merged pick these rules up on merge.**~~ Done in the combine above (`fdfb92d`, `3de4c8f`). M1.4 Phase C (`claude/compassionate-goldwasser-e62a07`,
  888fbc9), linted read-only from a scratch export with this config, shows exactly one warning beyond the two fixed
  here: `src/components/assist/dockHooks.ts:54`, `react(set-state-in-effect)` in `useNews` (`setNews` in an effect that
  also writes the module-level `announced` map and fires notifications). Phase C owns that file and should settle it
  when it merges. Its `Shell.tsx` change (imports, and the dock under `<main>`) does not touch `useDrawer`, so the
  two branches should merge without a conflict there.
