# Plan — M1.4 Gates in the new UI

**Milestone:** M1.4 (PRD §9 Phase 1).
- **Requirements covered:**
  - §4 golden path, steps 4–6.
  - FR-LIVE-6.
  - FR-ONB-4: dispositions with who and why. M1.1 deferred them here, see `frontend/src/pages/Requirements.tsx:5`.
  - FR-ACC-3: approvals, dispositions, defect confirmations and exports in the change log.
  - FR-INT-1: Zoho CSV export.
  - FR-SCH-3: nothing approved automatically by default.
  - §7.4: `questions`, `plan`, `defects`.
- **PRD acceptance:** all three gates completed in the new UI on the demo; the change log records who and why.

**Marker:** the PRD does not give M1.4 its lock marker, but **Phase C is reviewed as if it had one**, for four reasons:
- Take-over sends clicks and keystrokes into a real browser on the application under test.
- New routes serve files from the project folder.
- Typed passwords and one-time passwords (OTPs) pass through the store.
- An approved heal writes `project.yaml`.

Phases A and B get `security-reviewer` for the exports and the file routes.

**Owner approval:** **given 4 Nov 2026, all seven decisions as recommended.** Planned with the `planner` agent at `5d85b63`, 4 Nov 2026; every
"the code does X" below names its file and line. Re-checked by hand the same day: facts 2 (the change-log writers and
their `by`), 3, 4, 5, 6 (`check_demo.py:45`), 9 (the "Typed '…'" echo and the stored command), 12 and 13.

**Shape:**
- Four phases, each a commit that can merge alone.
- Acceptance in two sittings: after Phase B (the three gates and the change log) and after Phase C (visual review, heals, needs-you box, take-over, pause).
- Acceptance runs in No-AI mode: **nothing is spent**.

## Goal

Bring every human decision of the v0.8 dashboard into the React app, record who made it and why, and retire the old pages it replaces.

- **Gate 1 — Questions:**
  - answer in plain English;
  - reopen an answer;
  - "Apply my answers and re-plan".
- **Gate 2 — Test plan:**
  - summary, gaps, cases by type, imported manual cases;
  - decide per case, per type, or all at once;
  - approve the plan;
  - download the Excel file;
  - continue the run.
- **Gate 3 — Defects:**
  - confirm, reject (with a reason), or send back to draft;
  - evidence;
  - Jira-style CSV and Zoho CSV downloads.
- **Visual review:** approve a changed screen as the new baseline, or report it as a defect.
- **Heals:** approve or reject each proposed fix.
- **"AgentQA needs you" box, take-over, pause and resume:** on every project page and in the Live View.
- **Change log** page.
- **Requirements** page: dispositions and the traceability matrix (RTM) download.
- **Project page:** shows what is waiting for you; the "approve automatically" switch becomes off by default and says exactly what it does.

## What the code says (recorded so nobody re-learns it)

1. **The gates live only in the old dashboard.**
   - Questions: `web/app.py:523-545`.
   - Plan: `552-587`; functional approval `612-617`; test-case Excel `630-638`.
   - Defects and their two CSVs: `652-690`.
   - Heals: `693-707`.
   - Visual review: `761-822`.
   - Help box and pause: `1309-1386`.
   - Change log page: `283-287`.
   - The API registers only these routers: projects, runs, live, live WebSocket, wizard, AI (`api/__init__.py:77-80`).

2. **The change log already exists and has a `by` column** (`store.py:96-98`). What writes to it today:

   | Action | Who writes the row | `by` value |
   |---|---|---|
   | Answering a question | `reconciler.answer_question` (`reconciler.py:191-194`) | "dashboard" |
   | Approving or rejecting a heal | `healer.approve_heal` (`healer.py:128-131`) | "dashboard" |
   | Setting a requirement's disposition | `requirements.set_disposition` (`requirements.py:305-307`) | "dashboard" |
   | Cases added or dropped by a design | the designer (`designer.py:398-415`) | "agents" |
   | Approving cases or the plan (`designer.py:580-598`) | nothing | — |
   | Defect decisions (`triage.py:320-324`) | nothing | — |
   | Visual review (`web/app.py:774-822`) | nothing | — |
   | Pause, take-over, exports | nothing | — |

3. **No API handler knows who is signed in.**
   - Routers check sign-in through `dependencies=[Depends(current_user)]` (`routes_projects.py:10`, `routes_runs.py:14`, `routes_wizard.py:13`), so handlers never receive the `User`.
   - `User(email, role)` is frozen (`auth.py:44-47`).
   - The owner is the only real account (`auth.py:143-160`).
   - Writers are owner and tester (`auth.py:27`).

4. **Plan approval.**
   - Only "approve all" sets `plan.approved` (`designer.py:593-597`). Approving by ids or by type only changes the cases (`designer.py:583-592`).
   - `plan()` clears the approval whenever the set of cases changes (its fingerprint, the `digest`) (`designer.py:549, 571-574`).
   - The pipeline stops at the plan gate unless `--auto-approve` is given (`cli.py:248-262`).
   - `--auto-approve` approves every proposed case (`cli.py:251-253`) and every ready imported manual case (`cli.py:291-294`).
   - "Continue" means `pipeline --from generate` (`routes_runs.py:23-24`).
   - When the plan was approved earlier, the gate passes silently (`cli.py:254-256`). The Live View's plan gate therefore reads "not yet" during a continued run, because only a `designer approve` event marks it approved (`board.ts:229`, `LiveHeader.tsx:42`).

5. **Questions.**
   - The pipeline never stops at the questions gate: it logs the count and carries on (`cli.py:243-244, 272-277`).
   - An answer only takes effect when reconcile runs again. The CLI says "Re-run 'reconcile' and 'design'" (`cli.py:377`); answers are read back by key in `reconciler._ask` (`reconciler.py:166-179`); design only reads the open count (`designer.py:563`).
   - **v0.8 bug:** the old page's "Re-plan" button runs design alone (`questions.html:8`), so answers given there wait for the next reconcile.
   - `answer_question` does not check that the question is still open (`reconciler.py:182-194`). Reopen clears the answer (`web/app.py:541-545`).
   - The options per question kind are in `reconciler.py:31-46`. The value box is free text, "only if your option asks for one" (`questions.html:16`).

6. **Defects and exports.**
   - `set_defect_status` appends the note and writes no change log (`triage.py:320-324`).
   - The old CSV downloads include drafts (`web/app.py:682, 689` pass `include_drafts=True`).
   - `export_csv` writes absolute evidence paths, i.e. the owner's folder names (`triage.py:339`).
   - Both CSVs write text from the application under test as-is (`triage.py:332-340, 361-369`). The Excel writer does the same through `ws.append` (`case_export.py:162`).
   - `check_demo` counts every defect that is not rejected or resolved (`check_demo.py:45`). **A seeded bug rejected in Gate 3 therefore reads as "MISSED".**

7. **Visual review is dashboard code, not engine code.**
   - `_approve_visual` copies files and updates the row (`web/app.py:774-784`); "report as defect" builds the draft (`web/app.py:803-821`). Neither checks the stored paths or writes the change log.
   - Statuses `baseline`, `same` and `changed` come from the runtime (`agentqa_runtime.py:1141, 1156, 1170`); `approved` and `reported` from the dashboard. A run keeps `approved` while the screen stays the same (`executor.py:222-229`).
   - A first run only saves baselines (`agentqa_runtime.py:1138-1145`). `DEMO_VISUAL_CHANGE=1` restyles the demo portal (`demo/portal/app.py:47, 94`).

8. **Heals.**
   - `approve_heal` does not check the heal's status (`healer.py:120-131`).
   - A workflow heal writes `project.yaml` (`healer.py:132-145`) through `yamledit.replace_in_workflow`, which quotes the new value only when it contains `{}:#` (`yamledit.py:45-49`) and then checks the result through `_commit` (`yamledit.py:54`). That value comes from the application under test.
   - The old page offers buttons only for locator and workflow proposals (`heals.html:14`).
   - `DEMO_VERIFY_LABEL` renames a button so the Healer has something to fix (`demo/portal/app.py:48`).

