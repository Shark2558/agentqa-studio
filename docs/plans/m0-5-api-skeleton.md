# Plan — M0.5 API skeleton + React scaffold 🔒

**Milestone:** M0.5 (PRD §9, Phase 0; PRD §7.4 API surface, D9). **Marker:** 🔒 — authentication, job execution and
the first network surface of the new product. **Owner approval:** required before building (asked 3 Nov 2026).

## Goal

The first slice of the new product: a versioned JSON API (`/api/v1`) in front of the existing engine, with sign-in,
projects, runs and the live event stream, plus the React + TypeScript app shell built from the M0.4 design system.
Acceptance (PRD): **sign in → create a project → start the demo run → watch its events in a bare React page.**

## What is built

### Backend — `backend/agentqa/api/` (new package, FastAPI, mounted beside the old dashboard)

| Area | Endpoints (all under `/api/v1`) | Notes |
|---|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | **One owner account for now** (email + password from environment: `AGENTQA_OWNER_EMAIL`, `AGENTQA_OWNER_PASSWORD_HASH` (argon2)); signed `HttpOnly; SameSite=Lax` session cookie (itsdangerous, 12 h); CSRF guard: every state-changing call must send `X-Requested-With: AgentQA`; login rate-limited (5 tries / 15 min per IP). The users table, roles and memberships are M2.1 and plug into the same `current_user` dependency. |
| Projects | `GET /projects`, `POST /projects` (name, url), `GET /projects/{slug}`, `POST /projects/demo` | Reuses `init_project`, the demo copier and the project summary the old dashboard computes. Slugs validated; path traversal impossible (resolved against the projects dir). |
| Runs | `POST /projects/{slug}/runs` (scope: `pipeline`, a single stage, `continue`; options policy / auto-approve), `GET /projects/{slug}/runs`, `GET /projects/{slug}/runs/{id}`, `GET /projects/{slug}/runs/{id}/log` | One running job per project (409 otherwise). Spawns the same `python -m agentqa … --job-id` subprocess the dashboard does. |
| Live | `GET /projects/{slug}/live/sessions`, `GET /projects/{slug}/live/{session}/events?cursor=`, `GET /projects/{slug}/live/{session}/stream` (SSE), `GET /projects/{slug}/live/{session}/shots/{name}` | The JSONL reader the dashboard has, exposed as JSON and as Server-Sent Events (WebSocket in M1.3 when the UI needs bidirectional take-over). |
| Meta | `GET /api/v1/health`, `GET /api/v1/openapi.json`, `/api/v1/docs` | Health is unauthenticated; docs are gated behind sign-in. |

**Engine refactor (move, not rewrite):** `_spawn`, `_running`, `_pid_alive`, `_sessions`, `_session_dir`, `_projects`,
`_open` move out of `web/app.py` into `agentqa/orchestrator/jobs.py` and `agentqa/orchestrator/live.py`; the old
dashboard imports them from there, so it keeps working unchanged (demo regression proves it). This is the start of
the Orchestrator service the PRD describes (§7.3).

**API conventions (ECC patterns.md):** one response envelope `{"ok": true, "data": …}` / `{"ok": false, "error":
{"code", "message"}}`; Pydantic v2 schemas at the boundary; rate limiting on every endpoint (simple in-process token
bucket now, Redis later); errors never leak paths or stack traces; sign-in attempts logged (outcome + client address,
never the password) — a full structured access log is M2.x.

### Frontend — `frontend/` (React 19 + TypeScript + Vite)

- Scaffold: Vite, React Router, TanStack Query for server state, `tokens.css` from M0.4 as the only styling source,
  fonts **bundled locally** (IBM Plex Sans, JetBrains Mono — OFL), Phosphor icons (`@phosphor-icons/react`).
- Pages for this milestone (deliberately bare, styled only by the tokens and the shell recipes): **Sign in**,
  **Projects** (list + create + "Try the demo"), **Project** (summary + "Run full pipeline" button), **Live** (agent
  board + event stream over SSE). The full Live View v2 and the onboarding wizard are M1.x.
- Vite dev server proxies `/api` to the backend; the production build is copied into the backend image
  (`/srv/frontend`) and served by FastAPI at `/app` (the old dashboard stays at `/` until M1.4 replaces it).
- Tooling: oxlint + Prettier + `tsc -b`; Vitest (+ Testing Library) for unit tests; Playwright for the acceptance flow.

## Tests first

- Backend (pytest, `backend/tests/test_api_*.py`): auth (wrong password → 401 + rate limit after 5; session cookie
  attributes; CSRF header required; `/me`); projects (create, slug collision, traversal attempt `../x` → 404, demo
  creation); runs (spawn is mocked to a fake process → 202 with id; second start → 409; status transitions; log tail);
  live (events cursor paging over a temp session dir; SSE yields events then closes when the run ends; shot path
  traversal → 404); envelope shape on every error; health unauthenticated, everything else 401 when signed out.
