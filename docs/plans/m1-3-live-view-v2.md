# Plan — M1.3 Live View v2

**Milestone:** M1.3 (PRD §9 Phase 1; §5.4 FR-LIVE-1…8; §7.3 "events are the contract"). PRD acceptance: **a demo run
watched live; its replay matches; a Viewer sees it read-only.**
**Marker:** the PRD does not mark M1.3 🔒, but it is reviewed as if it were: a WebSocket skips the HTTP middleware
(sign-in, rate limit, CSRF guard), the AI client gains a cost event, a new dependency arrives, and a role rule is added to
every write. **Owner approval:** required before building (asked 3 Nov 2026). Planned with the `planner` agent, which
checked every claim below against the code; the main points were re-checked by hand the same day.

## Goal

Replace the M0.5 board-and-list with the Live View of the approved mock (`frontend/design-system/mock/index.html`
329-386, `docs/design/m1-2ui-live-*`):
- an agent board in pipeline order, with honest states, and the model and cost on each card;
- for the chosen agent, a thought → action → result stream beside its browser frame(s);
- test tiles and findings;
- the pipeline timeline with the three human gates;
- the Document, Site map, Rules, Code and Activity panels, ported from the v0.8 player (`web/static/live.js`);
- replay with pause, step, speed, scrub and Go live.

Events travel over a WebSocket, with the existing SSE stream as the fallback. Recordings stay JSONL + JPEG, so live
view, replay and the cloud edition read the same files. Viewers can watch everything and change nothing.

## What the code says that changed the first design (recorded so nobody re-learns it)

1. Agents make about 200 `live.emit` / `live.shot` calls in 28 files with 41 kinds. PRD §7.3's "new kinds thought /
   action / result / waiting" would mean rewriting all of them. Instead each event gets a derived **`phase`** when it is
   read (`orchestrator/phases.py`): the files on disk do not change and old recordings get phases too. `model` and
   `cost` already exist (M1.2). ADR 0003 records this reading of §7.3.
2. One kind can mean two things: `model` from `srs` is "asking the model" (`srs_analyst.py:541,566`), from `ai` it is
   "model in use"; `requirement` from `srs` is reading, from `writer` a rewrite. The phase table needs (agent, kind)
   overrides.