9. **The help box (assist) and take-over.**
   - An agent stores the question as a row (`assist.py:97-98`), emits a live `assist` event with `assist_id` and `ask_kind` (`assist.py:103, 382`), and checks the row every 0.5 s (`assist.py:109-123`). It emits again when answered, skipped or out of time (`assist.py:115-117, 125`).
   - Take-over commands queue in `assist_cmds` (`assist.py:394-405, 425-429`).
   - `_run_cmd` allows: click, type, press (only the keys in `KEYS`), back, scroll, and goto (only in-scope paths) (`assist.py:314-358`).
   - The dashboard passes the request body fields through unchecked (`web/app.py:1333-1335`).
   - **Typed text stays in the database in clear text** (`assist.py:429`, nothing removes it). A `type` command without the secret flag is also echoed into the live recording as "Typed '…'" (`assist.py:332, 403`). Answers, OTPs included, stay in `assist.answer` (`assist.py:155`).
   - `pending()` has a line meant for secret questions that does nothing (`assist.py:162-163`).
   - `expire_stale` exists but nothing calls it (`assist.py:167-175`).
   - By default the project folder sits inside the backend folder (`projects.py:16-24`), here inside Google Drive, so that database file is synced to the cloud.
   - `tools/e2e_assist.py` checks the vault and the logs for the typed password, but not the database (`e2e_assist.py:269-271`).

10. **Pause.**
    - Pause is a flag file holding `by` (`assist.py:435-455`).
    - It is honoured only where a browser runs: the Explorer (`explorer.py:346-347`), login (`login_flow.py:557, 712`) and test steps (`agentqa_runtime.py:1439-1448`). The other stages never check it.
    - Continue after a take-over clears it (`assist.py:420`). Resume answers every pending take-over with "done" (`web/app.py:1350-1357`).
    - A flag left set hands the browser over at the next run's first step.

11. **The old help box.**
    - It is on every dashboard page and polls every 2 s, 0.9 s during a take-over (`base.html:185-196`).
    - It asks for browser notifications without being asked (`base.html:159-163`).
    - It scales a click on the screenshot to the browser's viewport (`base.html:177-183`).

12. **Live View (M1.3).**
    - The board marks a card "waiting" per open `assist_id` (`board.ts:180-190`) and the plan "waiting" on the pipeline's gate event (`board.ts:156-158`).
    - The gate counts are counts of events in that recording (`board.ts:226-229`).
    - The pipeline card shows gate text but no link (`LiveHeader.tsx:39-43, 76-81`).
    - In the API process `AGENTQA_LIVE_DIR` is not set, so engine `live.emit` calls made from a route write nothing (`live.py:28, 39-40, 93`). An approval made in the app leaves no line in any recording.

13. **Frontend.**
    - Routes: `App.tsx:41-48`. Navigation: `NavLinks.tsx:25-40`.
    - The "Approve the gates automatically" switch defaults on (`Project.tsx:22-24, 57-62`), although it only approves the test plan and the imported cases (fact 4).
    - `canWrite`: `can.ts:3-7`. The CSRF header on every write: `api.ts:24-29`.
    - `list_requirements` has no LIMIT (`routes_wizard.py:91-97`).

14. **Request guard.**
    - The rate limit, the CSRF check and the Viewer rule run on every API write (`api/__init__.py:103-114`).
    - Only Live View screenshots have their own rate bucket (`api/__init__.py:23, 106`). The general limit is 240 per minute (`settings.py:48`).
    - `test_api_roles.py:44-78` lists every write route in the OpenAPI schema, so new writes are covered automatically.

