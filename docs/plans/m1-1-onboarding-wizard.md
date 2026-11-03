# Plan — M1.1 Onboarding wizard 🔒

**Milestone:** M1.1 (PRD §9 Phase 1; §4 steps 1–6; FR-ONB-1…6). **Marker:** 🔒 — file uploads, test-account secrets,
and an outbound request to the owner's URL. **Owner approval:** required before building (asked 3 Nov 2026).

## Goal

A new project is created in the React app from a six-step wizard, each step with a short "why we ask" note. The
PRD acceptance: **the owner creates a project from the demo SRS and another from typed text alone, each in under
five minutes, and the requirements then appear with their sources.**

## What is built

### Backend — new routes under `/api/v1/projects/{slug}` (all owner-only, same envelope, same CSRF rule)

| Step | Endpoint | What it does |
|---|---|---|
| 1 Name & URL | `POST /projects` (extended: `environment`) | `init_project` as today, then writes the chosen environment into `applications.main.environment`. **Production** keeps the engine's read-only behaviour (no form submissions, workflows, attacks, load). |
| 1 | `POST /projects/{slug}/preflight` `{url}` | FR-ONB-5. One GET with a 6 s timeout, redirects followed (max 5), 256 kB read: `reachable`, final status, whether a **login page** is visible (a password box, or a Login / Sign in link) and the guessed login path. Every failure comes back as a plain-English fix ("the name does not resolve — check the spelling", "the site refused the connection — is it running?", "its certificate is not trusted — ask the team for the right address", "it answered 403 — AgentQA's address may need to be whitelisted"). Only `http(s)` schemes; the response body is never returned, only the verdict. |
| 2 Requirements | `GET/POST/DELETE /projects/{slug}/documents` | FR-ONB-2 with the **existing reader** (`agentqa.documents`): several files per upload (multipart), names sanitised to a bare file name, extension must be in `documents.SUPPORTED`, 50 MB per file; each upload is probed with `documents.read()` right away and answered as *read in full / partly read / not read* with the reason and the number of segments found. Progress per document is the browser's upload progress (XHR) plus that verdict. |
| 2 | `POST /projects/{slug}/requirements/typed` `{text, answers?}` | FR-ONB-3. Typed English is stored as a document source `srs/typed-requirements.md` (so the SRS stage reads it like any file). The **Requirement Chat agent — rule path** (`agentqa/agents/req_chat.py`, new, no AI): splits bullets / numbered items / "shall-must-should" sentences / user stories / Gherkin lines into candidate requirements, flags vague words with the SRS analyst's own `VAGUE` table, and asks **at most five** clarifying questions: who the users are when no role is named; the number when a limit is mentioned without one ("maximum", "within", "at most"); what should happen when an action fails; which login the users have; the meaning of a vague word. Answers are appended to the same document under *Clarifications*, so nothing is lost and the ledger has one source. **AI path:** when the project's AI mode is not `none` and the gateway has a usable key, the same prompt goes through `agentqa.ai.gateway().complete_json` (redacted, tier *balanced*) and its list replaces the rule list, marked `source: "ai"` so the UI says "proposed by AI — confirm"; any provider error falls back to the rule path. (The mode switch itself is M1.2; until then the mode is read from `project.yaml` and defaults to `none`.) |
| 2 | `POST /projects/{slug}/imports` | FR-ONB-6 (should): an Excel/CSV manual test sheet saved to `imports/` for the existing Importer, same checks as documents. |
| 3 Accounts | `GET/PUT /projects/{slug}/accounts` | One entry per role or `no_login: true`. Non-secret parts (`login_option`, `method`, `aliases`, `app`) go to the `roles:` block of `project.yaml` through `yamledit.replace_top_block`; secrets (`password`, `otp_fixed`, `totp_secret`) and identities go to the encrypted **vault** (`Vault.set_account`), exactly as the old Test data page does. GET returns masked values (`vault.mask`), never a secret. Input validated with Pydantic: role names `[a-z0-9_]{1,40}`, methods from `vault.METHODS`, OTP sources from `vault.OTP_SOURCES`. |
| 4 AI mode | — | The step shows **No-AI (selected, default)**, Local AI and Cloud AI as *coming in M1.2* with the reason; nothing to save yet. |
| 5 Schedule | — | Shown as optional and *coming in M1.5*; "Skip" is the only action. |
| 6 Review & start | existing `POST /projects/{slug}/runs` | Review card (name, URL, environment, documents + their verdicts, typed requirements count, roles) and "Run full pipeline" → the Live page, as today. |
| After | `GET /projects/{slug}/requirements` | For the acceptance: the requirements the SRS stage produced, each with `source_file`, section and ambiguity flags, so they "appear with sources" in the new app (`/app/projects/{slug}/requirements`, a plain list for now; dispositions and the RTM are M1.4). |