3. Helpers are not tied to one stage: `analyst` events come from `requirements.standardise` (`requirements.py:174`,
   called by the Writer, the Designer and the Reporter) and from `workflows.py:226`; `casegen` runs inside design;
   `importer` between stages. AI keys such as `login`, `visual_qa`, `requirements` and `documents` serve several stages
   and the pytest workers. So helper, `model` and `cost` events are **attributed by time** to the stage running at `t`
   (from the main worker's `stage_start` / `stage_end`); only `importer` has a static fallback (design). `_announce`
   dedupes per process, so each gw worker announces again; the board dedupes by `agent_key` per stage.
4. Today a recording cannot end honestly: a failed stage emits nothing (the `cli.stage` except branch only writes
   `stage_runs`), the pipeline never emits its own end, a skipped exploratory stage emits nothing (`cli.py:202-206`),
   and `--from` / `--resume` runs do not say which stages they cover. Four one-line events in the run shell fix this
   (table below); no agent changes.
5. `assist` fires when an agent starts waiting **and** again when it is answered, skipped or times out
   (`assist.py:103-126`); v1 keeps the card "waiting" forever. Waiting is now tracked per `assist_id`.
6. The pipeline does not stop at the questions gate: it logs and carries on (`cli.py:211-216`); it stops only at the
   plan gate when the plan is not approved. So the Reconciler card says **Done · 15 questions for you**, not the mock's
   "Waiting for you". "Waiting" is used only when something really waits: an open `assist`, or a stop at the plan gate.
7. `heading` events carry `level` as a number (heading depth, `srs_analyst.py:84,137`); the severity `level` is a
   string. The TS type `level?: string` is wrong; severity is read only when `level` is ok, warn or bad.
8. `test_end.category` has six values: passed, defect, visual, blocked, not-run, test-issue (`runtime/conftest.py:
   157-163`); a setup failure emits no `test_end`. Tiles keep all six apart (Blocked is never Passed); a test that
   started but has no end once its stage is over shows "no result".
9. `routes_live._is_running` calls `sessions()` every 0.5 s while a stream is quiet; `sessions()` walks every session
   folder and globs every screenshot (15 runs × ~1 000 on Drive), **on the event-loop thread** (the store's SQLite
   connection is tied to it), so it blocks the whole server. The stream also keeps the project store open for up to an
   hour. New `is_running(p, session)` checks only the asked run, in a worker thread, with its own short-lived store.
   `sessions()` keeps its `shots` count for the old dashboard (`web/app.py:332`); the API asks for the list without it.
10. A command-line run counts as running only while an event file changed in the last 8 s (`CLI_SESSION_LIVE_S`). A
    Local-AI Writer chunk can be silent for minutes, so the stream said "finished" mid-run (the M1.2 acceptance runs
    used the CLI). `cli._live_session` will write a `running.json` marker (with the pid) and remove it at exit; the 8 s
    rule stays for old folders.
11. The HTTP middleware (`@app.middleware("http")`) never runs for WebSockets, and the router-level
    `Depends(current_user)` takes a `Request`, which FastAPI does not give a WebSocket route. So the WS route has its
    own router and does its own checks: sign-in through `HTTPConnection`, Origin, rate limit, stream cap.
12. Neither `websockets` nor `wsproto` is installed (fastapi 0.162, starlette 1.10, uvicorn 0.54 without `[standard]`,
    sse-starlette 3.6). Starlette's TestClient runs WS routes without them, so a green test would not prove the real
    server speaks WebSocket. `deploy/constraints.txt` pins every package, so the new one is pinned there too.
13. Screenshots are served under `/api/v1`, so they count against the 240 requests/min per address limit
    (`api/settings.py:48`); a fast replay or a column of thumbnails trips 429 (the old dashboard's route sits outside
    the limiter). Screenshots get their own bucket and frame-image swaps are throttled to 4/s during fast replay.
14. The cursor is trusted as it comes in: a crafted offset (`-1`, `"x"`) raises inside `read_events` (500) and unknown
    keys are carried forever. It will be validated.
15. The client dedupes on `w:seq`, unique while one process writes each worker file — true today (one main pytest and
    one login pytest per run stage, `executor.py:155-167`).
16. The React app has no ErrorBoundary and `useMe` throws every non-401 error (`App.tsx:15-21`): today one failed
    `/auth/me` blanks the whole app.
17. `frontend/local-node.sh` mirrors only `frontend/`, so Vitest cannot read `backend/tests/fixtures`; the Vite dev proxy
    has no `ws: true`.
18. The mock is a sketch: "3 of 10 stages" in another order; `cli.STAGES` has 12 (analyze, explore, reconcile, write,
    design, generate, run, exploratory, security, triage, heal, report). The scan-line recipe exists only in the mock's
    CSS (`motion.css` has a comment); MASTER §6 still says 202/202 and five widths (now 212/212 and six).
19. `cli.py` is 723 lines and `cmd_pipeline` is already 61 lines (over the 50-line rule). Neither takes new logic: the
    stage→agent dict moves out, and the new emits arrive with an extraction that brings `cmd_pipeline` under 50 lines.
20. No coverage tool is installed (no pytest-cov, no Vitest coverage). Each new module gets its own test file; coverage
    is measured from M1.8.

## The board (`orchestrator/board.py`, pure; the one source for cli and UI)

| # | Stage | Agent | Card label | Live counter (ported from `live.js counter()`) | Gate |
|---|---|---|---|---|---|
| 1 | analyze | srs | Requirement Analyst | requirements · rules · vague words | — |
| 2 | explore | explorer | Explorer | screens mapped · current role | — |
| 3 | reconcile | reconciler | Reconciler | rules by status · questions | **Questions for you** (after) |
| 4 | write | writer | Requirement Writer | rewritten · flagged | — |
| 5 | design | designer | Test Designer (+ Analyst, Test Case Generator, Test Importer) | cases | **Test plan approval** (before generate) |
| 6 | generate | generator | Script Generator | files · tests | — |
| 7 | run | executor | Executor | passed · failed · blocked · running | — |
| 8 | exploratory | exploratory | Exploratory Tester | pages · findings | — |
| 9 | security | security | Security Scanner | alerts / progress | — |
| 10 | triage | triage | Triage + Bugs | defects | **Defects to confirm** (after) |
| 11 | heal | healer | Healer | proposals | — |
| 12 | report | reporter | Reporter | report ready | — |

Other cards appear only when seen: `doctor` (Readiness check), teach-login runs, single-stage jobs. `STAGES`,
`STAGE_AGENT`, `LABELS`, `HELPERS`, `GATES` and `AI_LABELS` (from `ai/modes.AGENTS`) live here; `cli.STAGES` and
`cli.stage()` import them.

**Card states (FR-LIVE-1), always glyph + word:** Queued (not started, run going) · Running (pulses) · Waiting for you
(open `assist`, or stopped at the plan gate) · Done (with an amber note when questions or defects wait) · Skipped
(`stage_skip`, with the reason) · Failed (`stage_end` level bad) · Not in this run (outside the run's `stages`) · Not
reached (the run ended first) · Did not finish (started, no end, run over: old recordings and crashes).
Meta line: elapsed time · model (the actual one from `cost`, else the planned one from `model`, else "no AI: <reason>")
· cost so far.

**Gates:** Questions = count of `question` events. Plan = the designer's `approve` (auto or by a person) shows green;
the pipeline's `gate` stop shows amber "waiting for you". Defects = count of `defect` events "to confirm (in the old
dashboard until M1.4)".

## Phases (`orchestrator/phases.py`, added by `read_events`)

| Phase | Kinds | Shown as |
|---|---|---|
| thought: what it reads, which rule fired, what it plans | open, heading, text, table, rule, ambiguity, unclear, persona, role, case, test_start; (srs, requirement); (srs, model) | "Thought". In No-AI mode, the rule that fired (`rule_kind · field · value`, "from the SRS text"); a `source: llm` rule is labelled **AI proposal** |
| action: what it did | action, navigate, request, step, write, approve, sync | "Action", with a thumbnail when `shot` is set |
| result: what happened | observe, verdict, test_end, status, defect, finding, issue, skip, contract, login, data, heal, question; (writer, requirement) | "Result"; level bad shows glyph + "Failed"; a model rewrite is labelled AI proposal |
| waiting | assist, gate | amber row + card state |
| lifecycle | stage_start, stage_end, stage_skip, start, summary, progress | dividers in the stream; marks on the timeline |
| meta | (ai, model), (ai, cost) | card meta and header totals; not stream rows |

An unknown kind in an old file reads as `note`; a test stops any source file from adding one.

## Event additions (run shell and AI client only; no agent behaviour changes)

| Where | Event | Fields | Why |
|---|---|---|---|
| `cli.stage` except branch | `<agent> stage_end`, level bad, "<stage> failed (see the run log)" | stage, exception class name only (the text can carry page content) | Failed card |
| `cmd_pipeline`, exploratory skipped | `exploratory stage_skip` | stage, why | Skipped card |
| `cmd_pipeline` start (emit moved below the resume logic) | `pipeline stage_start` gains `stages` (this run's list) and `pipeline` (the `pl-…` id) | | "Not in this run"; ties a recording to its `ai_usage` rows |
| `cmd_pipeline` end | `pipeline stage_end`, level ok / warn (stopped at the plan gate) / bad | stage, outcome | Honest finish in replay |
| `cli._live_session` | `running.json` {pid, started} in the session folder, removed at exit | | CLI runs stay "running" through quiet AI calls |
| `AiClient._on_usage`, after `usage.record` | `ai cost` per billed call | agent_key, tier, scope, provider, model, input/output tokens, cost_usd, estimated, ms, ok. **Never** the prompt, the answer, the key id or the key label; no `state` (budget alerts keep theirs) | Model and cost per card; the recording carries its own costs |

## Transport

| | SSE (kept) | WebSocket (new) |
|---|---|---|
| URL | `GET …/live/{session}/stream?cursor=` | `…/live/{session}/ws?cursor=` (ws: or wss:, following the page) |
| Feed | one async generator `live_feed(p, d, session, cursor)` in `api/live_feed.py`: reads in a thread every 0.5 s, sends batches, ends when the run is over and nothing new remains or after 1 h idle, re-checks every 60 s that the sign-in has not expired | same generator |
| Sign-in | router dependency | cookie read through `HTTPConnection`; any signed-in role may watch |
| Cross-site | SameSite=Lax cookie; GET only | **Origin must be present and equal the Host** (cross-site WebSocket hijacking: Lax cookies are sent on a cross-site handshake) |
| Limits | general bucket + stream slots | general bucket on the handshake + stream slots: 4 open streams per address across SSE and WS, 64 in total; client messages read and dropped, one over 1 KB closes the socket; uvicorn `ws_max_size` 64 KB |
| Messages | `event: live` {events, cursor} · `event: end` {cursor, reason} | `{"type":"live",…}` · `{"type":"end",…}`, then close 1000 |
| Refusals | HTTP 401 / 404 / 429 | accept, then close with a code, nothing sent first: 4401 signed out · 4403 origin · 4404 no such run · 4429 too many streams |

Client (`lib/liveStream.ts`): WebSocket first; if the socket closes before `open`, SSE for the rest of the tab
(remembered in `sessionStorage`). 4401 stops with "Your session ended: sign in again"; 4404 says "This run no longer
exists"; 4429 waits 10 s and retries; any other drop reconnects from the last cursor (the merge ignores what it has).

Why this is worth it beyond the PRD: uvicorn speaks HTTP/1.1 only, and browsers allow six HTTP/1.1 connections per
origin, so a few SSE tabs can starve the page's API calls. WebSockets do not take one of those six slots.

## What is built

### Backend (every file ≤ 400 lines)

| File | Responsibility | Size |
|---|---|---|
| `orchestrator/board.py` (new, pure) | STAGES, STAGE_AGENT, LABELS, HELPERS, GATES, AI_LABELS, `board(roles)` | ~140 |
| `orchestrator/phases.py` (new, pure) | PHASES, OVERRIDES, `phase_of(event)` | ~80 |
| `orchestrator/live.py` | `read_events` adds `phase`; validated cursor (only known `events-*.jsonl` names, offsets clamped to 0…file size, ≤ 64 keys; a bad cursor restarts from the beginning); `is_running(p, session)` (job row + pid, or run marker + pid, or the 8 s rule); `mark_running(folder)`; `sessions(count_shots=True)` + `has_events` | 82 → ~180 |
| `orchestrator/jobs.py` | `job_running(store, job_id)`: one row and one pid check, not "the latest running job" | 93 → ~110 |
| `api/live_feed.py` (new) | `live_feed` generator; `StreamSlots` (per address and in total, released in `finally`); store closed on exit | ~130 |
| `api/routes_live.py` | `/board`; SSE through `live_feed` + slots; events and sessions use `is_running`; `cursor` ≤ 4 096 chars (longer → 422) | 81 → ~120 |
| `api/routes_live_ws.py` (new) | WS route: sign-in, Origin, limiter, slots, close codes, a task that receives and drops client messages | ~130 |
| `api/auth.py` | `session_user(conn: HTTPConnection)`, `client_key(conn)`, `WRITE_ROLES = {owner, tester}`, `same_origin_strict(conn)` | 149 → ~180 |
| `api/__init__.py` | middleware: a POST / PUT / PATCH / DELETE from any role outside WRITE_ROLES gets 403 `read_only`, on the API **and** the old dashboard (login and logout exempt; an unknown role counts as read-only); screenshots use their own bucket; WS router added | 149 → ~175 |
| `api/settings.py` | `shot_rate_per_min` 1 200, `streams_per_client` 4, `streams_total` 64 | 70 → ~76 |
| `cli.py` | imports the board; the four run-shell events; `_live_session` marks the run as running; `cmd_pipeline` split under 50 lines; `uvicorn.run(…, ws_max_size=65536)` (`cli.py:524`) | 723 → ~725 |
| `ai/client.py` | `_on_usage` emits the per-call `cost` after the usage row is written | 172 → ~190 |
| `requirements.txt`, `deploy/constraints.txt` | `websockets` (decision 1) | +1 each |
| `tools/make_live_fixture.py` (new) | trims a real demo recording into a fixture: every agent and kind, the gates, defects, verdicts, ~400 events and 12 screenshots; fails if any demo account password or OTP appears; writes the backend folder and `frontend/src/test-fixtures/live-demo.json` | ~120 |
| `docs/adr/0003-live-phases-and-transport.md` (new) | phases instead of new kinds; WS + SSE; the Viewer write rule | — |

### API (`/api/v1`, envelope, rate-limited)

| Endpoint | What changes |
|---|---|
| `GET /projects/{slug}/live/sessions` | adds `has_events`; no screenshot globbing (the old dashboard keeps its count) |
| `GET /projects/{slug}/live/board` (new) | the board above + the project's roles (the page prefers the `roles` stored in the recording) |
| `GET …/live/{session}/events` | events carry `phase`; validated cursor; cheap `running` check |
| `GET …/live/{session}/stream` | shared feed, stream slots, store closed |
| `WS …/live/{session}/ws` (new) | as in the transport table |
| `GET …/live/{session}/shots/{name}` | own rate bucket; same path guard; 1-day cache |
| every POST / PUT / PATCH / DELETE | 403 `read_only` for a Viewer session |

### Frontend (`frontend/src/`, every file ≤ 400 lines)

**Pure logic in `lib/live/`:**
- `event.ts` (~90): type guards and cleaners — `LiveEvent` with `level: string | number` and `phase`; `severity(e)`;
  `safeBox(e)` (finite, positive, inside the viewport); `safeShot(name)` (`^[\w.-]{1,80}\.jpg$`). Unknown fields are
  ignored; collections keyed by strings from the tested app (paths, case ids) are `Map`s, never plain objects.
- `stream.ts` (~110, replaces `lib/live.ts`; its test moves too): dedupes by `w:seq`, merges events sorted by
  (t, seq, w), reports the earliest changed index; keeps up to 50 000 events, then says so.
- `model.ts` (~150): `fold(model, events) → model`, pure (never changes its input; copies each touched slice once per
  batch); checkpoints every 500 events; `modelAt(pos)`. Slices: `board.ts` (~180: cards, time attribution, gates, AI
  totals), `lanes.ts` (~100: one browser frame per worker — shot, box, URL, role, case, last 6 steps, verdict),
  `panels.ts` (~200: tiles, findings, rules, document, code), `siteMap.ts` (~120: nodes by click depth, roles, HTTP
  errors, pure layout).
- `player.ts` (~120): position, playing, speed (0.5–10× or instant), follow; `dwellMs(event, speed, backlog)` ported
  from `live.js dwell()`; the position saved in `sessionStorage` per run.

**Hooks and helpers in `lib/`:** `liveStream.ts` (~150: `useLiveStream`, WebSocket first then SSE, reconnect from the
cursor, status `connecting | live | retrying | ended | signed-out | gone`, transport in `data-transport`), `can.ts`
(~20), `api.ts` (`board()`, `wsUrl()`, `has_events`).

**Components in `components/live/`** (each 50–130 lines): `RunHeader` (run, start, workers, "AI so far: tokens · $",
new-run banner) · `PipelineCard` (progress "n of m stages done"; the timeline as a list of buttons, gates in amber,
Enter jumps the replay there) · `AgentBoard` and `AgentCard` (each card a button that selects the agent) · `AgentFocus`
("<agent> · what it is doing": `BrowserFrame` with the scan-line while running and worker chips; `PhaseStream` with the
updated `EventRow`, newest 300 rows + "Show earlier", lazy thumbnails with explicit width and height) · `TestTiles`
with its legend, `Findings` · `DetailsTabs` (WAI-ARIA tabs) holding `DocumentPanel`, `SiteMapPanel` (SVG, all text
through React), `RulesPanel`, `CodePanel` (`<pre>`, text only), `ActivityPanel` (agent filter, "problems only") ·
`PlayerBar` · `Lightbox` (a dialog with an inert background; Escape closes it and focus returns — the NavDrawer
pattern). One throttled `role="status"` per region (card state changes on the board; position and paused on the
player); the stream keeps `role="log"`.

**Error handling:** `components/ErrorBoundary.tsx` (~50, the one class component React still needs) wraps the app root
and each Live panel: "This panel could not be shown; the rest of the run is fine". `useMe` keeps throwing non-401 errors
into the root boundary, which now shows a message instead of a blank page.

**Pages:** `pages/Live.tsx` (~150) and `pages/LiveRun.tsx` (~150). The URL keeps `session`, `agent` and `tab`. Without
a session in the URL the page picks the running run, else the newest with events. A finished run opens at the final
picture with **Replay from the start** (decision 4); a running run follows live. A Viewer sees no run prompt.
`pages/Project.tsx`: no Run button for a Viewer.

**Styles:** `styles/live.css` (board, stream, tiles) and `styles/live-frame.css` (frame, the mock's scan-line moved
into `motion.css`, timeline, map, player, lightbox), each ≤ 400 lines. Layout per the mock: from 1100 px three columns
(`300px minmax(0,1fr) 320px`) with Details full width below; under 760 px everything stacks; the timeline and the tab
list scroll inside their card, never the page; the player bar stays in the flow (a sticky bar could hide the focused
element). Reduced motion turns off the scan-line and makes the pulse a static ring. `check_contrast.py` gains the
phase-label pairs if any pair is new.

**Build config:** `vite.config.ts` gets `ws: true` on the `/api` proxy.

**Untrusted content** (page titles, URLs, SRS text, model rewrites, code previews, finding text, file names): rendered
as React text only, no `dangerouslySetInnerHTML`; the old `highlight()` HTML-building becomes text split into `<mark>`
nodes; URLs from the application under test are text, never links; screenshot names go through `safeShot` +
`encodeURIComponent` to the guarded route; box styles come only from validated numbers.

## Tests first

**Fixture.** `tools/make_live_fixture.py` runs once on the owner's real No-AI demo recording
(`cli-20261103-133627-pipeline`: 2 676 events, 996 screenshots, 6 worker files, 7.6 min), adding 3 `cost` and 2 `model`
lines shaped like the Cloud run. It writes `backend/tests/fixtures/live/cli-fixture-pipeline/` (events-main, gw0, gw1,
tests-login, 12 screenshots, ≈ 0.4 MB), `expected-summary.json` (card states, counters, tiles, findings, AI totals) and
`frontend/src/test-fixtures/live-demo.json`.

**Backend (pytest):**
- `test_live_board.py`: `cli.STAGES == board.STAGES`; every stage has an agent and a label; `cli.stage` emits with
  `board.STAGE_AGENT`; every `ai/modes.AGENTS` key has a label; `/board` envelope, 401 signed out, 404 unknown project.
- `test_live_phases.py`: an AST scan of every `.py` under `agentqa/` (runtime and conftest included) finds each
  `.emit(…)` / `.shot(…)` kind literal and checks it has a phase; a non-literal kind outside `live.py` fails; overrides
  hold (srs/model thought, ai/model meta, writer/requirement result); `read_events` adds `phase` and leaves the files
  byte-identical.
- `test_live_running.py`: job session running + alive → True, another job id → False, dead pid → False and the job is
  marked failed; CLI session with a marker and a live pid → True even after 60 s of silence, dead pid → False, no
  marker → the 8 s rule; `is_running` never calls `sessions()` and never globs `shots/`.
- `test_live_cursor.py`: negative, non-numeric, past-the-end, unknown-file and oversized cursors are clamped or restart
  from the beginning, never a 500; more than 4 096 chars → 422.
- `test_live_feed.py`: batches then `end`; resume from a cursor; the idle limit; the store is closed; `StreamSlots`
  per-address and total caps, released even after an exception; an expired sign-in ends the feed.
- `test_api_live_ws.py` (TestClient): owner and Viewer get the fixture's batches then close 1000; signed out → 4401;
  wrong or missing Origin → 4403; unknown run or `..%2F` → 4404; a fifth stream → 4429; an empty limiter bucket →
  4429; client messages ignored; a 2 KB message closes the socket.
- `test_live_ws_real_server.py`: the real app on uvicorn in a thread; the `websockets` client with cookie and Origin
  receives the first batch and `end`; without the cookie it gets 4401 (the proof TestClient cannot give).
- `test_live_run_events.py` (`_stage` faked): exploratory disabled → `stage_skip`; a stage that raises → `stage_end`
  level bad whose title holds no exception text; `pipeline stage_start` carries `stages` and `pipeline`;
  `pipeline stage_end` ok, warn at the plan gate, bad on failure; the run marker exists during the run and is gone
  after success and after failure.
- `test_ai_client.py` (extended): one billed call → one `ai cost` line with the listed fields; a planted prompt marker,
  the key id and the key label never reach the live file; a local call costs 0; budget alerts still carry `state`,
  per-call lines never do; the usage row is kept when the live write fails.
- `test_api_roles.py` (test-made Viewer cookie): every live GET → 200; every write route in `app.routes` (login and
  logout aside) and an old-dashboard form post → 403 `read_only`; the owner unaffected; `/auth/me` reports viewer; an
  unknown role counts as read-only.
- `test_api_hardening.py` (extended): 300 screenshot requests in a minute pass and leave the general bucket untouched;
  the screenshot bucket has its own cap.
- `test_api_projects_runs_live.py` stays green: the SSE contract is unchanged apart from the new `phase` field.

**Frontend (Vitest):**
- `event.test.ts`: bad shapes rejected; a numeric `level` kept but not a severity; NaN, Infinity, negative and
  off-viewport boxes dropped; `../x.jpg`, `a b.jpg` and 200-character names get no thumbnail.
- `stream.test.ts`: repeats ignored; a late gw1 event lands in order and reports its index; the 50 000 cap message.
- `board.test.ts`: every state in the table; `assist` open → waiting, answered → running (the v1 bug); `analyst`
  events attributed to write and to design by time; cost and model per card, deduped by agent key; a plan-gate stop →
  generate waiting, later stages "not reached"; questions → Done + "15 questions for you"; counters equal
  `expected-summary.json`.
- `panels.test.ts`: blocked, not-run and test-issue never show as passed; a start without an end → "no result";
  findings sorted by severity; exploratory findings merged once triage drafts defects; rule counts; code files.
- `siteMap.test.ts`: depth, parent edges, roles, HTTP-error nodes; probe navigations only move the current node; a
  path named `__proto__` is just another node.
- `model.test.ts` (**replay matches**): fold(all events) = fold(any batch split) = fold after shuffling events across
  workers within the same second (through the stream's sort) = checkpoint + fold at every 100th position; the input
  model is deep-frozen and never changes; the fixture's final model equals `expected-summary.json`; a 2 700-event fold
  takes under 200 ms.
- `player.test.ts`: the `dwellMs` table and backlog speed-up; step, restart, Go live, scrub, instant; position saved and
  restored per run.
- `liveStream.test.ts` (fake WebSocket and EventSource): WebSocket first; close before open → SSE; 4401, 4404, 4429
  handled; the reconnect URL carries the cursor; `end` → ended; the sessions list saying "running" again reopens it.
- Components: `AgentCard` (button name, glyph + word, "no AI: reason", cost) · `PipelineCard` (named buttons, gates,
  jump) · `DetailsTabs` (arrow keys, Home / End, `aria-selected`, labelled panels) · `TestTiles` (labels, legend) ·
  `BrowserFrame` (box placed in %, none when invalid, scan-line only while running, the URL is not a link) ·
  `PhaseStream` (300 rows then "Show earlier") · `Lightbox` (focus kept inside, Escape closes, focus returns) ·
  `ErrorBoundary` (a throwing panel shows its message, the board stays) · **untrusted content**: a title
  `<img src=x onerror=…>` and a `javascript:` URL render as text and create no element.
- `Live.test.tsx` and `Project.test.tsx` (extended): the fixture fills the header totals; a finished run shows the final
  picture + Replay from the start; a Viewer sees no run prompt and no Run button; the new-run banner.

**In a real browser** (no owner sign-in: a throwaway server and owner, like `check_app.py`):
- `check_app.py`: a new `live-run` page with the fixture copied into the throwaway demo project, measured at six
  widths, light and dark: the usual checks plus the timeline and tabs scrolling inside their cards.
- `frontend/design-system/check_live.py` (new, ~160; `make live-check`): opens Live View on a new CLI session with a
  marker; appends the fixture in 40 timed chunks and waits for the end; records the final picture (cards, counters,
  tiles, findings, AI totals); reloads and checks the same picture; Replay from the start at Instant, same picture
  again; repeats with the WebSocket refused (`page.route_web_socket`) so it falls back to SSE, same picture; asserts
  `data-transport` was `websocket`, then `sse`.

## Build order (three commits)

**Phase A — backend, transport, events (commit 1; it can merge alone, the v1 page keeps working).**
1. Fixture tool and fixtures.
2. `board.py` and `phases.py`; `phase` in `read_events`; cursor validation; `is_running` + run marker;
   `sessions(count_shots)`; `job_running`.
3. Run-shell events in cli (with the `cmd_pipeline` split); the AI per-call `cost`.
4. `live_feed` + `StreamSlots`; SSE moved onto them; `/board`; the screenshot bucket.
5. The Viewer write rule; sign-in through `HTTPConnection`.
6. `websockets` installed (decision 1), then the WS route and the real-server test.
7. Full suite, pyflakes, `check_demo` 19/0 in No-AI mode; fresh-context `code-reviewer` + `python-reviewer` +
   **`security-reviewer`** (WS surface, Viewer rule, AI client, cursor); HIGH and MEDIUM fixed test-first; commit.

Step 2 needs 1; step 3 needs 2 (the kind scan covers `stage_skip`); step 4 needs 2; step 6 needs 4 and 5.

**Phase B — frontend (commit 2).**
1. `event`, `stream`, the model slices and `player` (pure, tested against the fixture).
2. `liveStream`, tested against fakes, with the message contract from A6.
3. Components, ErrorBoundary, `can`.
4. Page, layout, CSS, Project page; `make lint`, `make web-test`, `make web-build`, `make ui-check`.
5. `check_live.py`; `typescript-reviewer` + `react-reviewer` (with an accessibility pass) + `security-reviewer`
   (untrusted rendering); fixes test-first; commit.

Step 2 can run beside step 1; step 3 needs 1; step 4 needs 2 and 3; step 5 needs Phase A and step 4.

**Phase C — acceptance with the owner (commit 3: this plan's record, HANDOFF, MASTER §6/§7/§9, ADR 0003).**
- **Watched live:** on a throwaway review server he presses Run full pipeline (No-AI, auto-approve) and watches in the
  browser pane: cards move in order, frames and the site map grow, tiles fill, gates mark; transport WebSocket.
- **Replay matches:** he reloads and sees the final picture, then Replay from the start, pause, step, scrub, speed and
  Go live end at the same final picture (`check_live.py` checks it too).
- **Cloud:** one Anthropic demo run (decision 7) through the CLI on a demo copy in that server's projects folder; each
  card names its model and cost; the header total equals that run's row on the AI page.
- **Viewer:** the API tests; then a look in the browser pane with a Viewer pass minted for the throwaway review server
  only (decision 2).
- `check_demo` 19/19, 0 extra, after each commit that touches the engine.

## Risks

- **WebSocket through proxies and Cloud Run** (60-min request cap): reconnect from the cursor, SSE fallback. Older
  Safari may not treat `connect-src 'self'` as covering `ws:`; the fallback covers it.
- **TestClient is not uvicorn:** the real-server test and `check_live.py` are mandatory, not optional.
- **Drive I/O:** each stream still reads up to 6 files every 0.5 s (unchanged); the idle check is now one row or one
  stat, and the session list no longer globs ~15 000 screenshots.
- **About 1 000 screenshots per run:** lazy thumbnails, their own bucket, frame swaps capped at 4/s in fast replay,
  a 1-day cache.
- **Immutability vs speed:** the fold copies once per batch, and the budget is measured; a slowdown shows in
  `model.test.ts`.
- **Very long runs:** the browser keeps up to 50 000 events (about 25 MB), then says so; the M1.8 load test (50
  events/s) measures the rest.
- **Event order across workers:** live and replay share one sorted merge, proven by the shuffle test.
- **Duplicate keys and stale markers:** `w:seq` would repeat if a future change ran pytest twice in one session; a stale
  run marker whose pid Windows reuses keeps a CLI run "running" until the 1 h idle limit.
- **Stateless sessions:** signing out does not close an open stream; the 60 s expiry check limits this; real
  revocation needs M2.1's session table.
- **Viewer rule not met by a person yet:** the server enforces it today, a real Viewer signs in only in M2.1.
- **PRD wording:** §7.3's "new kinds" are delivered as phases (ADR 0003).
- **Fixture in the repo:** about 0.4 MB of screenshots of the demo portal (demo data only); the fixture tool's secret
  scan guards it.

## Decisions for the owner

1. **WebSocket library.** Add one small, widely used package (`websockets`) so Live View uses WebSocket first, with
   today's stream as the fallback. *Recommended:* it meets PRD FR-LIVE-7 and stops several open Live View tabs from
   slowing the rest of the app. *Alternative:* keep only today's stream and do WebSocket later.
2. **Viewer read-only.** The server refuses every change from a Viewer, in one place, and tests prove it. You also see
   the Viewer page yourself in the browser pane, on a throwaway test server where I make a one-off Viewer pass (no new
   sign-in code in the product). Real Viewer accounts come with team logins (M2.1). *Recommended.* *Alternatives:*
   tests only; or a temporary second sign-in now (not recommended: code we would throw away).
3. **Engine touch.** Five small additions, none inside an agent: a "skipped" note for skipped stages, a "failed" note
   for failed stages, a "pipeline finished / stopped" note with the list of stages in the run, a "still running" marker
   for command-line runs, one cost line per AI call (never the text sent). No agent behaves differently, and the
   19-bug check must stay 19/0. *Recommended.* *Alternative:* none of them — the board then cannot show skipped or
   failed stages honestly, cards show no cost, and long quiet AI steps look like the end of a run.
4. **Opening a finished run.** Show the final picture with a "Replay from the start" button. *Recommended.*
   *Alternative:* start replaying automatically at 2×, like the old dashboard.
5. **How many recordings to keep.** 15 runs per project (today's setting). Each demo run is about 24 MB of screenshots,
   so about 360 MB synced to Google Drive. *Recommended.* *Alternative:* 10 runs (about 240 MB).
6. **The old dashboard's Live View.** Leave it as it is until M1.4 retires the old dashboard. *Recommended.*
   *Alternative:* point its links to the new page now.
7. **Acceptance spend.** One Cloud demo run (about $0.34; approve up to $1) so model and cost show on the cards, plus
   the free No-AI run. *Recommended.* *Alternative:* No-AI only, and every card then says "no AI".

## Out of scope (named so nobody expects them)

- **M1.4:** the needs-you box, take-over, pause and resume, answering questions, plan approval, defect confirmation,
  visual review and heals in the new UI (FR-LIVE-6).
- **M1.6:** the report's "AI used in this run" section.
- **M1.8:** the 50 events/s load test and the coverage gate.
- **M2.1:** real roles and Viewer sign-in, session revocation, owner-only key pages, hiding "New project" for Viewers.
- **M2.2 / M2.3:** screenshots in cloud storage; Cloud Run WebSocket settings.
- **Also not here:** the stage graph (parallel stages), a retention settings page, `stage_runs.model/cost` columns, the
  old dashboard's duplicate `read_events` (`web/app.py:339-365`, retired with the dashboard in M1.4).

## Verification

To fill after the build.

## Review (fresh context)

To fill after the build.

## Record of changes

To fill after the build.