15. **Store and project creation (M1.3 open rows #16 and #19).**
    - `open_project` opens a store (`projects.py:40-42`) that `open_or_404` callers never close (`routes_projects.py:13-17`).
    - Project creation accepts `user:password@` in the address (`schemas.py:19, 27`; `projects.py:18, 77`).

16. **The old dashboard.**
    - It is mounted at `/` (`api/__init__.py:169-172`, `server.py:10`).
    - Its own `live_events` trusts the cursor it is sent (`web/app.py:339-365`; M1.3 #17).
    - `tools/e2e_assist.py` drives it directly, without sign-in (`e2e_assist.py:166-169`).
    - Beyond the gates it holds:
      - test data and teach-login (`1035-1175`)
      - app map and teach-nav (`494-520`)
      - imports (`825-874`)
      - assistant (`877-913`)
      - readiness (`920-945`)
      - security (`948-964`)
      - integrations (`967-987`)
      - inbox (`990-1028`)
      - config (`394-411`)
      - SRS review (`418-491`)
      - execution and results (`267-313`, `641-649`)
      - APIs (`724-749`)
      - master plan (`237-242`)

17. **Almost no unit tests cover the gate engine functions.** Only a setup helper calls `designer.approve` (`test_v06.py:143`).

18. **The Live View run picker** shows the run folder's last change time (`orchestrator/live.py:40-41, 61`; M1.3 C6). Job rows have `started_at`; command-line markers have `started` (`orchestrator/live.py:132`).

19. **`cli.py` is 778 lines** (M1.3 record; the ceiling is 800).

## Shared backend pieces

- **One store per request (#16).** `orchestrator/projects.project_store(slug)` is a context manager that closes the store. Every route that uses `open_or_404` moves to it. An AST test makes sure no route calls `open_project` directly.
- **Who (fact 3).** Every write handler takes `user: User = Depends(current_user)`.
  - `orchestrator/gates/changelog.py`, about 80 lines:
    - `who(user)` returns `"<email> (<role>)"`. M2.1 adds `change_log.user_id`.
    - `record(store, object, object_id, change, why, by)` writes a row with `agent="person"`.
    - `page(store, limit, before_id)` reads the log.
  - Three engine functions gain a keyword `by: str = "dashboard"`: `reconciler.answer_question`, `healer.approve_heal`, `requirements.set_disposition`. Existing callers (CLI, old dashboard) behave exactly as before.
- **Reasons (decision 4).** `why` is trimmed text of at most 500 characters, stored in `justification`. It is required for: rejecting, undoing (reopening an answer, sending a defect back to draft), and approving visual changes as new baselines.
- **Safe files.** `orchestrator/gates/files.py` resolves a stored path and serves it only when it is inside `runs/`, `reports/`, `visual/` or `.agentqa/assist/`, and only for these types:
  - shown in the page: `.png`, `.jpg`, `.jpeg`;
  - offered as a download: `.zip`, `.webm`, `.txt`, `.json`.
  - Pages never receive file paths, only `(id, n)` or `(key, which)`.
  - `SHOT_PATH` widens to cover assist screenshots, visual images and evidence, so they use the screenshot rate bucket.
- **Formula-safe exports.** A new `agentqa/util.spreadsheet_safe(value)` puts a leading `'` before text that starts with `=`, `+`, `-`, `@`, a tab or a carriage return (a lone "-" excepted). It is applied in `case_export.workbook`, `triage.export_csv`, `triage.export_zoho_csv` and `requirements.write_rtm`. `export_csv` writes evidence paths relative to the project folder.
- **Limits.** Every list has `limit` and `offset` (or `before`), at most 200 rows.
- **Threads.** Handlers are plain `def`, so FastAPI runs them in its thread pool, as today.

## Gate 1 — Questions (`api/routes_questions.py`, `orchestrator/gates/questions.py`)

| Endpoint | Request | Response `data` | Calls | Change log |
|---|---|---|---|---|
| `GET /projects/{slug}/questions?status=open\|answered&limit&offset` | — | `{items, counts: {open, answered}, total}`; each item `{id, kind, question, options: [{label, needs_value}], proposed, priority, req_id, rule_id, status, answer, value, answered_at}` | the query of `web/app.py:527-530`, plus LIMIT | — |
| `POST …/questions/{qid}/answer` | `{choice: int, value: str ≤ 400}` | the question | `reconciler.answer_question(s, qid, choice, value, by=who)` | the engine's own row, now with who |
| `POST …/questions/{qid}/reopen` | `{why}` | the question | the update of `web/app.py:544` | "reopened (was '<label>')", why |
| `POST …/questions/apply` | `{}` | the job (202) | `jobs.spawn(p, s, ["replan"], "replan")` | "asked to re-plan with N answered question(s)" |

- **Errors:** 404 for an unknown question; 409 when it is no longer open (reopen it first); 422 when the choice is out of range, or when the option asks for a value and none was given.
- **Which options need a value:** `needs_value` comes from one table, `VALUE_OPTIONS`. A test checks it against `reconciler.OPTIONS` so the two cannot drift apart.
- **New `replan` command (fact 5).** `agentqa/replan.py`, about 40 lines:
  - runs `cli.stage("reconcile")` then `cli.stage("design")` in one process, with a live session and the job's status;
  - imports `cli` inside the function, so there is no import loop;
  - `cli.py` gains only the parser entry, about 3 lines;
  - `RunIn.scope` gains `replan`;
  - it does not re-run the Writer, so no AI cost in Cloud mode and no hour-long wait in Local mode.
- **Continued runs read honestly (fact 4).** When the plan gate passes because the plan was approved earlier, the run shell emits `designer approve` "Test plan approved earlier, on <at> by <who>" (level ok), taking <who> from the last plan-approval row. This is a run-shell line, not an agent change, and `board.ts` reads it without any change.

## Gate 2 — Test plan (`api/routes_plan.py`, `orchestrator/gates/plan.py`)

| Endpoint | Request | Response `data` | Calls | Change log |
|---|---|---|---|---|
| `GET /projects/{slug}/plan` | — | `{plan: {approved, approved_at, digest, summary}, types: [{type, cases, approved, rejected, proposed}], gaps, imported: {ready, review, approved, rejected}, running}` | as `web/app.py:552-568` | — |
| `GET …/plan/cases?type&status&limit&offset` | — | `{items: [{id, type, title, role, path, priority, oracle_source, req_ids, status}], total}` | query plus LIMIT | — |
| `POST …/plan/cases` | `{ids: ≤ 500 ids matching ^TC-\d{4,6}$, decision: approve\|reject\|reset, why}` | `{changed, plan}` | `designer.approve(s, case_ids=…, reject=…)`; reset as `web/app.py:584-586` | one row: "rejected 12 case(s): TC-0003, …", why |
| `POST …/plan/types/{ctype}` | `{decision: approve\|reject, why}` | same | `designer.approve(s, case_types=[ctype], …)` | one row |
| `POST …/plan/imported` | `{ids?, decision: approve_ready\|approve\|reject\|review, why}` | same | `importer.set_status` (`importer.py:418-421`), as `web/app.py:868-873` | one row |
| `POST …/plan/approve` | `{digest, why?}` | the plan | `designer.approve(s)` | "approved the plan: N approved, M rejected" |
| `GET …/plan/testcases.xlsx` | — | file (attachment; name made safe as `web/app.py:635`) | `case_export.workbook(p, s, include_srs=True, all_types=True)` | "downloaded the test cases (Excel)" |

- **Errors:** 422 for an unknown id, a bad pattern or too many ids. On approve: 409 `plan_changed` when the fingerprint the person reviewed is no longer current; 409 `busy` while a job runs.
- **No approval mid-run:** plan writes are refused while a job runs, so a re-design cannot overwrite a decision.
- **"Generate and run"** after approval uses the existing `POST /runs {scope: "continue"}`.
- **Starting a run that approves by itself:** `start_run` with `auto_approve: true` writes "started a run that approves the test plan by itself".

## Gate 3 — Defects (`api/routes_defects.py`, `orchestrator/gates/defects.py`)

| Endpoint | Request | Response `data` | Calls | Change log |
|---|---|---|---|---|
| `GET /projects/{slug}/defects?status&severity&limit&offset` | — | `{items, counts: {open_by_severity, by_status}, total}`; each item `{id, severity, priority, title, role, url, steps, expected, actual, req_ids, case_ids, status, created_at, notes, external_key, evidence: [{n, kind, role, image}]}` (no paths) | order as `web/app.py:655-656`, plus LIMIT | — |
| `POST …/defects/decisions` | `{ids: ≤ 200 ids matching ^DEF-\d{3,6}$, decision: confirmed\|rejected\|draft, why}` | `{changed}` | `triage.set_defect_status(s, ids, decision, note=f"{who}: {why}")` | one row per defect |
| `GET …/defects/export.csv?drafts=0\|1` | — | file | `triage.export_csv(p, s, include_drafts)` | "downloaded defects CSV (with / without drafts)" |
| `GET …/defects/zoho.csv?drafts=0\|1` | — | file | `triage.export_zoho_csv(p, s, include_drafts)` | same |
| `GET …/defects/{did}/evidence/{n}` | — | image or attachment | `files.py` guard on `evidence[n].path` | — |

- **Drafts in exports (decision 5):** the downloads default to confirmed defects only; the page has an "Include drafts" switch.

## Requirements (FR-ONB-4; `routes_gates.py`)

- `GET /projects/{slug}/requirements` gains `limit`, `offset`, `total` and `disposition_note`.
- `PATCH …/requirements/{rid}` takes `{disposition: out_of_scope|not_testable|manual|clarify, why}` and calls `set_disposition(…, note=why, by=who)`.
  - `covered` and `gap` are refused with 422: they are computed, and "covered" must never be a person's claim.
- `GET …/requirements/rtm.xlsx` serves the Excel file from `write_rtm` and is logged as an export.

## Visual review and heals (`api/routes_review.py`, `orchestrator/gates/{visual,heals}.py`; Phase C)

| Endpoint | Request | Calls | Change log |
|---|---|---|---|
| `GET /projects/{slug}/visual?show=changed\|all\|approved\|reported\|baseline\|same` | — | `{items: [{key, role, path, status, diff_ratio, run_id, case_id, updated_at, images: {baseline, current, diff}}], counts}` | — |
| `GET …/visual/{key}/{baseline\|current\|diff}` | — | image through the `files.py` guard; `key` matches `^[\w@.\-]{1,200}$` and must exist | — |
| `POST …/visual/{key}` | `{decision: approve\|defect, why}` | **moved, not rewritten** from `web/app.py:774-821`, plus a check that `current` is inside the project before copying | "approved as the new baseline" / "reported as DEF-0xx" |
| `POST …/visual/approve-all` | `{keys?: ≤ 200, why}` (why required) | loop over the same code | one row |
| `GET /projects/{slug}/heals` | — | `{items: [{id, case_id, run_id, kind, old, new, reason, status, created_at, decidable}], counts}`, LIMIT 200 | — |
| `POST …/heals/{hid}` | `{decision: approve\|reject, why}` (why required for reject) | `healer.approve_heal(s, hid, approve, project=p, by=who)` | the engine's row with who; the response carries the engine's note ("project.yaml updated" / "change it by hand") |

- Heals answer 409 unless the heal is `proposed` and its kind is `locator` or `workflow`.

## Needs-you box, take-over, pause (`api/routes_assist.py`, `orchestrator/gates/helpbox.py`; Phase C)

| Endpoint | Request | Calls | Change log |
|---|---|---|---|
| `GET /projects/{slug}/assist` | — | one bare read-only query (like `jobs.peek`, `jobs.py:45-55`) plus `expire_stale` at most once a minute → `{items: [{id, kind, question, role, agent, at, hint, options, clickables, fields, secret, url, vw, vh, headed, log, shot_v, has_shot, production}], paused: {on, at, by}}`, capped: question 500, hint 1 000, options 20×200, clickables 40, fields 20, log 12×200, url 2 000. Answers are never returned. | — |
| `POST …/assist/{aid}/answer` | exactly one of `text ≤ 200` · `option` · `{x, y, text?}` · `ok` · `skip` · `takeover` · `done` | `assist.answer(s, aid, ans, via="app <email>")`; 409 when already answered or out of time | "answered the explorer's otp question (value hidden)", "took over the <agent>'s browser as <role>", "handed back", "skipped" |
| `POST …/assist/{aid}/commands` | a union by `kind`: click `{x, y}` (inside the stored `vw`/`vh`) · type `{text 1–500, secret, replace}` · press `{key ∈ assist.KEYS}` · back · scroll `{dy ±5 000}` · goto `{path 1–400, starting with / or @}` | `assist.add_command`; 409 when not handed over; 429 when 20 commands already wait | none per command (start and finish are logged) |
| `GET …/assist/{aid}/shot?v=` | — | as `web/app.py:1367-1375`; `no-store`; screenshot bucket | — |
| `POST …/pause` · `POST …/resume` | `{}` | `request_pause(p, by=who)` (409 `not_running` when no job and no running live marker) · `clear_pause` plus "done" to pending take-overs (as `web/app.py:1350-1357`) | "paused every agent" / "resumed" |
| `POST …/accounts/{role}/teach` · `POST …/explore/teach {role}` | — | spawn `teach-login` or `teach-nav` as `web/app.py:1148-1154, 514-520`; the role must be in `p.roles()` | — |

**Small engine changes in `assist.py` (decision 2; why: no password or OTP stays readable in a Drive-synced file or a recording):**
- After a `type` command runs, its stored text becomes `{chars: n}`.
- Typing into a focused password field counts as secret even when the person forgot to tick "hide".
- A secret answer is overwritten with `"[given]"` once the agent has read it.
- What the agent does with the value is unchanged: the recorder takes values from the page, not from the command row (`assist.py:270-283`).

**How the page learns that a person is needed:**
1. The agent writes the row, then emits `assist` with its `assist_id` (`assist.py:97-103`).
2. The Live View receives the event within the feed's 0.5 s poll. The board already marks the card "Waiting for you". `LiveRun` sees `model.board.assists` grow and asks for the pending list at once.
3. On every other project page, the Shell's `useAssist(slug)` polls `GET /assist`: every 2 s while the tab is visible, every 1 s during a take-over, every 10 s while the tab is hidden (so the tab title still changes). It stops on 401. That is 30–60 requests a minute per tab, inside the 240 limit.
4. When the agent is answered, it emits the closing `assist` event and the card returns to "Running".

**What the person sees:**
- **The box ("AgentQA needs you").** It docks at the bottom right (a full-width bar on a phone) and does not steal focus. It shows the agent, role and question, announces itself once, and changes the tab title to "(!) AgentQA needs you". A "Tell me with a notification" button asks the browser's permission only when clicked.
- **Open** shows a dialog, using the Lightbox pattern (portal, page behind made inert). It holds the current screenshot (clickable for navigation questions, with the click scaled to the browser's viewport as `base.html:180`), option chips, chips labelled "On the screen:", the text box (OTP: numeric keypad, one-time-code autocomplete), "Let me take over" and "I can't help: skip it". **Escape minimises the dialog; it never skips the question.**
- **Take-over** fills the screen:
  - the live screenshot, with explicit width and height, reloaded only when `shot_v` changes;
  - "Type into the selected box" (password-style automatically for password fields, plus a "Hide what I type" switch);
  - Enter, Tab, Backspace, Back and Scroll down buttons;
  - "Open an address on the portal";
  - field and button chips;
  - the last six actions as text;
  - Continue: I'm done / Cancel;
  - the note about the visible browser window when there is one.
  - **On a production application** a red warning and an "I understand" tick come before the first command (decision 6).
- **Pause and take over** sits in the Live View header and in the box while a run is going. It switches to "Paused: resume all" and explains: "Agents with a browser stop at their next step and hand it to you; the Writer, Designer, Triage and Reporter carry on" (fact 10).
- **A Viewer** sees "AgentQA is waiting for the owner or a tester", with no controls and no screenshot.
- **Text from the application under test** (question parts, chip labels, the URL) is shown as text only; URLs are never links.

## Change log and the gate summary (`api/routes_gates.py`)

- `GET /projects/{slug}/changes?limit=50&before=` returns `{items: [{id, at, agent, object, object_id, change, why, by}], next_before}`, newest first, at most 200 rows.
- `GET /projects/{slug}/gates` returns `{questions_open, plan: {exists, approved, proposed, cases, digest}, imported_ready, defects_draft, defects_open, visual_changed, heals_proposed, assist_pending, paused, running}` (from `web/app.py:113-128`). It feeds the navigation badges, the Project page and the Live View.

## Frontend (`frontend/src/`, every file ≤ 400 lines)

- **Logic:**
  - `lib/gatesApi.ts`: requests and types.
  - `lib/gates.ts`, pure: the case/defect selection reducer, which decisions need a reason, export links, how "by" is shown.
  - `lib/assist.ts`, pure: cleans the pending list with caps, `pollMs(state)`, `scalePoint`, the answer bodies.
  - `lib/useAssist.ts` and `lib/useGateCounts.ts`.
- **Pages** (each about 100–180 lines, loaded lazily per route): `pages/gates/{Questions,TestPlan,Defects,ChangeLog,Visual,Heals}.tsx`.
  - Routes: `/projects/:slug/questions`, `/plan`, `/defects`, `/changes`, `/visual`, `/heals`.
- **Components:**
  - `components/gates/`: `QuestionCard` (a radio group labelled by the question; the value box only for options that ask for one), `CaseTable` (a selection checkbox per row, filter chips by type with counts), `DecisionBar`, `ReasonDialog`, `DefectCard` (steps / expected / actual in `<pre>` as text; evidence thumbnails through the guarded route), `ExportLinks`, `GateCounts`.
  - `components/assist/`: `NeedsYouDock`, `AssistDialog`, `TakeOver`, `ScreenShot`, `PauseButton`.
- **Navigation** (`NavLinks.tsx`), "This project": Overview, Requirements, Questions (badge), Test plan (badge), Defects (badge), Visual review (badge), Heals (badge), Change log, AI. Each badge has a spoken name, e.g. "Questions, 15 open".
- **Project page:**
  - a "What needs you" card (`GateCounts`) with a link per item;
  - the switch reads "Approve the test plan automatically (demos)", defaults **off**, and its use is logged (decision 3).
- **Live View:**
  - the pipeline card's gates become links to their pages; for the newest run they also show what is still open, e.g. "15 asked · 3 open";
  - `PauseButton` in the header row;
  - a "AgentQA needs you" banner while an assist is open.
- **Requirements page:** a disposition menu limited to the four values, with a reason; RTM download; "Show more" paging.
- **Styles:** `styles/gates.css` and `styles/assist.css`, each ≤ 400 lines; new colour pairs go into `check_contrast.py`.
- **Breakpoints:** new grids follow the 1 024 / 1 400 px convention and `.g-dash` is fixed (C12). MASTER §6 records the one convention.

## The old dashboard

| Old pages | New home | When |
|---|---|---|
| questions, plan, functional, defects (+ CSVs), heals, visual, changes, the help box and pause | M1.4 pages | Phase D: redirect to `/app/…`, remove routes and templates |
| live, live events, live sessions, shots, `live.js` / `live.css` | Live View (M1.3) | Phase D: redirect and remove (**closes #17**) |
| srs (dispositions, RTM), ai, new / demo forms | Requirements (Phase B), AI page (M1.2), wizard / Try the demo | Phase D: redirect |
| test data (accounts, teach-login, data sets, secrets), app map, imports, overview / master plan, execution / results, readiness, security, APIs, integrations, inbox, assistant, config, SRS passage review | wizard and teach routes in part; the rest M1.5–M2.4 | kept behind a banner "These pages are moving to the new app"; the inventory goes in HANDOFF |

The old help box stays on the remaining old pages until they go: the first answer wins and the second gets a 409.

## Carry-overs from M1.3

| Row | Decision | Where and why |
|---|---|---|
| A #16 store never closed | **in** | Phase A: M1.4 adds about 30 routes that open stores; fix the pattern first |
| A #17 old `live_events` cursor | **in** | Phase D: the old Live View routes are removed |
| A #19 `user:password@` at creation | **in** | Phase A: one validator on `ProjectIn` and the old `/new` form, answering 422 |
| B22 aria-pressed on the followed card | **wait** | `AgentBoard.tsx:38` belongs to the follow-up branch: Phase D after it merges, otherwise handed to it |
| B22 lightbox backdrop click | **in** | Phase C (`AgentFocus.tsx:29`): the help dialog reuses the pattern |
| B22 auto-approve default | **in** | Phase B (decision 3) |
| C6 run picker time | **in** | Phase D: job `started_at`, then marker `started`, then first event, then folder time, in `orchestrator/live.py` (not in the follow-up's list) |
| C7 site-map children column | **deferred** | layout work in `siteMap.ts` with nothing to do with the gates: M1.8 polish |
| C12 grids ignore the sidebar | **in, partly** | Phase B: new pages and `.g-dash`; the mock itself is deferred (it documents, it does not ship) |
| C13 focus column out of sight under 1 024 px | **in** | Phase C (`LiveRun.tsx`): scroll into view on choice |
| C14 board's spoken status | **wait** | `AgentBoard.tsx:57`, as B22 |
| C15 `runOver` prop names; Next step / Go live disabled under focus | **in, partly** | Phase D: `PipelineCard`, `AgentFocus`, `TestTiles` and `PlayerBar.tsx:35, 47` now; `AgentBoard` waits as B22 |

**Coordination.** Phases A–C never touch `ai/providers.py`, `ai/router.py`, `orchestrator/phases.py`, `lib/live/board.ts` or `components/live/AgentBoard.tsx`. They only read the board model and import `STATE_WORDS`. Phase D rebases onto `main` before the three `AgentBoard` items.

## Tests first

**Fixture.** `tools/make_gates_fixture.py` builds `backend/tests/fixtures/gates/` from the owner's real No-AI demo store, stopped at the plan gate, then continued:
- JSON rows: questions, plan, cases, imported cases, defects with evidence, requirements, a few visual rows and heals;
- at most 6 small images;
- relative paths only;
- it refuses to run if any demo password or OTP appears (the passwords are read from the YAML, as in M1.3 #9);
- it also writes `frontend/src/test-fixtures/gates-demo.json`.

**Backend (pytest):**
- `test_gates_engine.py`, written first and green on today's code, to pin today's behaviour before anything moves:
  - `answer_question` label, value and log row;
  - approving by ids, by type and all, and that only "all" sets the plan approved;
  - `plan()` clears the approval when the case set changes;
  - `set_defect_status` appends the note;
  - CSV and Zoho columns, the byte-order mark (BOM) and the `include_drafts` flag;
  - locator and workflow heals;
  - `set_disposition`.
- `test_project_store.py`: the store closes on success and on error; no route calls `open_project`; `user:pw@` addresses answer 422 on the API and on the old form.
- `test_changelog.py`: the `who` format; the row's fields; newest-first paging with `before`; the `by` keyword defaults to "dashboard".
- `test_api_questions.py`:
  - list order, filters and counts;
  - an answer is logged with the signed-in email and role;
  - a value is required when the option asks for one;
  - wrong choice 422, already answered 409, unknown 404;
  - reopen needs a reason;
  - `VALUE_OPTIONS` matches `reconciler.OPTIONS`;
  - "apply" spawns `replan` and answers 409 while busy.
- `test_replan.py` (with `_stage` faked): reconcile then design in one live session; the job is marked; `RunIn` accepts `replan`; a continued run with an earlier approval emits `designer approve` with who.
- `test_api_plan.py`:
  - summary and gaps; cases paging (at most 200);
  - decisions: unknown id, bad pattern and more than 500 ids answer 422; reject without a reason answers 422;
  - by type; imported cases;
  - approve with a stale fingerprint 409, during a job 409, and one log row;
  - the Excel file: content type, a safe file name, and a case titled `=HYPERLINK(…)` stored as text;
  - "started a run that approves by itself" is logged.
- `test_api_defects.py`:
  - order and counts;
  - several ids at once; reject without a reason 422; notes appended; one row per defect;
  - both CSVs with and without drafts; formula-safe cells; no absolute paths;
  - evidence: an index out of range, a planted `..` path and an absolute path outside the project all answer 404; types follow the allow-list.
- `test_api_requirements.py` (extended): only the four dispositions; the log; LIMIT; the RTM file.
- `test_api_gates_summary.py`: the counts equal the fixture's.
- `test_api_roles.py` (extended): the new writes are covered automatically (the floor rises from 15 to 30 routes); the gate pages and downloads answer 200 to a Viewer.
- **Phase C:**
  - `test_assist_engine.py` (pinning tests, then the hardening):
    - an answer counts once;
    - `add_command` only for a pending take-over;
    - typed text gone after it runs, checked with a fake page;
    - a password field forces secret;
    - a secret answer is overwritten after it is read;
    - pause records `by`; `expire_stale` works.
  - `test_api_assist.py`:
    - the caps on the pending list;
    - exactly one action per answer;
    - x/y outside the viewport, an unknown kind or key, and a bad goto path all answer 422;
    - a 21st waiting command answers 429; out-of-time 409;
    - the screenshot name guard and `no-store`;
    - pause with nothing running 409; resume releases take-overs;
    - log rows are written, and a planted typed marker appears in no log row, no recording and not in the database file;
    - teach routes check the role (with a fake spawn).
  - `test_api_visual.py`:
    - **parity**: the old route and the new one, on two copies, leave identical rows and files;
    - a row whose path is outside the project is refused and nothing is copied;
    - approve-all needs a reason.
  - `test_api_heals.py`:
    - approving a locator heal changes the cases and is logged with who;
    - a workflow heal updates `project.yaml`;
    - a hostile new value (a quote, a newline, `: x`) still leaves valid YAML with nothing else changed;
    - not proposed or kind `manual`: 409.
- **Phase D:**
  - `test_live_sessions_start.py` (C6);
  - `test_dashboard_retired.py`: old gate URLs redirect, their POSTs are gone, `live.js` is gone, the remaining old pages show the banner, and the old-form Viewer test still passes.

**Frontend (Vitest):**
- `lib/gates.test.ts`: selection never changes its input; reason rules; export links.
- `lib/assist.test.ts`: caps; `pollMs`; `scalePoint`; answer bodies.
- `QuestionCard.test.tsx`: the value box appears only when the option asks for one; 409 says "already answered"; a question `<img src=x onerror=…>` renders as text.
- `TestPlan.test.tsx`: summary, gaps, type chips; reject asks why; approve is disabled while running; the 409 "plan changed" message; "Generate and run" appears after approval; the Excel link; a Viewer gets no controls.
- `Defects.test.tsx`: counts; decisions; reject asks why; evidence goes by index; the drafts switch; application URLs are text; a Viewer gets no controls.
- `ChangeLog.test.tsx`: who and why shown; "Show older".
- `NavLinks.test.tsx`: badge names.
- `Project.test.tsx` (extended): the switch is off and renamed; the "What needs you" card.
- `Requirements.test.tsx`: the menu and the reason.
- `LiveHeader.test.tsx`: the gate links.
- **Phase C:**
  - `NeedsYouDock.test.tsx` (fake timers): poll timing; focus not stolen; the tab title; Viewer read-only.
  - `AssistDialog.test.tsx`: options; a screenshot click is scaled; skip; Escape only minimises.
  - `TakeOver.test.tsx`: each button's body; password means secret; the production tick; the screenshot reloads only on a new `shot_v`.
  - `PauseButton`, `Visual`, `Heals`.
  - The Live View banner; Lightbox backdrop (B22); scroll into view (C13).

**In a real browser** (a throwaway server and owner, like `check_app.py`):
- **`check_app.py`:** six new pages (questions, plan, defects, changes, visual, heals), seeded from the fixture, at six widths in light and dark.
- **`frontend/design-system/check_gates.py`** (new, about 220 lines; `make gates-check`).
  - Phase B part:
    - answer two questions (one with a value) and reopen one with a reason;
    - reject three cases with a reason, approve one type, approve the plan;
    - confirm 17 defects and reject 2 with a reason;
    - download the three files and check them: the Excel opens, the CSV headers, the Zoho BOM, no drafts by default;
    - open the change log and find every action with the owner's email and the reason;
    - as a Viewer pass (minted with the throwaway secret, as in M1.3): no controls, and a write answers 403.
  - Phase C part:
    - insert a pending assist with a screenshot: the dock appears within 3 s and the title changes; answer it;
    - insert a take-over: click the screenshot and a command row appears with scaled coordinates; type into a password field and the stored text is gone once the script, acting as the agent, marks the command done;
    - Pause and Resume;
    - approve one visual change and report one; approve one heal and reject one.
- **`tools/e2e_assist.py`**, ported to the signed-in API with the CSRF header. It runs the real take-over on the hard-login demo, and its last check also scans the database file for the typed password.

## Build order (four commits)

**Phase A — the three gates' backend, the change log, store fix (commit 1; can merge alone, the old dashboard keeps working).**
1. Pinning tests (`test_gates_engine.py`), then the fixture tool and the fixture.
2. `project_store` (#16), the creation validator (#19), `changelog.py` and the `by` keywords.
3. Services: questions, plan (with imported cases), defects, requirements; formula-safe exports.
4. `replan` command and the continued-run approval line.
5. Routers and `schemas_gates.py`, the summary and the change-log route.
6. Full suite, pyflakes, `check_demo` 19/0 (No-AI). Fresh-context `code-reviewer`, `python-reviewer` and `security-reviewer` (exports, file guard, who). HIGH and MEDIUM fixed test-first; commit.

Dependencies: step 2 needs 1; 3 needs 2; 4 can run beside 3; 5 needs 3 and 4.

**Phase B — the three gates in the app (commit 2).**
1. `lib/gates*`; components and pages; navigation; Project page; Requirements page; gate links in the pipeline card.
2. CSS and contrast pairs; `check_app.py` pages; the Phase B part of `check_gates.py`.
3. `make lint`, `make web-test`, `make web-build`, `make ui-check`, `make gates-check`. `typescript-reviewer`, `react-reviewer` with an accessibility pass, `security-reviewer` (untrusted text); fixes test-first; commit.
4. **Acceptance sitting 1** (below).

Dependencies: needs Phase A's contract. Step 2 needs 1.

**Phase C — visual review, heals, help box, take-over, pause (commit 3; reviewed as lock-marked).**
1. Pinning tests for `assist`, then the hardening; visual code moved with its path check; heals service; help-box service.
2. Routers, schemas and the screenshot bucket; teach routes; `e2e_assist.py` ported.
3. The dock, dialog, take-over and pause; Live View banner; Visual and Heals pages; B22 backdrop; C13.
4. `check_demo` 19/0; the Phase C part of `check_gates.py`; `e2e_assist.py`. All five reviewers in fresh contexts, `security-reviewer` on the take-over surface, assist secrets, file routes and the heal's YAML write; fixes test-first; commit.

Dependencies: needs Phase A steps 2–3; step 3 needs step 2 and Phase B's navigation.

**Phase D — retire, polish, acceptance sitting 2, record (commit 4).**
1. Old pages: redirect and remove (#17); the banner; the inventory in HANDOFF.
2. C6, C15 (without `AgentBoard`); rebase onto `main`, then B22 aria-pressed, C14 and the `AgentBoard` rename if the follow-up has merged.
3. **Acceptance sitting 2**; this plan's record, HANDOFF, MASTER §6, ADR 0004 (who/why in the change log, the export policy, take-over hardening).

Dependencies: needs Phases B and C.

## Acceptance with the owner

**Sitting 1 (the PRD acceptance), after Phase B.** A throwaway review server (generated owner, scratchpad projects folder; the owner's own sign-in never touched) and the demo portals on 8800/8810. The owner watches in the browser pane.
1. Run full pipeline with the switch off. The Live View shows "Test plan approval: waiting for you" and the run stops there.
2. **Gate 1:** he answers questions (one with a value), reopens one with a reason, and presses "Apply my answers and re-plan".
3. **Gate 2:** he reviews the plan, rejects one case with a reason, approves the plan, downloads the Excel file, then presses "Generate and run".
4. `check_demo` is taken **before Gate 3**, because a rejected seeded bug counts as missed.
5. **Gate 3:** he confirms defects, rejects one with a reason, and downloads the Zoho CSV.
6. The Change log page shows each action with his email "(owner)" and his reasons.
7. A look as a Viewer, with a pass minted for the throwaway server only.

**Sitting 2, after Phase C.** A second demo copy, with its own portals on 8820/8830 and the mock inbox on 8025, as `e2e_assist.py` uses.
- **Take-over:** with `DEMO_LANG=ml DEMO_HARD_LOGIN=1`, AgentQA asks; he presses "Let me take over", clicks the icon, Citizen Login, types the mobile number and the OTP from the inbox, and presses Continue.
- **Pause:** during the Executor he presses Pause, the browser is handed over, he presses Continue.
- **Visual review:** restart the portals with `DEMO_VISUAL_CHANGE=1`, run `pipeline --from run`; he approves one changed screen and reports one.
- **Heals:** with `DEMO_VERIFY_LABEL="Mark verified"` he approves one heal and rejects one.

## Demo regression rule

- After every commit that touches the engine (A: `by` keywords, export cells, `replan`, the approval line; C: `assist.py`, the visual move, the heals `by`), run the **unattended** check on a fresh copy in No-AI mode: `pipeline --policy srs_wins --auto-approve`, then `tools/check_demo.py`. It must give 19/19 and 0 extra.
- The gated acceptance run's result is also recorded, but the person's answers can honestly change it: for example "log a defect" adds a defect.
- The visual and heal runs use their own copy (the portal is deliberately changed), so the 19/0 count does not apply to them.

## Risks

- **Concurrent writers:** a gate write can meet a running stage (SQLite in WAL mode with a 30 s wait). Plan writes are refused while a job runs. A command-line run is not a job, so pause checks the live marker too.
- **The plan can change under the person:** a re-plan clears the approval (`designer.py:571-574`). The fingerprint check answers 409 and the page says "the plan changed: review again".
- **Answers alone do nothing** until re-plan (fact 5). The page says so, and "Apply my answers" is the only button that applies them.
- **Pause covers browser stages only;** a stale flag would hand over at the next run. The server refuses pause when nothing runs, and Resume always clears it.
- **Questions left by a crashed run:** `expire_stale` on read.
- **Take-over drives a real browser:** in-scope addresses only, coordinates inside the viewport, an allow-list of keys, at most 20 waiting commands, the production warning, nothing typed kept. Two people at once: the first answer wins and commands queue in order.
- **Untrusted text everywhere:** SRS questions, defect titles and results, chip labels, heal values written into `project.yaml`, spreadsheet formulas. Text-only rendering, safe cells, and the YAML hostile-value test.
- **File routes:** paths are never sent; the guard checks folders and types; images go out with fixed types and `nosniff`.
- **Imported manual cases** are approved only by `--auto-approve` (`cli.py:291-294`). The Test plan page offers them explicitly, so a gated run can match the unattended one. That this keeps 19/0 is checked in sitting 1, not assumed.
- **Size limits:** `cli.py` 778 → about 785 (ceiling 800; M1.5 extracts the runner, M1.3 #20). `web/app.py` shrinks in Phase D.
- **The Viewer rule** is only met by tests and a minted pass until M2.1.
- **No coverage tool** (M1.3 fact 20): every new module gets its own test file; coverage is measured from M1.8.
- **The follow-up branch:** files are disjoint until Phase D; rebase before the `AgentBoard` items.

## Decisions for the owner

**Confirmed by the owner, 4 Nov 2026: all seven as recommended** — one milestone in four phases with two acceptance
sittings; the small engine changes (who in the log, formula-safe exports, relative CSV paths, `replan`, the "approved
earlier" line, typed secrets wiped); per-case / per-type / all approval with the auto-approve switch off by default and
logged (case editing later); a reason required to reject, undo or accept changed screens; downloads hold confirmed
defects only, with "Include drafts"; take-over on production behind a warning and a one-time tick; the replaced old
pages redirect and are removed, the rest stay with a "moving" banner.

The seven as they were put to him:

1. **One milestone or two.**
   - *Recommended:* one milestone in four steps, and you check it twice: first the three gates (questions, test plan, defects) and the change log, then visual review, heals, the "AgentQA needs you" box and taking over the browser. You can merge the gates after the first check.
   - *Alternative:* two separate milestones (M1.4 the gates, M1.4b the rest), each with its own plan.

2. **Small engine changes.** None changes how an agent tests; the 19-bug check must stay 19/0.
   - The change log remembers who you are.
   - Spreadsheets cannot carry a hidden formula from the tested website.
   - The CSV no longer shows your folder names.
   - A new "re-plan" step (compare again, design again) applies your answers without re-running the Writer, so it costs nothing in Cloud mode.
   - A continued run says the plan was approved earlier, and by whom.
   - Passwords and one-time codes you type in the help box are wiped from the database once used.
   - *Recommended.* *Alternative:* none of them. Then the log says "dashboard", answers need a slower run that re-writes the requirements, and a password you type stays readable in a file Google Drive syncs.

3. **The test plan gate.**
   - *Recommended:* you approve or reject each case, each type, or everything, with a reason when you reject. Editing a case's own steps or expected result comes later, because the Test Designer would first have to learn to keep your edits each time it re-plans. The "approve automatically" switch on the project page becomes off by default, says it only approves the test plan, is meant for demos, and every use is written in the change log. Scheduled runs (M1.5) will never use it.
   - *Alternatives:* keep the switch on by default; or allow editing case text now (a bigger change to the Test Designer, with its own plan).

4. **When to ask "why".**
   - *Recommended:* a short reason is required when you reject something, undo a decision, or accept changed screens as the new normal. It is optional when you approve or confirm.
   - *Alternatives:* always required; or never required (the log then shows only who and when).

5. **What the downloads contain.**
   - *Recommended:* the Zoho and Jira downloads contain only defects you confirmed, with an "Include drafts" switch.
   - *Alternative:* include drafts, as the old dashboard does today, which can send unchecked findings to developers.

6. **Taking over the browser on a live production website.**
   - *Recommended:* allowed, with a red warning and a one-time "I understand" tick, because a real login with a one-time code often needs you.
   - *Alternative:* not allowed on production; you can still type a one-time code or say which button to press.

7. **The old dashboard.**
   - *Recommended:* the old pages this milestone replaces (questions, plan, defects, heals, visual review, Live View, change log) send you to the new app and are removed. The other old pages (test data, app map, readiness, security scan, integrations, inbox, settings file) stay, with a note that they are moving, until their own milestones.
   - *Alternatives:* keep every old page until all are rebuilt; or remove all now, which loses test data, readiness, security and integrations until they are rebuilt.

## Out of scope (named so nobody expects them)

- **Later milestone:** editing a case's steps or expected result (needs a Test Designer plan).
- **M1.5:** the scheduler's unattended rules. Schedules must never pass `auto_approve`; new questions and defects queue for a person (FR-SCH-3).
- **M1.6:** reports, and the RTM inside the reports.
- **M1.8:** site-map layout (C7); the coverage gate.
- **M2.1:** real Tester and Viewer accounts; `change_log.user_id`; per-project membership.
- **M2.4:** Zoho CSV import and the Zoho API; Jira and Azure DevOps push from the new app; "agent waiting > N minutes" alerts.
- **Also not here:**
  - the remaining old pages (table above);
  - pushing the pending list over the WebSocket instead of polling;
  - clearing a person's disposition override;
  - the follow-up branch's provider-switch line and credit classification (C4, C5).

## Not yet verified (Phase A pins these first)

- That openpyxl stores a string starting with "=" as a formula (library behaviour; the first export test pins it).
- Whether a gated run, with imported manual cases approved on the Test plan page, still gives 19/0 (sitting 1 checks).
- `yamledit._commit`'s exact check; the evidence kinds (assumed screenshot, trace, video); whether `generator` runs
  approved imported manual cases; how long the demo takes to reach the plan gate.

## Verification

### Phase A (4 Nov 2026, No-AI, nothing spent; demo portals on 8800/8810)
- **Pinning tests first:** `test_gates_engine.py` 16/16 green on the unchanged code, then kept green.
- **Every new test was red before its code:**
  - `test_project_store`, `test_changelog`, `test_gates_fixture` and `test_replan`;
  - `test_spreadsheet_safe` and `test_api_{questions,plan,defects,requirements,gates_summary}`;
  - the extended `test_api_roles`.
  - Together: 155 tests across the 12 files.
- **Full backend suite:** **621 passed** (`pytest -q tests`).
- **pyflakes** (`agentqa demo tools tests`): clean.
- **Demo regression, unattended,** on a fresh copy (`pipeline --policy srs_wins --auto-approve`, then `tools/check_demo.py`): **19/19, 0 unexpected**. Its `reports/defects.csv` holds evidence as `runs/…/evidence/…` and no folder names.
- **Demo run, gated, for the fixture:** a fresh copy stopped at the plan gate (15 open questions, 206 proposed cases, 9 of 10 imported cases ready). The plan and the ready imported cases were then approved, and the run continued with `--from generate`: **19/19, 0 unexpected**.
- **Fixture:** `tools/make_gates_fixture.py` on that copy wrote 606 rows in 13 tables and 6 images. It checked the 3 demo passwords and the 8 one-time codes the inbox delivered.
- **Flaky under load:** `test_live_ws_real_server.py::test_an_sse_stream_closed_early_frees_its_slot` failed once while a demo pipeline ran beside the suite. It passed alone (4/4) and in the full run above.
- **After the review fixes** (below), everything was run again on a third fresh copy:
  - the full suite: **659 passed**;
  - pyflakes: clean;
  - the unattended demo regression: **19/19, 0 unexpected**, and its `reports/defects.csv` names no folder;
  - the fixture, regenerated: 606 rows and 6 images with fingerprinted names, checked against the passwords and the 8 delivered codes.

## Review (fresh context)

### Phase A (4 Nov 2026)
Three reviewers read the change in fresh contexts: `code-reviewer`, `python-reviewer` and `security-reviewer`. They read the code and probed it with throwaway scripts. Nothing was CRITICAL. Every HIGH and MEDIUM was fixed test-first: each new test failed first, then passed.

| # | Found by | Severity | Finding | Fixed |
|---|---|---|---|---|
| 1 | python | HIGH | `CASE_TYPE` refused digits, so `a11y_basic` could not be filtered or decided | `^[a-z0-9_]{1,40}$`; a test checks every fixture type |
| 2 | python, security | HIGH / LOW | the CSV download name used the raw slug: a Hindi or Japanese project name answered 500 | `exports.download_name` (ASCII only) for all four downloads |
| 3 | code, python | MEDIUM | requirement and imported-case ids from documents (`BR/01`, `TC 001`) were refused | `DOC_ID`: any text up to 200 characters without control characters; `PATCH requirements/{rid:path}` |
| 4 | code | MEDIUM | "approved earlier … by" could name the person behind an older approval | a log row counts only if it is not older than `plan.approved_at` |
| 5 | code, python, security | MEDIUM | downloads rewrote `reports/` and could serve a stale or swapped file (Excel holding `rtm.xlsx`, a report stage beside them) | `gates/exports.build`: the engine writer runs into a temporary folder of its own; a missing file or `OSError` answers 503 and nothing is logged |
| 6 | security | MEDIUM | `user:password@` still reached `project.yaml` through the old add-application form and `agentqa init` | `config.init_project` refuses it, and so does the form; a saved one is never shown (`summary`, the Excel header) |
| 7 | security | MEDIUM | downloads are logged GETs, so a link on another site (the portal under test on its own port included) could start one | `auth.download_origin_check`: `Sec-Fetch-Site` must be `same-origin` or `none` (403 `csrf`); the same download by the same person is logged once a minute |
| 8 | python | MEDIUM | `decide_cases([])` in the service would approve every case (the `designer.approve` trap) | `known_ids` refuses an empty list |
| 9 | python | MEDIUM | confirming an exported defect again would file it twice in Jira | 409 `exported` for a defect with `status='exported'` or an `external_key` |
| 10 | python | MEDIUM | a failed `replan` left no traceback in its log | `traceback.print_exc()` |
| 11 | security | LOW | a double-click on "apply" could start two jobs | `jobs.spawn` checks and starts under one lock (`test_jobs_spawn.py`) |
| 12 | all three | LOW | a huge id answered 500 | `Path(ge=1, le=2**31-1)` / `Query(le=…)` for questions, runs and `before` |
| 13 | code | LOW | "approved 0 … case(s)" rows | no row when nothing changed |
| 14 | security | LOW | a newline in a reason could fake a decision line in a defect's notes | reasons are one line (`clean_why`) in the log, the note and the schemas |
| 15 | security, python | LOW | one bad evidence entry broke the whole defect list; NTFS streams; other drives and network shares | type guards; `:` in a name refused; another drive refused before anything is read |
| 16 | security | LOW | `" =1"` passed `spreadsheet_safe` | spaces before the sign count |
| 17 | python | LOW | fixture tool: a failed write lost the old fixture; image names could clash; "demo" was cut from "demo2"; no email or `/tmp` check; `--frontend` could be any file | build in `<out>.new` and swap; fingerprinted names; a folder-boundary match; email and POSIX-root checks; `.json` outside the project only |
| 18 | python | LOW | tests: open files and stores, a silent `raising=False`, an unchecked sign-in | fixed; the `demo` fixture now closes its store |
| 19 | python, code | LOW | small repeats (`XLSX`, file-name regex, `WHY_MAX`, the filter builder) and `GateError(ValueError)` | one each; `GateError(Exception)`; open questions report no answer time |

**Not changed, and why:**
- **The apostrophe also in Excel cells.** The plan's choice; it is cosmetic (`-1` shows as `'-1`). A test pins exactly which values change.
- **Plan decisions check "no job runs" and then write in separate steps.** The window is milliseconds, and a command-line run is not a job anyway (plan Risks). Accepted.
- **Defect, answer and disposition writes do not wait for a running job,** as planned. A Triage stage could overwrite a person's change in that small window. Accepted and recorded.
- **Trace, video and log-JSON evidence downloads are open to every signed-in role.** Only the owner exists until M2.1, which must restrict them to owner and tester.
- **The Requirements page shows the first 200 rows** until Phase B adds "Show more". The response carries `total`, and **Phase B must show it**.
- **The old dashboard's `/p/{slug}/files/{rel:path}`** still serves any type. Phase D removes it.
- **A second review round** of the fixes was not run. The fixes are covered by the tests listed under Verification.

## Record of changes

### Phase A (4 Nov 2026, branch `claude/compassionate-haslett-3eb339`)

**Built as planned.**
- **Store per request (#16).** `orchestrator/projects.project_store` and `api/routes_projects.store_or_404` / `project_or_404`. Every route moved; an AST test refuses `open_project`, `open_or_404` or `Store(` in any `routes_*.py`. `store_or_404` also turns a gate refusal (`GateError`) and `Busy` into the answer, so every gate route answers alike.
- **Address check (#19).** `projects.address_problem` is the one rule: `ProjectIn` (422), `create_project` and the old `/new` form (422). It refuses any user name, not only `user:password@`, and never repeats the address.
- **Change log.** `orchestrator/gates/changelog.py`: `who`, `clean_why`, `record` (`agent="person"`), `page`, `last`. `by=` on `answer_question`, `approve_heal` and `set_disposition` (keyword-only, default "dashboard").
- **Services** in `orchestrator/gates/`: `questions`, `plan` (with imported cases), `defects`, `requirements`, `summary`, `files`, plus shared `need_why` / `known_ids`.
- **Routers:** `routes_questions`, `routes_plan`, `routes_defects`, `routes_gates` (requirements, change log, gate counts). `schemas_gates.py` sets ids by pattern and count, decisions from fixed lists, `extra="forbid"`, reasons of at most 500 characters, and lists of at most 200 rows.
- **Exports.** `util.spreadsheet_safe` in `case_export.workbook`, `triage.export_csv` / `export_zoho_csv` and `requirements.write_rtm`. The Jira CSV's evidence paths are relative to the project. Each download runs the engine's writer into a temporary folder of its own (`gates/exports.py`), so `reports/` is never touched by a download (review row 5).
- **`replan`** (`agentqa/replan.py`, 4 lines in `cli.py`'s parser) and the run-shell line "Test plan approved earlier, on <at> by <who>" (2 lines in `_plan_gate`; `cli.py` 778 → 785).
- **Logged:** starting a run with `auto_approve`.
- **Rate bucket:** `SHOT_PATH` now also covers `defects/{did}/evidence/{n}`. Visual and assist images join it in Phase C.
- **Fixture.** `tools/make_gates_fixture.py` writes `backend/tests/fixtures/gates/` (rows.json about 530 KB, 6 images of at most 3 KB each) and `frontend/src/test-fixtures/gates-demo.json`.

**Where the code disagreed with the plan, and what was done.**
1. **`replan` and the policy (fact 5 was incomplete).** `reconcile` without `--policy` uses `project.yaml`'s policy (the demo's is `ask`). No run stores the policy it used. So `replan` without `--policy` reconciles as a pipeline started from the app does (that also passes no policy). `replan --policy …` exists on the command line, and the runs API passes `policy` for `scope: replan`. A pipeline started *with* `--policy srs_wins` (the unattended demo) and then re-planned from the app would reconcile with `ask`, re-opening the divergences the policy had decided. "Apply my answers" stays `{}` as planned; Phase B's page should say the policy it uses.
2. **`projects.summary()` never closed its store** (the projects list and the project page). It now closes it, in the same fix as #16.
3. **The requirements list moved** from `routes_wizard.py` to `routes_gates.py`, where the plan puts it. The response keeps `{requirements, documents}` and adds `total` and `disposition_note`; the default `limit` is 200.
4. **A disposition needs a reason** for all four values: each replaces AgentQA's computed status with a person's claim, so it is treated as an override (decision 4).
5. **Defect note format.** The note reads `"<who>: <decision> (<why>)"` rather than `"<who>: <why>"`, so a confirmation without a reason still says what was done.
6. **Imported-case decisions** answer 422 when `ids` is empty (except `approve_ready`). "Review" counts as undoing, so it needs a reason. An unknown case type on `POST plan/types/{ctype}` answers 422.
7. **Roles floor.** Phase A has 24 write routes (15 before, plus 9 decisions). The plan's 30 counts Phase C's writes, so the floor is 24 now and rises in Phase C.
8. **Fixture contents.** A No-AI demo run proposes no heals, and a first run's visual rows are all `baseline`. The fixture therefore has no heals or changed screens; Phase C's own copies make them, as the plan's demo rule already says. Evidence kinds are screenshot `.png`, trace `.zip` and log `.json`; no video.
9. **Fixture checks.** Besides the YAML passwords, the tool refuses the one-time codes the run actually received: the mock inbox keeps each one in `.agentqa/inbox.db`. A pattern for "six digits after OTP" was tried and dropped: it matched the Test Designer's deliberate wrong OTP and a postal PIN code. Paths and secrets are checked on each value, not on the JSON text, where a regex's `\b` looked like a network share.
10. **The old dashboard's downloads** call the same engine functions, so they also get safe cells and relative evidence paths. They still include drafts until Phase D removes them.
11. **`triage.py` is 411 lines** (was 400; ceiling 800).

**Pinned (`test_gates_engine.py`), so later phases do not trip on them.**
- `designer.approve(s, reject=True)` with no ids or types rejects every proposed case *and* marks the plan approved. The service never calls it that way, and `ids` is never empty.
- `answer_question` keeps the label in a JSON column, so a numeric label reads back as a number. The API returns it as text.
- `set_defect_status` writes no log; the service writes one row per defect.

**"Not yet verified" items now settled.**
- openpyxl does store a leading `=` as a formula (`test_spreadsheet_safe.py`).
- A gated run, with the ready imported cases approved at the gate, still gives **19/19 and 0 extra** (approved through the engine at the gate, the same functions the Test plan page calls).
- The demo reaches the plan gate in about 40 s of stage time (No-AI).
- Evidence kinds are as above.

**Still not verified:** `yamledit._commit`'s check and whether `generator` runs approved imported cases (both Phase C / sitting 1).
