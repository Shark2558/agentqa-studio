# Plan — M1.3 Live View v2

**Milestone:** M1.3 (PRD §9 Phase 1; §5.4 FR-LIVE-1…8; §7.3 "events are the contract"). PRD acceptance: **a demo run
watched live; its replay matches; a Viewer sees it read-only.**
**Marker:** the PRD does not mark M1.3 🔒, but it is reviewed as if it were: a WebSocket skips the HTTP middleware
(sign-in, rate limit, CSRF guard), the AI client gains a cost event, a new dependency arrives, and a role rule is added to
every write. **Owner approval:** given 3 Nov 2026, all seven decisions as recommended. Planned with the `planner` agent, which
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
| `cli._live_session` | `running.json` {pid, started} in the session folder; at exit the same process adds `ended` (built: the marker is kept, not removed, so a finished run never reads as running; writing it never stops or fails a run) | | CLI runs stay "running" through quiet AI calls |
| `AiClient._on_usage`, after `usage.record` | `ai cost` per billed call | agent_key, tier, scope, provider, model, input/output tokens, cost_usd, estimated, ms, ok. **Never** the prompt, the answer, the key id or the key label; no `state` (budget alerts keep theirs) | Model and cost per card; the recording carries its own costs |

## Transport

| | SSE (kept) | WebSocket (new) |
|---|---|---|
| URL | `GET …/live/{session}/stream?cursor=` | `…/live/{session}/ws?cursor=` (ws: or wss:, following the page) |
| Feed | one async generator `live_feed(p, d, session, cursor)` in `api/live_feed.py`: reads in a thread every 0.5 s, sends batches of at most 2 000 events (only the last batch of a read carries the new cursor, so a reconnect mid-read re-reads instead of skipping), re-checks every 60 s that the sign-in has not expired; a passing read or database error is retried at the next poll | same generator |
| End reasons | `finished` (run over, nothing new) · `idle` (1 h without a word) · `signed-out` · `gone` (the run's folder was pruned) | same |
| Sign-in | router dependency | cookie read through `HTTPConnection`; any signed-in role may watch |
| Cross-site | SameSite=Lax cookie; GET only | **Origin must be present and equal the Host, port included** (cross-site WebSocket hijacking: a page on another local port, such as the demo portal, is same-site, so the Lax cookie *is* sent with its handshake) |
| Limits | general bucket + stream slots | general bucket on the handshake + stream slots: 4 open streams per address across SSE and WS, 64 in total; client messages read and dropped, one over 1 KB closes the socket (1009); uvicorn `ws_max_size` 64 KB |
| Messages | `event: live` {events, cursor} · `event: end` {cursor, reason} | `{"type":"live",…}` · `{"type":"end",…}`, then close 1000; a fault in the feed closes 1011 (logged) |
| Refusals | HTTP 401 / 404 / 422 (cursor over 4 096 chars) / 429 | accept, then close with a code, nothing sent first: 4400 cursor too long · 4401 signed out · 4403 origin · 4404 no such run · 4429 too many requests or streams; every refusal is logged with the address and the Origin (never the cookie) |

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
into `motion.css`, timeline, map, player, lightbox), each ≤ 400 lines. Layout per the mock: three columns
(`300px minmax(0,1fr) 320px`) with Details full width below — **from 1400 px since Phase C** (the sidebar and gutters
take 311 px, so the mock's 1100 px left the middle column 137 px; board + focus from 1024 px, one column below); the timeline and the tab
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

**Confirmed by the owner, 3 Nov 2026: all seven as recommended** — the `websockets` package with SSE as fallback; the
Viewer write rule with tests and a one-off Viewer pass on a throwaway review server; the five event lines and no agent
change; a finished run opens at its final picture; 15 recordings kept; the old dashboard's Live View left alone until
M1.4; one Cloud demo run (about $0.34, up to $1 approved) plus the free No-AI run.

The seven as they were put to him:

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

**Phase A (backend, transport, events), 3 Nov 2026, on branch `claude/exciting-margulis-b91a03`.**

| Check | Result |
|---|---|
| `python -m pytest -q tests` (from `backend/`) | **476 passed** (339 at hand-off; 436 before the review fixes); every new test written RED first |
| `python -m pyflakes agentqa tools tests` | clean |
| Demo regression in No-AI mode (fresh demo copy, `pipeline --policy srs_wins --auto-approve`, then `tools/check_demo.py`) | **19/19 seeded bugs, 0 unexpected**, twice: before the review fixes (21:52) and after them on a fresh copy (22:36–22:42) |
| The regression's own recording | the pipeline's start line lists its 12 stages and its `pl-…` id; the questions gate; "Pipeline finished" (level ok) as the last line; no `cost` lines (No-AI makes no billed call); after the fixes the run marker read `{"pid", "started", "ended"}` |
| Real uvicorn + `websockets` client (`test_live_ws_real_server.py`) | a run streamed over a WebSocket and closed 1000; a signed-out socket closed 4401; a socket dropped without a closing handshake and an SSE stream closed early both freed their slot |
| `websockets` 17.3 (released 19 Oct 2026; 17.4 was four days old) | BSD-3-Clause; OSV lists no known vulnerability (3 Nov 2026); `pip-audit` runs in CI (`agentqa-selftest.yml`), not installed on this PC |
| Sizes | new files 46–249 lines; `cli.py` 778 (723 before; ceiling 800); `create_app` now under 50 lines (it was over before Phase A); the only functions over 50 lines are the pre-existing `cli._stage` and `cli.build_parser` |

Plan-vs-build differences worth knowing:
- The fixture lives in `backend/tests/fixtures/recordings/` (the backend `.gitignore` keeps every `live/` folder,
  `*.jsonl` and `shots/` out of git; one narrow exception admits only this folder). `expected-summary.json` moves to
  Phase B: it describes the browser's model, which Phase B builds. The fixture is 447 events in 4 worker files with 12
  screenshots (330 KB); absolute paths are cut to the part inside the project.
- The run marker is kept at exit and marked `ended` instead of being removed (a removed marker fell back to the
  8-second rule, so a finished run read as running for a few seconds); writing it never stops or fails a run.
- `is_running` reads one row with a bare query; the live routes and the socket open no project store at all
  (`projects.find_project`).
- A path that escapes the live folder never reaches the socket's handler (no route matches), so it is refused at the
  handshake rather than with 4404; the folder guard itself is tested directly. Close codes 4400 (cursor too long),
  1009 (message too big) and 1011 (fault in the feed) were added; the end reasons are listed in the Transport table.
- The plan's "`cmd_pipeline` is under 50 lines" check is a review item, not a test.
- Two pieces are not in the plan and were added for the review: the old dashboard's form guard now compares the port
  (security review F1), and a project address with `user:password@` is written to the live view without it.

**Phase B (the React Live View), 3–4 Nov 2026, on branch `claude/gifted-ishizaka-972db8`** (B1, the pure model, was
committed first as `b02ec86`; B2 and the review fixes are the Phase B commit).

| Check | Result |
|---|---|
| Vitest (`bash frontend/local-node.sh test -- --run`) | **268 passed in 34 files**; every new test written RED first (the v1 page's tests went with the v1 files) |
| `run typecheck` · `run lint` (oxlint) | clean · clean |
| `run build` | JS 528 kB (**153.6 kB gzip**, budget 300 kB; Vite's 500 kB-unzipped note only), CSS 75 kB (23.7 kB gzip) |
| `make lint` (contrast) | **232 of 232** (56 pairs × 2 themes × 5 accents): the Live View's status ink on cards and sunken frames, ids and headings on sunken panels and the empty tile's icon were added as pairs |
| `make ui-check` | passes at 320 / 375 / 768 / 1024 / 1200 / 1440 px, light and dark, with a new `live-run` page (the fixture as a finished session of a second throwaway project, so "No run yet" stays measured); the timeline, tabs and wide tables stay inside their cards |
| `make live-check` (new, `check_live.py`) | the fixture appended in 40 timed chunks to a new command-line session with a run marker: **447 / 447 watched live over WebSocket**, the expected final picture (12 cards Done, 14 / 10 / 3 tiles, $0.1249, gates 15 / approved / 19), and the same picture after a reload, after Replay from the start at Instant, and with WebSocket refused before it opens (→ `data-transport="sse"`) |
| Backend `python -m pytest -q tests` · `pyflakes` | **477 passed** · clean (Phase B touches no engine code; one contrast-count test follows the new pairs) |
| A look in a real browser (screenshots of the live-run page at 1440 / 900 / 375, light and dark) | three things fixed from it: the Findings column made the page 6 240 px tall (now it scrolls in its card: 3 233 px), an empty screen was a full 16:9 blank, and "finished" wrapped onto its own line on a phone |
| Sizes | every Phase B file 7–285 lines (`board.ts` the largest); no function over 50 lines (`connectLive`, `Live` and `useLive` were split for the review) |

Plan-vs-build differences worth knowing:
- `liveStream.ts` became `lib/live/connect.ts` (the v1 file stayed until the v1 page went), and the hook is
  `useLive.ts`; the "new-run banner" became something simpler: the run list is invalidated when a run starts, re-read
  every 3 s for a minute while the address names a run not listed yet (a notice says so; another run is never shown
  in its place), and every 15 s while a run is going.
- Past 50 000 events the oldest go in whole blocks of 500 and the checkpoint at that boundary becomes the new start,
  so every total stays exact (a 52 000-event test checks calls and cost); the replay keeps the newest 50 000.
- Only an end that says "finished" makes the run over. "No news for an hour" (a run waiting at a gate, or one that
  died) shows a notice with **Check again**; a sign-in that ended or a run that is gone shows an alert; none of them
  marks a stage "did not finish".
- The 4-per-second cap on frame swaps was not needed: at Instant the player moves 600 events per step and draws once.

**Phase C (acceptance with the owner), 4 Nov 2026, on branch `claude/gifted-ishizaka-972db8`.** A throwaway review
server (generated owner, `AGENTQA_HOME` and `--projects-dir` in the session's scratchpad, port 52381, the owner's own
sign-in never touched), the demo portals on 8800 / 8810, the owner watching the browser pane.

| Check | Result |
|---|---|
| **Watched live, No-AI** (Run full pipeline from the project page, gates approved automatically) | the cards went Queued → Running → Done in order; the gates marked (Questions for you: 15 · Test plan approval: approved · Defects to confirm: 19); browser frames, the 35-screen site map (with `/help/faq` HTTP 404) and the 214 tiles filled while the Executor ran; `data-transport="websocket"`; 2 720 events, 01:20–01:27 |
| `tools/check_demo.py` on that run | **19/19 seeded bugs, 0 unexpected** |
| **Replay matches** | after a reload the same final picture (pipeline, 12 cards, tiles, findings compared as text); Replay from the start, Pause (222 stays 222), Next step (222 → 223), scrub to 1 500, 10× (1 500 → 1 550 in 3 s), Final picture: the same final picture again. Partway through, the board was wrong (C1, fixed) |
| **Cloud run** (decision 7; the owner said yes in chat right before it spent; project cap $1.00) | `pipeline --policy srs_wins --auto-approve` from the command line on a demo copy in the server's projects folder, the owner's real vault; 2 774 events over WebSocket, 12 / 12 stages, **19/19, 0 unexpected**; each AI card named its model and cost (Analyst claude-sonnet-5-5 $0.0129 · Writer $0.2398 · Test Designer $0.0185 · Triage $0.0017; the rest "no AI"), their sum is the header's **$0.2729 · 20 338 in / 21 969 out tokens**, and the AI page's run row `pl-20261104-014148` reads 35 calls, $0.27 (API $0.2728893, the same tokens). **Spent: $0.27** of the $1 approved |
| Anthropic credit ran out mid-run | after 5 Sonnet and 3 Opus calls Anthropic answered HTTP 400 "Your credit balance is too low"; the gateway switched each later call to Gemini (gemini-flash-lite-latest) as the policy says, and the run went on. The owner tops up Anthropic himself if he wants it back. Two findings (C4, C5) |
| **Viewer look** (decision 2; a one-off pass signed with the throwaway server's secret through `Sessions.issue`, role viewer, 1 hour) | Projects and the Live picker: no Try the demo, no New project; the project page: no Run full pipeline and no gate switch; the wizard: "Viewers can watch runs and read results…"; the finished Cloud run watched over WebSocket and replayed; writes sent by hand — start a run, create the demo, change AI, new project — all **403 `read_only`** |
| B19 (a half-open socket after the computer sleeps) | not observed: the PC did not sleep during the acceptance; stays open |
| After the fixes and the review fixes: Vitest · typecheck · lint · build | **275 passed in 34 files** (+7: the page test and the player tests RED first; the hook's `shownOver` cases and the live-edge case added as guards after the review) · clean · clean · built |
| The same replay on the real No-AI recording after the fixes | at 38 / 2 720 "analyze: Running", every later stage "Queued", nothing says "did not finish"; at the end "Final picture" and the Play button reads "Play from the start" |
| `make lint` (contrast) · pyflakes | 232 / 232 · clean (backend, `check_app.py`, `check_live.py`) |
| `make ui-check` | passes at 6 widths, light and dark, with a new check that the Live View's middle column exists on the recorded run and is at least 360 px whenever it shares its row: **RED on the old build** (196 px at 768, 252 px at 1200), green after the fix |
| `make live-check` | 447 / 447 live over WebSocket; the same picture after a reload, after Replay at Instant and over SSE |
| Backend | no backend change in Phase C (477 passed at Phase B) |

## Review (fresh context)

**Phase A.** Three reviewers read the uncommitted change set in fresh contexts on 3 Nov 2026: `ecc:code-reviewer`
(Approve: 3 MEDIUM, 7 LOW), `ecc:python-reviewer` (Block: 1 HIGH, 10 MEDIUM, several LOW) and `ecc:security-reviewer`
(Approve with warning: 1 MEDIUM, 4 LOW, 2 INFO; it found nothing sensitive in the fixture apart from three absolute
paths). Every HIGH and MEDIUM was fixed test-first (40 new test cases, 436 → 476, and four rewritten to the new
behaviour); the LOWs marked "open" are recorded.

| # | Severity | Finding (reviewer) | Fix |
|---|---|---|---|
| 1 | HIGH | The run marker's removal sat unguarded in `main()`'s `finally`: on Windows a reader holding `running.json` open makes it raise, masking the real error and leaving a finished job "running"; a failed marker write aborted the run (python, code) | marker writes are atomic (temp file + replace, retried) and never raise; at exit the marker is marked `ended`, never removed; tests for both failures |
| 2 | MEDIUM | The old dashboard's cross-site check compared the host only: a page on another local port (the demo portal under test) could post its forms while the owner is signed in (security F1) | one `origin_matches_host` (host and port; a malformed address is refused) for the dashboard and the socket; test with another port, a Referer and a broken Origin |
| 3 | MEDIUM | `is_running` and every screenshot / socket opened the full project store (schema set-up each time) on the half-second poll (code, python) | one bare query for the job row; `find_project` for folders only; tests that the store is never opened |
| 4 | MEDIUM | No test proved a slot is freed when a stream ends badly (code) | a failing feed (SSE and socket), a socket left mid-run, and on real uvicorn a dropped socket and an early-closed SSE stream |
| 5 | MEDIUM | Any read error ended a stream as "gone"; any other error while checking killed it (python, code) | only a missing folder is "gone"; a busy file or a locked database is logged and retried; tests |
| 6 | MEDIUM | The socket swallowed feed faults as if the browser had left; the slot release came after two awaits; the final close could raise (python, code) | release in the outermost `finally`; a feed fault is logged and closes 1011; the close is guarded; test |
| 7 | MEDIUM | A marker with an impossible pid (2^40) raised out of the Windows pid check, breaking the session list (python, security) | pids outside 1…2^31−1 are not alive, in the marker reader and in `pid_alive`; tests |
| 8 | MEDIUM | `json.dumps` of big batches ran on the event loop; one read could become one huge frame (python) | at most 2 000 events per message (only the last carries the new cursor); encoding in a worker thread; test |
| 9 | MEDIUM | The fixture tool could delete its own source (`--out` = the recording), found passwords by pattern (fail-open) and scanned top-level fields only (python) | it only replaces a folder that is itself a fixture; passwords parsed from YAML (refuses when none); nested fields and absolute paths scanned; a test reads the committed fixture every run |
| 10 | MEDIUM | A malformed Origin raised in the socket's check (python, code) | refused as another site; test |
| 11 | LOW | Absolute paths of the owner's folders in the fixture (security F3) | cut to the part inside the project; regenerated |
| 12 | LOW | `base_url` with `user:password@` would reach the live view (security F4) | stripped before the start line; test |
| 13 | LOW | Socket refusals left no log line (security F5) | logged with the address and the Origin, never the cookie |
| 14 | LOW | Idle time counted polls, not time; symlinks followed; a folder pruned mid-listing broke the list; outcome strings; `GATES` mutable; `create_app` over 50 lines; the docstring's "Lax cookies on a cross-site handshake" was wrong (python, code, security) | monotonic clock; symlinks refused; pruned folders skipped; constants; read-only gates; guard extracted; wording corrected (same-site, another port) |
| 15 | LOW · **open** | After a hard crash, a stale marker whose pid Windows has reused reads "running" until the 1-hour idle limit (python, security) | no heartbeat yet; revisit with the scheduler (M1.5) |
| 16 | LOW · **open** | `routes_projects` / `open_or_404` callers and some older tests never close their store (python; pre-existing) | the new live routes and tests use `find_project`; the rest when M1.4 rewrites those pages |
| 17 | LOW · **open** | The old dashboard's own `live_events` keeps an unvalidated cursor (security F6) | retired with the dashboard in M1.4 |
| 18 | LOW · **open** | Sessions are stateless: an open stream outlives a sign-out by up to 60 s, and a stolen cookie works after logout (security F7) | M2.1 session table |
| 19 | LOW · **open** | Project creation still accepts `user:password@` in the address (security F4) | the live view strips it now; refuse it at creation in M1.4 |
| 20 | LOW · **open** | `cli.py` is 778 lines: the pipeline runner's helpers stay there until the orchestrator becomes a service (code) | moving them now would need `cli.stage` passed in; M1.5 |
| 21 | LOW · **open** | Test set-up repeated across files; the fixture's 447 is a literal in several tests; a check-then-update race in `jobs._still_alive` (code, python; the race pre-dates M1.3) | consolidate in `conftest` with Phase B; the race with the scheduler (M1.5) |
| 22 | LOW · fixed in B | `frontend/src/lib/api.ts` still types `LiveSession.shots` (code) | `shots` optional, `has_events` added |

**Phase B.** Three reviewers read the whole Phase B change set (B1's model and B2's page) in fresh contexts on 3–4 Nov
2026: `ecc:typescript-reviewer` (Block: 2 HIGH, 7 MEDIUM, LOWs), `ecc:react-reviewer` with an accessibility pass
(Block: 5 HIGH, 9 MEDIUM, LOWs) and `ecc:security-reviewer` (no CRITICAL; 1 HIGH, 3 MEDIUM, 4 LOW; text-only rendering,
screenshot names, prototype keys and the Viewer gating all verified clean). Overlapping findings are merged below.
Every HIGH and MEDIUM was fixed test-first (Vitest 214 → 268).

| # | Severity | Finding (reviewer) | Fix |
|---|---|---|---|
| B1 | HIGH | Past 50 000 events the oldest were cut and everything refolded from empty on every batch: finished stages read "not reached", cost and tokens were undercounted, the replay position drifted (ts) | eviction in blocks of 500 with the boundary checkpoint as the new start; the position shifts with it; a 52 000-event test |
| B2 | HIGH | Any end counted as "run over": an hour without news (a run waiting at the plan gate), a sign-in that ended, a run that is gone or an unknown reason marked running stages "did not finish"; 4401 / 4404 showed no alert (ts) | only "finished" is over; an unknown reason reads "idle"; notices and alerts for each; **Check again** reconnects; tests |
| B3 | HIGH | Replay froze while a run was still streaming: each batch restarted the pause (react, ts) | the step waits on the event shown and on whether a next one exists; the pause follows the event just shown, as in the v0.8 player; test |
| B4 | HIGH | The enlarged screenshot pulled focus back and forth on every batch; focus did not return in Safari; the page behind was not inert (react, ts) | it mounts once per opening with its handlers in a ref; the opener comes from the click; a portal and `inert` on the page; tests |
| B5 | HIGH | The `pos / total` counter was a polite live region that changed on every event (react) | plain text; a separate status says Following live / Playing / Paused / Final picture; the slider has `aria-valuetext`; test |
| B6 | HIGH | The site map had no text alternative beyond counts (react) | a table of the screens (who reached them, their answer) under the map; test |
| B7 | HIGH | The event list stayed at the top while new rows arrived below (react) | it follows the newest row while the reader is at the bottom and stays put once they scroll up; test |
| B8 | HIGH | Nothing bounded what a hostile application could send: megabyte URLs, invented agents, workers and paths, quadratic copies, a slow `nodeid` pattern (security H1) | `toEvent` cuts text (titles 500, previews 20 000, the rest 2 000, names 64), lists and objects to 200 items and 3 levels, and times outside 0–4·10⁹ s; caps on cards 40, tiles 2 000, frames 32, screens 300, code files 200, requirements 2 000 with 50 items each, statuses 20, assists 200, marked words 20; a one-pass test-file reader; tests |
| B9 | MEDIUM | Reconnects never stopped: SSE errors (401 / 404 / 429 hidden by EventSource) and socket codes 4400 / 4403 / 1011 retried every 3 s forever; one blip pinned the tab to SSE (security M1, ts) | 3 s doubling to a minute with jitter, then "connection lost" after eight; 4403 → SSE; 4400 / 1008 / 1009 stop; after an SSE error the events endpoint is asked once why; SSE is remembered only after it has worked; tests |
| B10 | MEDIUM | One malformed event could blank the whole page, and a broken panel never came back; an out-of-range time broke every clock (security M2, ts, react) | the fold skips and counts an event that throws (the page says how many); plain values only in rule and table text; times bounded; a boundary around the whole run and a reset key on each panel; tests |
| B11 | MEDIUM | Findings stopped at 500 of any kind, so exploratory notes could push out defects; a status named `__proto__` vanished (security M3, ts) | caps per kind with "N more not shown"; rule counts in a `Map`; tests |
| B12 | MEDIUM | The run was chosen from a list that might still be loading or stale; an address naming an unlisted run silently showed another; the list was never re-read (ts, react, security L1) | the run mounts only when listed after a fresh read; a notice while waiting; the list invalidated on start and polled; run ids checked before they enter a URL; tests |
| B13 | MEDIUM | A Viewer was still offered Try the demo, New project and the wizard's Run (ts) | hidden on Projects, the Live picker and the empty list; the wizard shows a notice instead; tests |
| B14 | MEDIUM | Per-event work over every event and a `memo` that never held (react, ts) | rows memoised, rows and cards memoised on what they show, the reducer memoised, Activity reads only while open |
| B15 | MEDIUM | "Show earlier" grew without end and kept its length across agents (react) | capped at 3 000 rows and reset for each agent |
| B16 | MEDIUM | A test's failure message was only in a mouse tooltip (react) | a list of the tests that did not pass, with their messages; test |
| B17 | MEDIUM | `?agent=` was not checked; connection loss was not announced; headings and tab wiring; scrolling wrappers out of keyboard reach (react) | falls back to the running agent; a status role and notices; a Details heading, `aria-controls` only on the chosen tab, a focusable panel; scrolling regions focusable; tests |
| B18 | LOW | "N of M stages done" counted failed and skipped stages; negative costs and alerts; huge depths and viewports; unlabelled watch links; the run id raw in an address; unused `initialPlayer` (react, ts, security) | "12 of 12 stages finished · 1 failed"; values clamped; links labelled and ids encoded; `initialPlayer` now opens a finished run |
| B19 | LOW · **open** | A half-open socket after the computer sleeps keeps saying "live" (no keepalive) (ts) | watch in Phase C; the reconnect covers a closed socket |
| B20 | LOW · **open** | Event keys are worker + sequence: a second process writing the same worker file in one folder would have its events dropped (security L3) | not in today's pipeline (each run writes its own folder); add a process id if that changes |
| B21 | LOW · **open** | The browser checks' throwaway server still reads other keys from `backend/.env` (an `AGENTQA_COOKIE_SECURE=1` there would break their sign-in; nothing leaks: the generated owner and key win) (security L4) | a no-dotenv switch for the throwaway server |
| B22 | LOW · **open** | Agent cards use `aria-pressed` for the followed agent too; the lightbox has no backdrop click; "Approve the gates automatically" defaults on (react) | the default is the M1.2 decision until M1.4 brings the gates into this app; the rest with M1.4's page polish |

**Phase C.** What the acceptance runs found (C1–C7), fixed test-first where it is the Live View's own code; the fixes
were then read by `ecc:code-reviewer` (Approve: 2 MEDIUM, 6 LOW) and `ecc:typescript-reviewer` with React and
accessibility in mind (no CRITICAL or HIGH: 3 MEDIUM, 6 LOW) in fresh contexts; overlapping findings are merged in
C8–C15, and every MEDIUM was fixed test-first.

| # | Severity | Finding (where seen) | Fix |
|---|---|---|---|
| C1 | HIGH · fixed | Partway through a replay of a finished run, the stage at work read "Did not finish" and every later stage "Not reached" (No-AI replay at 38 / 2 720): every panel used "the recording is finished" | `useLive` also returns `shownOver` (finished **and** the picture is at the last event); pipeline, board, focus and tiles use it, the player keeps `runOver`; `Live.test.tsx` scrubs the fixture to 30 / 447 |
| C2 | MEDIUM · fixed | "What it is doing" was 186 px wide in the owner's 1 149 px pane (137 px at 1 100, 196 px at 768): the column breakpoints ignored the 311 px of sidebar and gutters | one column under 1 024 px, board + focus from 1 024, three columns from 1 400 (the middle column ≥ 437 px beside another); `check_app.py` checks ≥ 360 px |
| C3 | LOW · fixed | At the end of a finished run after Final picture (or a replay played to its end) the screen-reader status said "Playing" and the button offered Pause | "Final picture"; Play is disabled at the end (Replay from the start is the way back); `PlayerBar.test.tsx` |
| C4 | MEDIUM · **open** | A provider switch leaves no line in the Live View, and a card names only the last model used: the Writer's card read gemini-flash-lite-latest although about $0.23 of its $0.24 was Opus 5.5 (Cloud run) | a "switched" line from the gateway into the live recording and every model on the card; a follow-up (it touches the gateway, 🔒) |
| C5 | MEDIUM · **open** (M1.2 gateway) | Anthropic's "credit balance is too low" arrives as HTTP 400 and `ai/providers.classify` reads it as `bad_request`, so the empty key stays "ok" and is tried before every call (27 failures in a row in `key_state`) | classify it as `billing` (never retried until the key is edited); a follow-up with its own test and security review |
| C6 | LOW · **open** | The run picker's time is the run folder's last change, not its start (01:20 became 01:24 while the run went on; the header kept 01:20) | read the start from the run marker or the first event (M1.4) |
| C7 | LOW · **open** | The site map draws children that share their parent's column (`@department/…`) with short diagonal hatches between stacked boxes | place children one column to the right (M1.4 polish) |
| C8 | MEDIUM · fixed | C3's first fix disabled Play at the end, under a keyboard user's focus, so focus fell back to the page (ts) | at the end Play reads "Play from the start" and starts the replay again; never disabled there; test |
| C9 | MEDIUM · fixed | A recording that ended without finishing (idle, signed out, gone) still said "Playing" at its end (ts) | the player takes the stream's end reason: any ended stream at its last event is the end ("End of what was recorded"; "Final picture" when it finished); tests, with the live edge of a run still streaming pinned as "Playing" |
| C10 | MEDIUM · fixed | `shownOver`'s true side had no test, and the width check passed silently when there was no middle column to measure (code, ts) | hook cases (finished at its end, scrubbed back, still streaming, idle); `check_app.py` requires the column on the recorded run |
| C11 | LOW · fixed | The "311 px" comment hid a 15 px scrollbar (296 px without one, as in headless checks); who reads `shownOver`; the check's docstring and success line; "at the end" worked out twice in the player (code, ts) | worded out; computed once |
| C12 | LOW · **open** | The design mock still switches at 1 100 px; 1 400 px is not a measured width; other grids also ignore the sidebar (`.g-dash` gives four ~185 px columns at 1 100 px) and three breakpoint conventions now exist (760 / 1 100, 1 300, 1 024 / 1 400) (code) | M1.4 page polish, with the mock |
| C13 | LOW · **open** | Under 1 024 px "what it is doing" sits under the board, so choosing an agent changes content out of sight (ts) | scroll it into view on choice when the grid is one column (M1.4) |
| C14 | LOW · **open** | At the final picture of a run whose stage never ended, the board's spoken status says "X: running" while the card says "Did not finish" (pre-existing) (ts) | `running && !shownOver` (M1.4) |
| C15 | LOW · **open** | Four panels still name their prop `runOver` while receiving `shownOver`; "Next step" and "Go live" still disable under focus (pre-existing) (ts) | rename and refocus with M1.4's page work |

## Record of changes

**Phase A — one commit on `claude/exciting-margulis-b91a03`, 3 Nov 2026.**

New: `backend/agentqa/orchestrator/{board,phases}.py`, `backend/agentqa/api/{live_feed,routes_live_ws}.py`,
`backend/tools/make_live_fixture.py`, `backend/tests/fixtures/recordings/cli-fixture-pipeline/` (4 event files,
12 screenshots), `frontend/src/test-fixtures/live-demo.json`, `docs/adr/0003-live-phases-and-transport.md`, tests
`test_live_board`, `test_live_phases`, `test_live_running`, `test_live_cursor`, `test_live_run_events`,
`test_live_feed`, `test_api_live_ws`, `test_live_ws_real_server`, `test_api_roles`, `test_live_fixture`.

Changed: `orchestrator/live.py` (phase on read, checked cursor, one-run `is_running`, run marker, robust listing),
`orchestrator/jobs.py` (`job_running`, `peek`, `process_alive`, possible pids only), `orchestrator/projects.py`
(`find_project`), `api/routes_live.py` (board, shared feed, slots, no store), `api/__init__.py` (guards extracted,
screenshot bucket, Viewer rule, socket router, dashboard origin with port), `api/auth.py` (`HTTPConnection`,
`WRITE_ROLES`, `read_only_refusal`, `signed_in_check`, `origin_matches_host`), `api/settings.py` (three limits),
`ai/client.py` (per-call `cost` line), `cli.py` (board, run-shell events, `cmd_pipeline` split, marker, `ws_max_size`,
no userinfo), `backend/requirements.txt` and `deploy/constraints.txt` (`websockets`), `backend/.gitignore` (the fixture
exception), tests `test_ai_client.py` and `test_api_hardening.py` (added to, nothing weakened). No agent changed.

Left for Phase B: the React Live View itself (the page, components, model, player, WebSocket-then-SSE client,
`expected-summary.json`, `check_app.py` and `check_live.py`); Phase C: the acceptance runs with the owner.

**Phase B — two commits on `claude/gifted-ishizaka-972db8`, 3–4 Nov 2026** (`b02ec86` the pure model; then the page).

New: `frontend/src/lib/live/{event,stream,board,lanes,panels,siteMap,model,player,connect,useLive}.ts` with their
tests, `lib/can.ts`, `components/ErrorBoundary.tsx`, `components/live/{AgentBoard,LiveHeader,AgentFocus,
TestsAndFindings,DetailsTabs,SiteMapPanel,PlayerBar}.tsx`, `pages/LiveRun.tsx`, `styles/live-frame.css`,
`test-fixtures/{live.ts,live-board.json,live-expected-summary.json,fakeSocket.ts}`, `backend/tools/live_fixture_summary.py`
(the independent count behind the expected summary), `frontend/design-system/check_live.py` and `make live-check`,
tests `ErrorBoundary`, `AgentFocus`, `DetailsTabs`, `PlayerBar`, `TestsAndFindings`, `Projects`, `useLive`.

Changed: `pages/Live.tsx` (rewritten), `pages/{Project,Projects,LivePicker}.tsx` and `pages/wizard/NewProject.tsx`
(the Viewer rule; the run list refreshed on start; ids encoded), `components/ProjectList.tsx` (`mayCreate`),
`lib/api.ts` (`liveBoard`, `shotUrl`, `LiveSession`), `styles/{live,motion,components}.css` and `styles.css` (the
three-column layout from 1 100 px, the scan line), `vite.config.ts` (the dev proxy carries the socket),
`design-system/check_app.py` (the live-run page), `design-system/check_contrast.py` (ten pairs) and its test,
`backend/tests/test_live_board.py` (the frontend's copy of the board is the board). Removed: the v1 `lib/live.ts`,
`lib/liveStream.ts`, `components/live/{AgentCard,EventRow}.tsx` and their tests. No agent and no engine code changed.

Left for Phase C: the acceptance runs with the owner (a No-AI run watched live and replayed in the browser pane, one
Cloud run up to $1, a look as a Viewer on a throwaway review server), then HANDOFF, MASTER §6/§7/§9 and ADR 0003.

**Phase C — one commit on `claude/gifted-ishizaka-972db8`, 4 Nov 2026.** Acceptance with the owner (above) and its
fixes. Changed: `lib/live/useLive.ts` (`shownOver`), `pages/LiveRun.tsx` (the panels read it), `components/live/
PlayerBar.tsx` (takes the stream's end reason; the end of a recording, Play from the start), `styles/components.css`
and `styles/live.css` (the Live View columns from 1 024 / 1 400 px), `design-system/check_app.py` (the middle-column
check), tests `Live.test.tsx`, `PlayerBar.test.tsx` and `useLive.test.tsx`; this plan, `docs/HANDOFF.md`,
`frontend/design-system/MASTER.md` §6/§7/§9 and ADR 0003. No
engine, agent or backend code changed. Spent: $0.27 (the Cloud run). Not merged into `main`: the owner decides.