- Frontend (Vitest): sign-in form validation, API client envelope handling, event reducer for the live page.
- Acceptance (Playwright, `frontend/e2e/acceptance.spec.ts`): against the real backend and the demo portal — sign
  in, create the demo project, start the pipeline, see ≥ 1 live event appear on the Live page.

## Out of scope

Users table / roles (M2.1), onboarding wizard (M1.1), AI mode UI (M1.2), full Live View v2 (M1.3), gates (M1.4),
scheduler (M1.5), WebSocket, replacing the old dashboard.

## Decisions to confirm with the owner (this is the 🔒 gate)

1. **One owner login from environment for now** (users table in M2.1) — acceptable?
2. **Session cookie + CSRF header** (no OAuth yet; Google sign-in is M2.5) — acceptable?
3. **Old dashboard keeps running at `/`**, new app grows at `/app` until it replaces it — acceptable?
4. New dependencies: backend `argon2-cffi`, `sse-starlette`; frontend React/Vite/TanStack/Phosphor/ESLint/Vitest/
   Playwright (all MIT/OFL). The repo gains `node_modules` (git-ignored) under `frontend/`.

## Risks

- Google Drive + `node_modules`: thousands of small files sync slowly. Mitigation: `frontend/node_modules` is
  git-ignored and Vite is fast anyway; if Drive sync becomes a problem, move the checkout (ADR 0001 already allows it).
- Extracting helpers from `web/app.py` could change dashboard behaviour: the demo regression (19/19) is the guard.
- Windows subprocess handling (`PROCS`, `_pid_alive`) is reused as-is; the API process must be the one that spawned a
  job to see its handle, same as today.

## Verification (3 Nov 2026)

- Backend: `pytest` **115 passed** (89 before + 22 API + 4 web) at acceptance, **128** after the review fixes; lint
  clean. Frontend: `tsc -b` clean, Vitest 6 passed (10 after the review), production build 339 kB JS / 47 kB CSS
  (gzip 104 / 19 kB), fonts bundled.
- **Acceptance met, watched in the browser pane:** owner created the sign-in with `owner-set` in his own terminal →
  signed in at `http://127.0.0.1:8710/app/` → Projects page listed the demo and a project he had created himself →
  opened the demo → "Run full pipeline" → the Live page streamed events over SSE: srs done (186 events), explorer done
  (42), reconciler, writer, analyst, designer, casegen, generator … and job 5 finished **done, exit 0, 669 events,
  "Report ready"** in 94 s (checked through the API from the signed-in page). Two earlier attempts (jobs 3, 4) failed
  for the Chromium reason above, which the owner fixed with one command in his terminal.
- Security checks by hand: `/api/v1/projects` without a session → 401 envelope; `/app/../.env` → the app shell;
  `/app/%2e%2e/.env` → 404; health unauthenticated and reporting `owner_configured`.
- Not run: `frontend/e2e/acceptance.spec.ts` under Playwright (needs the owner's password as env vars; the owner can
  run `npm run e2e` with `AGENTQA_E2E_EMAIL/PASSWORD` set, or CI with secrets); the Docker image with the Node stage
  was not rebuilt (next `make smoke`/CI run covers it).

## Record of changes

- **Orchestrator extracted** (move, not rewrite): `agentqa/orchestrator/{projects,jobs,live}.py` hold what
  `web/app.py` had as `_projects/_open/_spawn/_running/_pid_alive/_prune_live/_sessions/_session_dir`; the dashboard
  keeps those names as thin wrappers that translate `NotFound`/`Busy` into its HTTP errors. Two small improvements
  on the way: the jobs log folder is created if missing; constants replaced the Windows magic numbers.
- **API**: `agentqa/api/{settings,errors,auth,ratelimit,schemas,routes_projects,routes_runs,routes_live}.py`,
  `create_app()` in `agentqa/api/__init__.py`, `agentqa/api/server.py` (what `python -m agentqa ui` now serves: API +
  built React app at `/app` + the old dashboard at `/`). New CLI command `owner-set` writes `backend/.env`.
- Tests first: `tests/test_api_auth.py` (9) and `tests/test_api_projects_runs_live.py` (13) were RED (no package), then
  GREEN; spawning is faked in tests, the job rows are real. Full suite: 111 passed.
- Dependencies: `argon2-cffi`, `sse-starlette` (pinned in `deploy/constraints.txt`).
- **Frontend**: Vite + React 19 + TypeScript scaffold in `frontend/` (`src/lib/api.ts` client with the envelope and CSRF
  header, `src/lib/live.ts` reducer, pages Sign in / Projects / Project / Live, `components/Shell.tsx`, `styles.css`
  from the M0.4 recipes, fonts bundled via `@fontsource`, Phosphor icons); unit tests for the client and the reducer
  (Vitest); `e2e/acceptance.spec.ts` (Playwright) for the acceptance flow.