**Engine refactor (move, not rewrite):** the upload rule from `web/app.py::upload_srs` and the account rule from
`testdata_account` are moved into `agentqa/orchestrator/intake.py` (`save_document`, `probe_document`,
`save_typed`, `save_accounts`) and the old dashboard calls them, so both UIs enforce the same checks.

### Frontend — `frontend/src/pages/wizard/`

- `NewProject.tsx` route `/projects/new`, linked from the Projects page button that today creates a project in one
  click. One screen per step, a step rail on the left (M0.4 shell), "why we ask" under each title, Back / Continue,
  and the state in a pure reducer (`wizard.ts`, unit-tested: step validity, the project slug once created, document
  verdicts, chat answers, accounts).
- Step 2: a drop zone + file picker (XHR with progress bar per file, verdict pill from the API), the typed-text box,
  the chat panel (questions → answers → "Looks right" confirms the list), and the optional manual test sheet.
- Step 3: role rows (role, login button text, method, username / mobile, password, OTP source); passwords are typed
  by the owner into password fields and sent once over the API; the page never shows them again (masked from GET).
- `Requirements.tsx` route `/projects/:slug/requirements` (list with source and section; link from the project page).
- Tests: reducer (Vitest), the chat panel (Testing Library: questions shown, answers sent), accounts form (no secret
  echoed). Playwright `e2e/wizard.spec.ts` for the typed-text path (runs when the owner's env vars are set).

## Tests first

- `tests/test_intake.py`: file name sanitising (`../x` → `x`), unsupported type refused, 50 MB cap, probe verdicts
  (good .docx → read / N segments; empty .pdf → unread with reason), typed text saved as `srs/typed-requirements.md`
  and re-saved with clarifications appended, accounts split (yaml gets no password; vault gets it; GET masks).
- `tests/test_req_chat.py`: bullets / numbered / modal sentences / user stories / Gherkin each become requirements;
  vague words flagged; ≤ 5 questions and which ones; no questions when roles, limits and failures are all stated;
  AI path with a fake gateway (used when mode ≠ none, falls back on error, marks `source: ai`).
- `tests/test_api_wizard.py`: every endpoint through the API with the envelope, 401 when signed out, 404 on an
  unknown slug, 413 on an oversized upload, `preflight` against a local test server (reachable + login detected;
  refused connection → friendly fix; `file://` → 422), environment written on create, `GET requirements` after a
  seeded store.
- Frontend: `wizard.test.ts`, `RequirementChat.test.tsx`, `Accounts.test.tsx`.

## Out of scope (named so nobody expects them)

AI mode switch and provider catalogue (M1.2); schedules (M1.5); requirement dispositions, editing and the RTM in
the new app (M1.4 / FR-ONB-4); OpenAPI / Postman import (FR-ONB-7, later); Google sign-in; the "Show me how to log
in" recorder in the new app (the old dashboard's take-over still works).

## Risks

- **Outbound request from the server** (`preflight`): only the owner can call it, only `http(s)`, body never
  returned — but it still lets a signed-in owner make the server fetch any URL (their own test environments are
  usually private addresses, so a private-range block would break the feature). Recorded for the security review.
- **Uploads**: extension allow-list + size cap + bare names; the readers already run on untrusted documents in the
  SRS stage, so probing at upload time adds no new parser surface.
- **Secrets**: never in `project.yaml`, never echoed; the vault key handling is unchanged from v0.8.
- The demo SRS is a .docx: the "from the demo SRS" acceptance uploads `demo/srs/Demo_Certificate_Portal_SRS.docx`
  through the wizard rather than the one-click demo copier, so the upload path is what gets exercised.

## Decisions confirmed by the owner (the 🔒 gate, 3 Nov 2026: "Approved, build it")

1. The wizard **creates the project at step 1** (so uploads have a home); leaving the wizard keeps the project
   with whatever was entered. (A temporary draft would add complexity for little gain.)
2. Steps 4 and 5 are **shown but not functional** until M1.2 / M1.5.
3. `preflight` makes the server fetch the URL the owner typed (see Risks).
4. New dependency: none on the backend (httpx is already there); none on the frontend.

## Verification (3 Nov 2026)

- Tests first: `tests/test_req_chat.py` (7), `tests/test_intake.py` (11), `tests/test_api_wizard.py` (11) were RED
  (no modules), then GREEN; frontend `wizard.test.ts` (8), `RequirementChat.test.tsx` (3), `StepAccounts.test.tsx`
  (3). Backend suite **157 passed** at acceptance (174 after the review below), pyflakes clean; frontend `tsc -b`
  clean, Vitest **24 passed** (25 after the review), build 395 kB JS / 53 kB CSS (gzip 117 / 20 kB).
- **Acceptance met, watched in the browser pane** against a second server (`--port 8720`, the owner's 8710 kept
  running) with the demo portal on 8800:
  - *Typed text alone*: "Typed Text Portal" → address check ("Reachable (answered 200)") → four typed lines →
    "Check my text" → the chat listed T-001…T-004, flagged “quickly”, asked three questions (failure behaviour,
    sign-in, the vague word) → answers → "Looks right" → clerk account (password typed into a password box; GET
    `/accounts` afterwards shows `has_password: true` and no secret; `project.yaml` holds the role without
    username or password) → AI / Schedule steps → Review → "Run full pipeline" → Live View streamed; pipeline
    finished in 1 min 45 s. The Requirements page then showed **REQ-001…REQ-006 from `typed-requirements.md`**,
    including the merged clarification *(“quickly” means: Within 5 seconds for up to 1000 rows)* and the answers
    as requirements of their own ("When something goes wrong: …", "Sign-in: …"). About 3 minutes end to end.
  - *Demo SRS*: "Demo SRS Portal" → the .docx dropped on the upload zone (dispatched from the page, same code
    path as a real drop) → "read in full · 33 pieces of text" → "No login needed" → Review → run → the
    Requirements page showed **35 requirements (FR-01…) from `Demo_Certificate_Portal_SRS.docx`** within a minute.
- Found and fixed during acceptance (test-first):
  - The first typed document was one paragraph, so the Requirement Analyst made **one requirement of all four
    lines** and a second of the clarifications. `save_typed` now writes one `REQ-nnn:` paragraph per item the
    chat found and merges each answer into the requirement it is about (`test_intake.py` checks the file and runs
    the real analyst on it).
  - The demo portal reaches its login through `<button data-go=…>` elements, not links; `preflight` now also
    reads login buttons, prefers one that says where it goes, and the wizard says "a login button was found"
    when there is no address.
- Not run: `frontend/e2e/wizard.spec.ts` was not written (the acceptance above was driven by hand in the pane;
  the Playwright version is a follow-up once the owner's credentials are available as env vars in CI).

## Review (fresh context, 3 Nov 2026) and what changed because of it

Verdict before fixes: **Warning** (no CRITICAL, 3 HIGH, 9 MEDIUM, 8 LOW). Everything HIGH and MEDIUM and most of
the LOW items were fixed test-first (`tests/test_wizard_hardening.py`, 17 tests RED → GREEN; backend suite
**174 passed**; frontend **25 Vitest** tests, `tsc -b` and oxlint clean):

| # | Finding | Fix |
|---|---|---|
| HIGH-1 | Uploads ran the document readers (OCR, LibreOffice, lxml) on the event loop: one scanned PDF froze every other request, including the live stream. | Every file is checked first (name, size), then saved and probed in a worker thread (`run_in_threadpool`); zipped Office files are refused before parsing when their members would unpack past 200 MB (zip bomb). |
| HIGH-2 | An address with a space or a bad IPv6 literal crashed the check with a generic 500. | `validate()` catches every parser error and answers the plain-English "not a valid web address"; `..` in a host is refused too. |
| HIGH-3 | The 6 s timeout was per read, so a slow-dripping site could hold the check for minutes. | A 10 s deadline for the whole check, redirects included; a drip is reported as a timeout. |
| MED | Link-local and cloud-metadata addresses (169.254.169.254 …) could be fetched, also through a redirect from a public URL. | Redirects are followed by hand; every hop's host is resolved and link-local / multicast / unspecified / reserved / known metadata addresses are refused ("blocked" fix). Loopback and private LANs stay allowed. |
| MED | `PUT /accounts` answered from the project's stale config. | The project is re-read before the answer. |
| MED | "No login needed" wiped vault accounts with recorded login steps. | Only roles without recorded steps are removed. |
| MED | One bad file in a batch left the earlier ones on disk with a 4xx answer. | All names are validated before anything is written. |
| MED | The confirmed (possibly AI-proposed) list was not what got written; AI questions could exceed the answer schema. | "Looks right" and "Continue" send the confirmed `items`, and `save_typed` writes those; AI questions are cut to 500 characters. |
| MED | Delete errors were silent; an aborted upload left the buttons disabled forever. | `remove.error` is shown; XHR `onabort` / `ontimeout` reject. |
| MED | A corrupt .docx verdict quoted the server path. | Paths are replaced by `<project>` in verdicts. |
| LOW | `Method` / `OtpSource` Literals now used by `RoleIn`; file names capped at 120 characters and Windows reserved names refused; unknown network errors get their own fix text; stable row keys for role rows; the address verdict resets when the address is edited; the old dashboard's `upload_srs` now goes through `intake.save_document`; `intake` no longer re-exports `ROOT` / `NotFound`. |

Left open, on purpose: a per-probe wall-clock timeout for the readers (a pathological PDF still occupies one worker
thread; the thread pool has 40); `list_requirements` has no LIMIT (M1.4 pages it); the old dashboard's
`testdata_account` keeps its own copy of the account rules (M1.4 retires that page); no component test for the
`NewProject` container and no Playwright `wizard.spec.ts` yet (the acceptance was driven by hand, see above).

## Record of changes

- Backend: `agentqa/agents/req_chat.py` (Requirement Chat: `extract`, `questions`, `chat` with the AI path through
  the gateway when the project's `ai.mode` is not `none`); `agentqa/orchestrator/intake.py` (`safe_name`,
  `save_document` + `probe_document`, `list_documents`, `delete_document`, `save_typed`, `set_environment`,
  `save_accounts` / `accounts_view`); `agentqa/orchestrator/preflight.py` (`check` with plain-English fixes);
  `agentqa/api/routes_wizard.py` (documents, imports, typed, requirements, accounts, `POST /preflight`);
  schemas `ProjectIn.environment`, `PreflightIn`, `TypedIn`/`AnswerIn`, `RoleIn`/`AccountsIn`; `summary()` now
  carries `environment`. The old dashboard's own upload / test-data routes were **not** rewired to `intake` in
  this slice (they keep working unchanged; M1.4 retires them).
- Frontend: `src/lib/wizard.ts` (reducer + `canContinue`), `src/lib/api.ts` (`upload()` over XHR with progress and
  the CSRF header, new types), `src/pages/wizard/{NewProject,StepBasics,StepRequirements,RequirementChat,
  StepAccounts,StepLater,StepReview}.tsx`, `src/pages/Requirements.tsx`, routes `/projects/new` and
  `/projects/:slug/requirements`, the Projects page's inline form replaced by the "New project" button.
