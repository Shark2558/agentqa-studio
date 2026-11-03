# Handoff — AgentQA Studio v1 (written 3 Nov 2026, after M1.1)

Read this first in a new session, together with `CLAUDE.md`. It says where the build stands, how to run things on
this machine, what the owner has decided, and what M1.2 must deliver. The PRD is `../01-PRD-AgentQA-Studio-v1.md`
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
| **M1.2 AI modes & selector 🔒** | **next** | — |

Every milestone has a plan with a verification and a review record in `docs/plans/`. Read `m1-1-onboarding-wizard.md`
for the latest patterns (tests first, fresh-context review table, "left open on purpose").

Test counts at hand-off: backend **174 passed** (`python -m pytest -q tests` from `backend/`, ~90 s), frontend
**25 Vitest** passed, `tsc -b` and `oxlint` clean, demo regression 19/19 (last run in M0.5 acceptance).

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
  works on 8720.
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

## M1.2 — what the PRD asks for (plan it first, 🔒 security review before commit)

From PRD §9: **mode switch** (No-AI · Local · Cloud · Hybrid) per project; **provider catalogue** incl. Ollama and
**LM Studio detection**; **per-agent assignment table** (agents ask for a tier cheap/balanced/strong/vision, never a
model id — CLAUDE.md non-negotiable); **consent switches** (send document text? send screenshots?); **cost meter**;
**budget cap with No-AI fallback** and an alert; **legacy `agentqa/llm.py` removed** (the gateway in `agentqa/ai/`
replaces it). Acceptance: the same demo run in No-AI, Local (Ollama qwen3) and Cloud (Anthropic) modes; cost shown
per agent; the cap triggers the fallback and the alert.

What already exists to build on: `agentqa/ai/{providers,router,store}.py` (gateway with failover, encrypted key
store in `%APPDATA%\AgentQA`, audit log of every call, `Adapter.last_usage` tokens), the `ai-test` CLI, the
Anthropic adapter on SDK 2.3 (`output_config.effort`, server-side fallbacks). Real keys for **Anthropic and Gemini**
are in the owner's encrypted store and both pass `ai-test`. The wizard's step 4 (`frontend/src/pages/wizard/
StepLater.tsx`) is the placeholder to replace; `req_chat.chat()` already takes the AI path when
`project.cfg["ai"]["mode"] != "none"` (read from `project.yaml`; no UI writes it yet).

Known gaps to fold into M1.2: Gemini auto-pick chose `gemini-3.8-flash` (times out) so the key is pinned to
`gemini-flash-lite-latest` (fallback `gemini-3-flash-preview`) — fix the auto-pick; usage/cost is only recorded for
Anthropic so far; **Ollama 0.40.13 is installed** on this PC since 3 Nov 2026 but has no model pulled yet (the owner runs
`ollama pull qwen3:4b` himself: the assistant's sandboxed shell cannot; 4 GB GPU, so 4b not 8b). Plan: `docs/plans/m1-2-ai-modes.md`.

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
