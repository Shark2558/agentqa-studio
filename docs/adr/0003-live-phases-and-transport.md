# ADR 0003 — Live View v2: phases instead of new event kinds, WebSocket with SSE, a read-only Viewer

**Date:** 3 Nov 2026 · **Status:** accepted · **Decides:** PRD §7.3 "events are the contract", FR-LIVE-1, 2, 7, 8
(M1.3 Phase A; plan `docs/plans/m1-3-live-view-v2.md`, owner decisions 1–3)

## Context

The Live View shows, for every agent, what it is looking at, what it decided and what happened. PRD §7.3 proposed new
event kinds for this (`thought`, `action`, `result`, `cost`, `waiting`, `model`). The engine already emits 41 kinds from
about 200 `live.emit` / `live.shot` calls in 28 files, and the v0.8 engine is moved, not rewritten. Recordings are
JSON lines plus JPEGs, written by every worker process and read back for live view and replay. The stream was
Server-Sent Events only, its "still running?" check listed every session and counted every screenshot on the event
loop, a crafted cursor raised a 500, and nothing distinguished a person who may only watch.

## Decision

- **Phases are derived, not emitted.** `orchestrator/phases.py` maps each kind (with a few agent-and-kind overrides:
  `srs`/`model` is the Analyst's own step, `writer`/`requirement` is a rewrite) to one of thought · action · result ·
  waiting · lifecycle · meta, and `read_events` adds `phase` to every event as it is read. The files never change, old
  recordings get phases too, and `tests/test_live_phases.py` fails when a source file emits a kind without a phase.
  `model` and `cost` already existed (M1.2) and are "meta": shown on the cards, not as stream rows.
- **Only the run shell gains events, never an agent:** a failed stage (`stage_end`, level bad, the exception's class
  only), a skipped stage (`stage_skip`), the pipeline's own end, the stages a run covers and its pipeline id on its
  start, a `running.json` marker for command-line runs (marked `ended` by the same process at exit; writing it never
  stops or fails a run), and one `ai cost` line per billed model call (figures from the usage row; never the prompt,
  the answer or which key answered).
- **One board** (`orchestrator/board.py`): stages in order, the agent behind each, labels, helpers, the three human
  gates. The command line runs it; the web app draws it (`GET /live/board`).
- **One feed, two transports.** `api/live_feed.py` is the only reader; SSE (kept) and a WebSocket
  (`/live/{session}/ws`, new, needs the `websockets` package) both send its items. The WebSocket route checks for
  itself what the HTTP guards would (sign-in cookie, Origin equal to the host *and port* — a page on another local
  port, such as the demo portal under test, is same-site and gets the Lax cookie — and the rate limit) and refuses
  with a close code after the handshake. Open streams are capped per address and in total across both transports;
  screenshots have their own rate bucket. The browser tries the WebSocket first and falls back to SSE (Phase B).
  The old dashboard's form guard now compares the port too, for the same reason.
- **A Viewer reads, never writes.** One rule in the request guard answers 403 `read_only` to every POST / PUT /
  PATCH / DELETE from a role outside owner and tester, on the API and the old dashboard; sign-in and sign-out stay
  open. Viewer accounts come with team logins (M2.1); the rule is in force from now.

## Consequences

- PRD §7.3's "new kinds" are delivered as phases; agents keep their vocabulary, and a new kind needs one line in the
  phase table (the test says where).
- The demo regression is unaffected by design: no agent's behaviour changed (No-AI run on 3 Nov 2026: 19/19, 0 extra).
- The WebSocket adds a dependency (`websockets` 17.3, BSD-3-Clause, no known vulnerability on OSV on 3 Nov 2026),
  pinned in `requirements.txt` and `deploy/constraints.txt`. Starlette's test client does not prove the real server
  speaks WebSocket, so tests start uvicorn for real (a run streamed, a signed-out socket refused, slots freed when a
  socket or stream is dropped).
- A stream outlives a sign-out by up to a minute (sessions are stateless until M2.1 adds a session table).
- Recordings remain the owner's data and stay out of git; the one exception is the trimmed demo fixture under
  `backend/tests/fixtures/recordings/`, which the tool that writes it and a test that reads it both check for demo
  passwords, unmasked secrets and absolute paths.

## Confirmed in acceptance (Phase C, 4 Nov 2026)

- Both acceptance runs streamed over the WebSocket (`data-transport="websocket"`), the No-AI run started from the
  app (2 720 events) and the Cloud run from the command line (2 774 events); a reload, Replay from the start, pause,
  step, scrub, speed and Final picture all ended at the same final picture. Both runs scored 19/19, 0 extra.
- **"The run is over" has two meanings in the browser**, and Phase C separated them: the recording is finished
  (`runOver`, which drives the player's Final picture) and the picture on screen is that finish (`shownOver`, which
  drives every card, gate and tile). Before the split, a replay of a finished run marked the stage at work "did not
  finish" and the rest "not reached".
- The one-off Viewer pass (signed with the throwaway server's own secret through `Sessions.issue`, no product code)
  watched a finished run live and replayed it; the pages offered no run, project or wizard action, and every write
  tried by hand answered 403 `read_only`.
- A provider switch during a run is recorded only in the gateway's audit log (`ai_events`) and as the key's last
  error: the Live View shows the new model on the card, and that card names only the last model used, with no line
  saying why. Open, with the gateway's classification of Anthropic's "credit balance is too low" (an HTTP 400 read as
  a refused request, so the key stays "ok" and is tried again before every call).
