# Handoff — AgentQA Studio v1 (updated 3 Nov 2026, after M1.2)

Read this first in a new session, together with `CLAUDE.md`. It says where the build stands, how to run things on
this machine, what the owner has decided, and what the next milestone must deliver. The PRD is `../01-PRD-AgentQA-Studio-v1.md`
(sections: §4 journey, §5 functional requirements, §7 architecture, §9 phases and milestones, §11 design, §12 ECC).

## Who you are working with

Akash is **non-technical**. Explain in plain English, click by click; jargon goes in the plan files. Ask before
spending money, running downloaded code, or anything irreversible. **He types secrets himself** (terminal or an app
page), never into chat; never print keys or the contents of `backend/.env`, only variable names. He approves every
milestone plan before code is written and likes being shown the result in the browser pane.

## Where the build stands

| Milestone | State | Commit |
|---|---|---|
| M0.1 repo + ECC + CI, M0.2 Docker, M0.3 real-AI validation, M0.4 design system | done | 63d3f38 · b2b8370 · 697e93f · 40d4151 |
| M0.5 `/api/v1` + orchestrator extraction + React app shell at `/app` | done | 291e259 |
| **M1.1 onboarding wizard** (six steps, documents with verdicts, Requirement Chat agent, accounts into the vault, address preflight, Requirements page) | done, reviewed, acceptance watched | bee5d2a |
| **M1.2-UI** flat blue-and-white look, five accents, phone layout, Live View reachable (owner-approved mock, reviewed) | done | 2b21608 · 7d2c613 · a6106ea · 2943fbe |
| **M1.2 AI modes & selector 🔒** — Phase A (backend gateway modes, tiers, usage, budget; `llm.py` removed) | done, merged into `main` | `cea3977` → merge `0c68c9f` |
| **M1.2 Phase B** (wizard AI step, AI page: providers, local detection, agents, spend; real-Ollama fixes; four acceptance runs) | **done**, reviewed, acceptance watched | `757402e` (+ the docs commit after it) |
| **M1.3** (PRD §9: next milestone) | **next**: plan it first, owner approves | — |

Every milestone has a plan with a verification and a review record in `docs/plans/`. Read `m1-2-ai-modes.md` for the
latest patterns (tests first, fresh-context review table, "left open on purpose", what the real Ollama taught).

