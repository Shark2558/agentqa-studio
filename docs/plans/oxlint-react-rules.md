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
- **Branches not yet merged pick these rules up on merge.** M1.4 Phase C (`claude/compassionate-goldwasser-e62a07`,
  888fbc9), linted read-only from a scratch export with this config, shows exactly one warning beyond the two fixed
  here: `src/components/assist/dockHooks.ts:54`, `react(set-state-in-effect)` in `useNews` (`setNews` in an effect that
  also writes the module-level `announced` map and fires notifications). Phase C owns that file and should settle it
  when it merges. Its `Shell.tsx` change (imports, and the dock under `<main>`) does not touch `useDrawer`, so the
  two branches should merge without a conflict there.