- `npm install` onto Google Drive failed with `EBADF` (as the venv did); Drive also refuses junctions ("Local NTFS
  volumes are required") and symbolic links ("The device does not support symbolic links"). Workaround:
  `frontend/local-node.sh` mirrors the folder to `~/.cache/agentqa-studio/frontend-work`, runs npm there and copies
  `dist/`, `package*.json` and reports back; `make web-*` uses it on Windows, plain npm elsewhere (CLAUDE.md records it).
- **SPA fallback** (found during acceptance): a deep link such as `/app/projects/demo` returned 404 from the static
  mount. `_serve_frontend` now serves real files as themselves, index.html for every other `/app/...` path, and
  nothing outside the build folder (`tests/test_api_web.py`, 4 tests, RED → GREEN; `/app/../.env` verified by curl).
- **Acceptance gotcha (environment, not code):** runs started from the server in the owner's own PowerShell failed
  with "Executable doesn't exist … chrome-headless-shell.exe" although Git Bash saw the file. The assistant's shell
  runs sandboxed and its writes to `%LOCALAPPDATA%` are not visible to the real user session, so the Chromium
  download of M0.1 lived only in that sandbox. Fix: `python -m playwright install chromium` run by the owner in his
  own terminal (it is a one-time per-machine step; the setup guide must say so).
- Dockerfile gained a Node build stage that produces `frontend/dist` into the image; CI gained a `frontend` job
  (type-check, unit tests, build; the `docker` job now needs it); Makefile gained `web-install/web-test/web-build/web-dev`.

## Review (fresh context, 3 Nov 2026) and what changed because of it

Verdict before fixes: **Warning** (2 HIGH, 14 MEDIUM, 20 LOW). Every HIGH and the feasible MEDIUM/LOW items were fixed
test-first (`tests/test_api_hardening.py`, 13 tests RED → GREEN; full suite **128 passed**; frontend 10 Vitest tests,
`tsc -b` clean, build 339 kB / 47 kB):

| # | Finding | Fix |
|---|---|---|
| HIGH-1 | The old dashboard at `/` had no sign-in, so the new login protected nothing on that port. | `guards` middleware gates every non-`/api/v1`, non-`/app` path: anonymous page loads → 303 to `/app/sign-in`, anything else → 401; its HTML forms are checked against the request's Origin/Referer. Verified by HTTP on a real process. |
| HIGH-2 | Stage subprocesses inherited `AGENTQA_SECRET_KEY` / the password hash via `{**os.environ}`, and `load_dotenv` wrote the `.env` into `os.environ`. | `jobs.child_env()` drops `AGENTQA_SECRET_KEY` and `AGENTQA_OWNER_*`; `load_dotenv()` now returns a dict and `server.py` passes `{**load_dotenv(), **os.environ}` to `Settings.from_env(env)` — the secrets never enter the process environment. |
| MED | Wrong email returned faster than wrong password (user enumeration by timing). | `authenticate` verifies against a decoy argon2 hash when the email is unknown; same message either way (test). |
| MED | Login lock-out and rate limiter grew without bound. | Both bounded (10 000 addresses, least recently seen forgotten); `RateLimiter` has its own test. |
| MED | Logout needed a valid session; `Shell.tsx` never cleared state when it failed. | Logout always clears the cookie; the UI clears its cache and navigates in `finally`. |
| MED | Live page kept the previous run's agents when the run changed; a bad SSE frame could throw. | `reset` action on the reducer (test), `JSON.parse` guarded. |
| MED | SSE could drop events written just before the run ended. | One more read before `end` (test); file reads moved off the event loop (SQLite stays on it: thread-bound). |
| MED | Same slug for a different URL silently returned the other project. | `Conflict` → 409. |
| MED | No security headers / CSP. | nosniff, DENY, Referrer-Policy, Permissions-Policy on every response; CSP + no-store on the app shell. |
| MED | No authentication logging. | Sign-in ok / failed / locked-out logged with the client address. |
| MED | `owner-set` wrote `.env` world-readable and used `assert`. | `os.open(..., 0o600)`; a short stored secret is replaced, not asserted. |
| MED | `Project.tsx` hard-coded `auto_approve: true`. | A visible checkbox ("Approve the gates automatically", on by default until M1.4 adds the approval screens). |
| MED | `summary()` leaked server paths through `url` on a broken project. | Logged server-side; the API says "configuration error". |
| LOW | `Retry-After` on 429; 404 (not the shell) for a missing asset; `SESSION_HOURS` parse guarded; cookie cleared with the same attributes; tautological assert in `test_api_auth.py` replaced by "same answer either way"; sign-in form test; `package-lock.json` committed; compose documents `AGENTQA_COOKIE_SECURE=1` behind HTTPS. |

Left open, on purpose: `web/app.py` (1 387 lines) is the v0.8 dashboard that M1.4 replaces, not refactored; a
reverse-proxy-aware client address (`X-Forwarded-For`) and a full access log come with the cloud edition (M3.x);
an `ErrorBoundary` around the app routes comes with Live View v2 (M1.3). The demo regression was not re-run after
the review fixes (they touch sign-in, headers and the job environment, not the agents); CI's `demo` job covers it.