Test counts at hand-off: backend **339 passed**, pyflakes clean; frontend **106 Vitest** in 20 files, `tsc -b` and
`oxlint` (with jsx-a11y) clean; contrast 212/212 (`make lint`); `make ui-check` green at six widths in both themes for
seven pages; demo regression 19/19 with 0 extra in **No-AI, Local (qwen3:4b, about 60 min) and Cloud (Anthropic,
$0.34, about 12 min)**; the $0.50-cap project tripped the warning and the cap mid-run (see the plan's Verification).

## How to run it here (Windows, Google Drive folder — the gotchas matter)

- Python venv: `C:\Users\akash\.venvs\agentqa-studio\Scripts\python.exe` (never inside the Drive folder: OpenSSL's
  certificate read takes ~45 s there). Anaconda 3.13 is the base.
- npm: **always** `bash frontend/local-node.sh <npm args>` (Drive refuses `node_modules`, junctions and symlinks;
  the script mirrors `frontend/` to `~/.cache/agentqa-studio/frontend-work`, runs npm there, copies `dist/` back).
  `make web-*` wraps it. Typecheck `run typecheck`, tests `test -- --run`, build `run build`, lint `run lint`.
- Server: from `backend/`: `python -m agentqa ui --port 8720 --projects-dir projects` (API `/api/v1`, React app
  `/app`, old v0.8 dashboard at `/`, all behind the owner sign-in from `backend/.env`, created by `owner-set`).
  At hand-off two servers were running in his terminal tabs: **8710 (old code, his tab; the assistant cannot restart
  it because he typed in it)** and **8720 (current code, assistant's tab c9)**. Demo portals: `python -m agentqa
  demo-portal` → 8800 (citizen) and 8810 (department); they were still running.
- The assistant's shell is **sandboxed**: its writes to `%LOCALAPPDATA%` / `%APPDATA%` are invisible to the owner's
  real session (Playwright browsers, the vault key under `%APPDATA%\AgentQA`). So the owner runs
  `python -m playwright install chromium` himself once per machine, and the assistant cannot decrypt a vault the
  owner's server wrote — check accounts through the API instead (`GET /api/v1/projects/<slug>/accounts`).
- Browser pane: ~860×527 viewport; buttons below the fold need `scroll_to` or a JS `.click()`; `form_input` on a
  checkbox does not fire React's `onChange` (use a real click); the app's CSP (`connect-src 'self'`) blocks fetches
  to other ports from the page. Session cookies are shared across ports on 127.0.0.1, so a sign-in on 8710 also
  works on 8720. The owner's session on 8720 expires and the assistant must never type his password: to look at a
  signed-in page, start a **throwaway server** with a generated owner, `AGENTQA_HOME` and `--projects-dir` in the
  scratchpad (the M1.2 session's `review_server.py`), sign in there, and create the demo with `POST /api/v1/projects/demo`.
  Acceptance runs with the real keys use the CLI (`pipeline -p <folder>`) on a demo copy placed in that server's
  projects dir, so its Live View and AI page show the run.
- The Bash tool's heredocs break on backticks (use the Write tool for TS files); port 8730 is taken on this PC.
- `localhost` is slow on this PC: use `127.0.0.1`.

## Decisions the owner has made (do not re-ask)

Keep the v0.8 engine, rebuild the shell · one Docker image for laptop and Google Cloud · v1 = web + API · team
logins Owner/Tester/Viewer (M2.1) · reports HTML/PDF/Excel/Word/PPT/email digest (+CSV/JSON/JUnit) · scheduler cron
+ webhook · Zoho via CSV both ways + optional API; Slack/Teams/WhatsApp alerts · **per-project AI consent, No-AI
default, No-AI fallback at the budget cap** · React + TS SPA · name "AgentQA Studio" · design: **flat professional blue and white**
(the M0.4 neumorphism was rejected by the owner on 3 Nov 2026 and replaced in M1.2-UI), Light / Dark / System + five
accents chosen in the app's Appearance menu, **IBM Plex Sans + JetBrains Mono**, Phosphor icons (`frontend/design-system/
MASTER.md`, `tokens.css`, 202/202 contrast checks by `make lint`, the built app measured at five widths by `make ui-check`). M1.1 specifics:
the wizard creates the project at step 1; AI-mode and Schedule steps are shown as "coming in M1.2 / M1.5";
preflight may fetch the typed URL (link-local/metadata blocked).

## M1.2 — what shipped (plan, verification and review: `docs/plans/m1-2-ai-modes.md`)

Per project: `ai:` block in `project.yaml` (mode none / local / cloud / hybrid, consent, budget, per-agent tiers),
saved from wizard step 4 (`pages/wizard/StepAi.tsx`) and the AI page `/projects/{slug}/ai` (`pages/ai/AiSettings.tsx`
composed of `components/ai/*`). Agents ask for a tier, never a model (`agentqa/ai/modes.py` routes). Keys live in
the encrypted vault, shared by every project, masked on the page, tested with one tiny call; Ollama and LM Studio
are detected at their fixed loopback addresses and stored as keys with "Use it" (the wizard does it itself for
Local / Hybrid). The spend meter is per agent and per run; at 80 % a warning, at the cap Cloud becomes No-AI and
Hybrid keeps the local model, with one live alert per state per month. `agentqa/llm.py` is gone; `ai-test` stays.

Facts the next milestones should know: a Cloud demo run costs about **$0.34** (Writer on Opus 5.5 is $0.31 of it);
the owner's real keys (Anthropic, Gemini) are in the vault with **Anthropic first** in the order; **Ollama 0.40.13 +
qwen3:4b** answers at about 8 tokens/s here, so Local runs take about an hour and local keys default to a 600 s
timeout; Visual QA makes no AI call on a first run (no baseline yet); the budget minimum is $0.50. The wizard's
step 5 (`StepLater.tsx`) is now the only placeholder left ("coming in M1.5").

## M1.3 — next (plan it first, owner approves; 🔒 review if it touches execution or the gateway)

Take the scope from PRD §9 for M1.3 and write `docs/plans/m1-3-<slice>.md` before any code. The Live View already
streams every agent's events with reconnect from the last cursor (M1.2-UI); the clarification and approval gates are
still answered in the old dashboard until M1.4.

## Follow-ups parked (not blockers)

Playwright `e2e/wizard.spec.ts` and a `NewProject` container test (M1.1 review) · CI Docker build cache (M0.2) ·
old dashboard's `testdata_account` keeps its own copy of the account rules (M1.4 retires the page) · `web/app.py`
is 1 400 lines (M1.4 replaces it) · `list_requirements` has no LIMIT (M1.4) · proxy-aware client address and a full
access log (cloud edition, M3) · ErrorBoundary in the React app (M1.3) · a stray `backend/.venv` on Drive for the
owner to delete · **no GitHub remote yet** (commits are local only) · the CLAUDE.md "Environment" section is the
place for new machine gotchas.

## The loop to follow (ECC, non-negotiable)

plan in `docs/plans/<milestone>.md` → owner approves → failing tests → implement → **fresh-context review**
(security-reviewer for anything touching auth, secrets, the AI gateway, execution) → fix HIGH/MEDIUM test-first →
verify in the browser → commit with a detailed message → update memory → record what was left open.
