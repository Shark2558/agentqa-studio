# Handoff — AgentQA Studio v1 (updated 4 Nov 2026, after M1.3)

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
| **M1.3 Live View v2** — A: board, phases, run-shell events, one feed over WebSocket + SSE, Viewer rule · B: the React Live View with replay · C: owner acceptance (three fixes) | **done**, reviewed, acceptance watched 4 Nov 2026; **merged into `main`** (fast-forward, on the owner's word, 4 Nov 2026) | `b6711d6` · `b02ec86` · `44ede97` · `8ff58c0` |
| **M1.4 Gates in the new UI** (plan `docs/plans/m1-4-gates.md`) | plan approved 4 Nov 2026 (all seven decisions as recommended); **Phase A done** (the gates' backend); **Phase B done** (the three gates in the app, reviewed; branch `claude/pensive-zhukovsky-481d45`, on Phase A, not merged); **acceptance sitting 1 done** with the owner (4 Nov 2026: all seven steps, 19/19 and 0 extra) and its five findings fixed (5 Nov 2026); **A+B and the fixes merged into `main`** (fast-forward to `301fb3d`, on the owner's word, 5 Nov 2026); **Phase C done** (visual review, heals, the "AgentQA needs you" box, take-over, pause; reviewed as lock-marked by all five reviewers in fresh contexts, security twice (backend and app), every HIGH and MEDIUM fixed test-first; branch `claude/compassionate-goldwasser-e62a07`, **not merged**); **next: acceptance sitting 2** with the owner (ask first; plan → Acceptance → Sitting 2), then Phase D | plan `35acae8` + approval · Phase A `8c9d651` · Phase B `b4a53e6` · `f1ad631` · sitting-1 fixes `301fb3d` · Phase C on its branch |

Every milestone has a plan with a verification and a review record in `docs/plans/`. Read `m1-3-live-view-v2.md` for the
latest patterns (three phases, fresh-context review tables, acceptance findings fixed test-first, "open" rows kept).

**M1.4 Phase C (5 Nov 2026):** backend **809 passed**, pyflakes clean; frontend **488 Vitest** in 54 files (two page
tests time out under load and pass alone), `tsc -b` and oxlint clean; contrast 244/244; `check_app.py` and
`check_gates.py` (with `check_gates_c.py`) green; `tools/e2e_assist.py` 27/27 on the signed-in API; demo regression
19/19 with 0 extra. Details: the plan's Verification, Review and Record → Phase C.

Test counts at the M1.3 hand-off: backend **477 passed**, pyflakes clean; frontend **275 Vitest** in 34 files, `tsc -b` and
`oxlint` (with jsx-a11y) clean; contrast 232/232 (`make lint`); `make ui-check` green at six widths in both themes for
nine pages (with a `live-run` page and a middle-column width check); `make live-check` green (live over WebSocket,
reload, replay, SSE fallback); demo regression 19/19 with 0 extra on 4 Nov 2026 in **No-AI** (started from the app)
and **Cloud** ($0.27, see below), as in M1.2 for Local and the cap.

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

## M1.3 — what shipped (plan, verification, reviews and acceptance: `docs/plans/m1-3-live-view-v2.md`; ADR 0003)

Live View v2 at `/app/projects/{slug}/live`: the pipeline with its three gates, one card per agent (state as border +
glyph + word, model and cost per card), what the chosen agent is doing (browser frames, the event stream by phase),
test tiles, findings, and Details (document, site map, rules, code, activity). It streams over a WebSocket and falls
back to SSE; a finished run opens at its final picture with Replay from the start, pause, step, scrub, speed and Final
picture. Phases are derived from the 41 existing event kinds (no agent changed); the run shell adds stage skip / fail,
pipeline end, a running marker for command-line runs and one cost line per billed call. A Viewer may read, never
write: one rule answers 403 `read_only` to every write, and the pages offer no run, project or wizard action.

Facts the next milestones should know: on 4 Nov 2026 the owner's **Anthropic account ran out of credit** mid-run
("credit balance is too low"); the gateway fell back to Gemini and the run still scored 19/19 — he adds Anthropic
credit himself if he wants it back. Two follow-ups came from it (below). The browser pane's width is whatever the
owner makes it (seen: 800, 1149, 1918 px), so check pages at the widths he uses too.

## M1.4 — Phases A and B done, sitting 1 done, merged into `main` (5 Nov 2026); next: Phase C (`docs/plans/m1-4-gates.md`)

**Sitting 1 (4 Nov 2026, with the owner; v10)** passed all seven steps on a throwaway server in No-AI mode: the run stopped at the plan gate,
he answered, reopened with a reason and re-planned, rejected a case, approved the plan and the imported cases, `check_demo` before Gate 3
gave **19/19 and 0 extra**, he confirmed 18 defects and rejected one, the Zoho CSV held the 18, the change log showed his email and
reasons, and a Viewer saw no decision anywhere. Record: plan Verification → Sitting 1.
- **Five findings fixed (5 Nov 2026), reviewed by three fresh-context reviewers** (plan Review → Sitting 1 fixes):
  - S1, the owner's decision "honest words now, real later": answers to vague-requirement and contradiction questions are notes no
    stage reads, so the page says so and such a requirement stays "Not testable" with the answer in its note;
  - S2 "Select the N defects shown" (shared `SelectAll`, part-ticked, tracker-filed defects left out);
  - S3 the change log shows an answer's question as the question;
  - S4 the `.why` class clash with the wizard (stray blue bars);
  - S5 a Viewer's Project page says "What is waiting".
- **The owner's design wishes (O1–O4)**: a Live View showing every agent's work, a livelier look with more themes and animation, numbered
  same-size agent cards, the workflow drawn as it runs. **He chose a design slice of its own right after M1.4**, planned with a mock he
  approves before any code; it starts after the follow-up branch (`AgentBoard.tsx`, `board.ts`) merges. Memory: `owner-visual-direction`.
- **Merged:** the owner said yes on 5 Nov 2026; `main` was fast-forwarded to `301fb3d` (four Drive ghost files re-read first, as the
  memory note says) and the main folder's `frontend/dist` rebuilt. He then looked at the fixes on a fresh server built from `main`.
- **Open, small:** a defect's evidence picture whose file is missing shows a broken-image icon; it should say the file is missing (seen
  with the gates fixture, which keeps only 6 pictures). "Real later" for vague answers needs its own plan.

**Phase B (4 Nov 2026)** is on branch `claude/pensive-zhukovsky-481d45` (on Phase A), not merged. In the React app:
- the Questions, Test plan and Defects pages;
- the Change log page;
- the Requirements page's dispositions, "Show more" and RTM download;
- navigation badges;
- the Project page's "What needs you" card and the switch, now "Approve the test plan automatically (demos)", off by default;
- the Live View's gates as links.

Checks: `make gates-check` (new) and `make ui-check` green; 367 Vitest; three fresh-context reviews with every HIGH and MEDIUM fixed. The plan's Phase B record lists where the code differed. Item 2 (Run vs "Apply my answers" rules) was decided by the owner the same day: a re-plan reuses the rule the run used (done). Sitting 1 is prepared, not run (the hand-over note in the session notes folder has the script and the steps).

**Phase A (4 Nov 2026)** is on branch `claude/compassionate-haslett-3eb339`, not merged. It covers:
- the API for questions, the test plan (with imported cases), defects with evidence, requirement dispositions, the change log and the gate counts;
- who and why on every decision;
- one closing store per request;
- formula-safe exports built in a folder of their own;
- the `replan` command and the "approved earlier" line.

Checks: 19/19 with 0 extra, the full suite green, three fresh-context reviews with every HIGH and MEDIUM fixed. The plan's record lists where the code differed from it; read item 1 (`replan` uses project.yaml's policy) before building the Questions page. **Phase B must show the Requirements page's `total`**: the list now comes 200 rows at a time.

The plan was approved on 4 Nov 2026 with all seven decisions as recommended. Four phases, each a commit: **A** the three
gates' API (questions, test plan, defects, requirements dispositions), who/why in the change log, one store per
request, formula-safe exports, the `replan` command; **B** the three gates in the React app, then **acceptance sitting
1** (the PRD acceptance); **C** visual review, heals, the needs-you box, take-over and pause (reviewed as 🔒);
**D** retire the replaced old pages, the M1.3 carry-overs, **acceptance sitting 2**. Both sittings run in No-AI mode.
The follow-up branch `claude/nervous-sutherland-913fae` (`482c887`, M1.3 C4/C5) touches `AgentBoard.tsx` and
`board.ts`: Phase D waits for it to merge before the `AgentBoard` items.
M1.3 is in `main` (the owner said merge on 4 Nov 2026); start M1.4 from `main`. A follow-up session was started the
same day for the gateway's "credit balance is too low" handling and provider switches in the Live View (C4, C5).

## Follow-ups parked (not blockers)

Playwright `e2e/wizard.spec.ts` and a `NewProject` container test (M1.1 review) · CI Docker build cache (M0.2) ·
old dashboard's `testdata_account` keeps its own copy of the account rules (M1.4 retires the page) · `web/app.py`
is 1 400 lines (M1.4 replaces it) · the old dashboard's `/p/{slug}/files/{rel:path}` serves any file type (M1.4
Phase D removes it) · trace, video and log-JSON evidence is downloadable by every signed-in role (M2.1: owner and
tester only) · proxy-aware client address and a full
access log (cloud edition, M3) · from M1.3 Phase C: the gateway reads Anthropic's "credit balance is too low" (HTTP
400) as a refused request, so the empty key stays "ok" and is tried before every call — classify it as billing
(`ai/providers.classify`, 🔒 gateway) · the Live View shows no line when the gateway switches provider and a card
names only the last model used · the run picker shows a run folder's last change, not its start · site-map children
in their parent's column · B19 (a socket half-open after sleep still says "live": not seen, the PC did not sleep) and
B20–B22 in the M1.3 plan · a stray `backend/.venv` on Drive for the
owner to delete · **no GitHub remote yet** (commits are local only) · the CLAUDE.md "Environment" section is the
place for new machine gotchas.

## The loop to follow (ECC, non-negotiable)

plan in `docs/plans/<milestone>.md` → owner approves → failing tests → implement → **fresh-context review**
(security-reviewer for anything touching auth, secrets, the AI gateway, execution) → fix HIGH/MEDIUM test-first →
verify in the browser → commit with a detailed message → update memory → record what was left open.
