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

### Phase B (4 Nov 2026; the built app on throwaway servers with a generated owner; No-AI, nothing spent)
- **Tests first:** every new test was red before its code: `lib/gates.test.ts`, `QuestionCard`, `Questions`, `TestPlan`, `Defects`, `ChangeLog`, `NavLinks`, `Requirements`, `LiveHeader`, `App` (the page frame), the extended `Project` test, and the backend `policy`, policy-hardening and evidence-origin tests.
- **Frontend:** **367 Vitest in 44 files**; `tsc -b` and `oxlint` (with jsx-a11y) clean. `make web-build` puts each gate page in its own file (Questions 9 kB, Test plan 12.5 kB, Defects 6 kB, Change log 2 kB).
- **Backend:** 665 tests; **663 passed** in the full run while both browser checks ran beside it. The 2 others are the Live View stream-slot tests Phase A recorded as timing-sensitive under load (`test_api_live_ws.py::test_leaving_in_the_middle_of_a_run_frees_the_slot`, `test_live_ws_real_server.py::test_an_sse_stream_closed_early_frees_its_slot`); their two files then passed alone, 28/28, and Phase B changes no Live View code. pyflakes clean; contrast **244/244** (two new pairs; the pinned count in `test_check_contrast.py` follows).
- **`make ui-check`:** green at 320 / 375 / 768 / 1 024 / 1 200 / 1 440 px in light and 375 / 1 440 px in dark for 13 pages, the four gate pages included, with the demo project holding the gates fixture.
- **`make gates-check`:** green, before and after the review fixes. As the owner:
  - answered two questions (one with a value) and reopened one with a reason;
  - rejected three cases with a reason, approved a whole type, approved the 9 ready imported cases, approved the plan, and saw "Generate and run";
  - confirmed 17 defects and rejected 2 with a reason;
  - marked FR-01 "tested by hand" with a reason;
  - downloaded the test-case Excel and the RTM (both open), the Jira CSV (header, 17 rows: no drafts and no rejected) and the Zoho CSV (byte-order mark and its Title column);
  - found every action in the change log with "ui-check@example.com (owner)" and each reason, by the API and on the page.
  - As a Viewer (a pass minted with the throwaway secret): no fields or decision buttons on the four pages, the downloads there, and a write answered 403 `read_only`.
- **Demo regression:** not re-run. Phase B changes no engine code (a read-only `policy` field and an origin check on a file route); the rule applies to engine commits.
- **Acceptance sitting 1:** run with the owner on 4 Nov 2026 (below).

### Sitting 1 (4 Nov 2026, with the owner; branch at `f1ad631`; No-AI, nothing spent)
A throwaway server from `sitting1_review_server.py` (generated owner `ui-check@example.com`, `AGENTQA_HOME` and the
projects folder in the session scratchpad, so the owner's own sign-in, vault and data were never read), the demo
portals on 8800/8810, the built app. The owner, Akash, watched in the browser pane and made every decision and wrote
every reason; the assistant clicked for him. All seven steps passed.
1. **Run full pipeline, switch off:** the run stopped at "Test plan approval: waiting for you" after about 40 s
   (5 of 12 stages); badges Questions 15, Test plan 215; the Live View linked each gate.
2. **Gate 1:** NFR-01 answered "Enter a precise rule" with the value "Every page loads within 3 seconds on the test
   environment."; "/apply" answered "Yes: block these roles"; FR-12 "Use the proposed interpretation"; the "/apply"
   answer reopened with "I need to confirm this with the department first." (13 open · 2 answered). "Apply my answers
   and re-plan" ran reconcile + design in 3 s with the remembered rule ("the requirements document wins"). The plan
   did not change: see finding S1.
3. **Gate 2:** TC-0022 rejected with "Already checked by hand in the last release."; the 9 ready imported cases
   approved; the plan approved (205 approved, 1 rejected); the Excel download checked in the page (200,
   `Demo-Certificate-Portal-test-cases.xlsx`, 30 kB, a zip); "Generate and run" ran generate → report (~6 min).
4. **`check_demo` before Gate 3:** **19/19 seeded bugs, 0 unexpected**, on the gated run with the owner's answers, a
   rejected case and the imported cases (settles "a gated run with imported cases approved still gives 19/0").
5. **Gate 3:** DEF-017 (home image without alt text) rejected with "Known issue, accepted by the department for this
   release."; the other 18 confirmed; the Zoho CSV checked in the page: byte-order mark, its header, **18 records**
   (DEF-017 absent), all "Open".
6. **Change log:** 30 rows, every person's action as "ui-check@example.com (owner)", the three reasons beside their
   rows, the two downloads, the agents' "first design".
7. **Viewer look** (a pass minted with `check_app.SECRET` for this server only, after `POST /auth/logout`): Project,
   Requirements, Questions, Test plan and Defects show no fields or decision buttons (filters, "Include drafts" and the
   downloads only); a write answered 403 `read_only` "Your account can watch but not change anything".

**The owner's findings** (from trying v9's test server before the sitting; recorded in his words, decided at the
sitting: **a design slice of its own right after M1.4**, planned with a mock he approves before any code):
| # | Finding |
|---|---|
| O1 | "The live view should reflect the activities of all agents working, not only the browser session." |
| O2 | "The user interface is very much basic": multiple themes, animations; using it should be fun, not a boring job. |
| O3 | "The agent cards to have numbers and should be of the same size." |
| O4 | "I need the workflow and the chain of commands running to visualize." |

O3 touches `AgentBoard.tsx` and `board.ts`, which the follow-up branch `claude/nervous-sutherland-913fae` changes: the
slice starts after that branch merges. O2 widens his 3 Nov choice ("purposeful motion only", five accents): the
slice's plan must re-ask it with a mock, flat (never glass or soft shadows).

**Found at the sitting** (fixed test-first below unless marked):
| # | Severity | Finding | Decision / fix |
|---|---|---|---|
| S1 | MEDIUM | Answers to "A vague requirement" questions (`ambiguous:<req>`) are stored but no stage reads them (v0.8 engine): "Apply my answers" leaves the plan as it was, and the Requirements page still says NFR-01 is "Not testable: vague wording" after the owner gave a 3-second rule | **The owner, 4 Nov 2026: honest words now, real later.** Now: the Questions page says such an answer is a note for checking by hand; the Requirements page and the RTM show the answer instead of "vague wording" / "waiting for a person". Later, in its own plan: a typed rule becomes a tested rule and "use the suggestion" a hand-check case |
| S2 | MEDIUM | The Defects page has no "Select every defect shown" (the Test plan has one): confirming 18 defects took 18 ticks | the same labelled box as the Test plan |
| S3 | LOW | Change log: on an answer row the "Why" column holds the question's text, not a person's reason; a question without a requirement reads "answered … for the plan" | the question shown as the question; "for the plan" only where it is true |
| S4 | LOW | Decision bars: the reason panel opens inside the sticky bar and reflows it; blue vertical rules beside "Reject" and "Back to review" read as stray lines | see the fix record |
| S5 | LOW | A Viewer's "What needs you" says "13 questions to answer" though a Viewer cannot answer | worded for who is looking |

**After the fixes (5 Nov 2026):**
- **Tests first.** The first-round tests were red before their code:
  - backend `test_answer_notes.py`: 5 red;
  - frontend: 6 red in 5 files. The WhyButton class test passed at first because Vitest reads `?raw` CSS as empty; it was rewritten to name the class, then went red.
- **The review round's tests were written before its code.** The revised backend tests: 9 red, then green; the precedence and reopen tests already passed and now pin that behaviour. The frontend review tests were not run separately while red.
- **Backend:** **689 passed** in the full suite; pyflakes clean.
  - In an earlier full run beside the frontend suite, `test_api_live_ws.py::test_resuming_from_a_cursor_sends_only_the_end` failed once, and once more while a reviewer ran tests beside it. Alone it passed 3 runs of 24/24. It joins the two load-sensitive Live View stream tests Phase A and B recorded. No Live View code changed.
- **Frontend:** **383 Vitest in 46 files**; `tsc -b` and oxlint clean; `make web-build`.
- **Browser checks:** `make ui-check` green (six widths, light and dark); `make gates-check` green (owner, then Viewer).
- **In the sitting's server** (frontend rebuilt): a Viewer's Project page read "What is waiting · 13 open questions".
- **Demo regression, unattended, on a fresh copy** (engine files changed): **19/19, 0 unexpected** (214 tests: 184 passed, 30 failed; the failures became the 19 seeded defects and nothing else).

### Phase C (5 Nov 2026; No-AI, nothing spent; throwaway servers with a generated owner, never the owner's sign-in)
- **Pinning tests first.** `test_assist_engine.py`'s 8 pinning tests were green on the unchanged `assist.py`; its 6
  hardening tests were red, then green. `test_yamledit.py`: 5 hostile-value tests red, then green.
  `test_api_{visual,heals,assist}.py` were red (52 failures and errors) before the routers existed.
- **Backend:** 773 passed in the first full run; **809 passed** after the review fixes; pyflakes clean. The review
  round's tests were all red first: 7 engine, 15 API, 8 old-dashboard (`test_dashboard_assist.py`), 2 YAML, 1 for the
  503 on an unreadable database.
- **Demo regression, unattended, on a fresh copy** (`pipeline --policy srs_wins --auto-approve`, then
  `tools/check_demo.py`): **19/19, 0 unexpected**, once on the first build and again after the review fixes (214 tests:
  184 passed, 30 failed, the failures becoming the 19 seeded defects and nothing else).
- **`tools/e2e_assist.py`** (the real take-over on the hard-login demo: Malayalam first, the unlabelled icon, the mock
  inbox; portals 8820/8830, inbox 8025, a generated owner, the signed-in API with the CSRF header): **27/27**, once on the
  first build and again after the review fixes. The second run typed the one-time code with "hide" unticked; the final
  scans found neither the code nor the clerk's password in any log, recording, the vault or the 658 kB database file.
- **App, first build:** 436 of 440 Vitest passed in the full run; the 4 others were 5-second timeouts under load
  (Live, Requirements, Defects pages) and passed alone (33/33). `tsc -b` and oxlint clean; contrast 244/244;
  `run build` (Visual 5 kB, Heals 4.5 kB, each loaded with its route). `check_app.py` timed out once waiting for the
  network to go quiet while three reviewers ran tests, then passed alone at six widths in light and dark with the two
  new pages and the help box's dock and dialog. `check_gates.py` with its Phase C part (`check_gates_c.py`) green.
- **App, after the review fixes:** **486 of 488 Vitest in 54 files** in the full run; the 2 others were 5-second
  timeouts under load (Live, Defects) and passed alone (28/28). `tsc -b`, oxlint and pyflakes clean; contrast 244/244;
  `run build`. **`check_app.py` green** (six widths, light and dark) and **`check_gates.py` green**: as the owner the
  three gates, the downloads, the help box (dock within 3 s, the tab title, an answer), take-over (a scaled click, a
  centre click within 2 px and an off-centre one within 1 px of the picture's own box, typing hidden by default, the
  typed text gone from the database file once the script acting as the agent ran it), Pause and Resume, visual review
  (one approved, one reported), heals (one approved, one rejected), the change log; the page behind the dialog inert,
  focus back on the opener or the `h1`, a drag released on the backdrop keeping the dialog, the dock's clearance on a
  phone; then a Viewer with no controls. `test_check_app_env.py`: the throwaway server sees no AI key, has its own home
  and a fresh vault key.

## Review (fresh context)

### Phase C (5 Nov 2026; reviewed as lock-marked)
**Backend.** `security-reviewer` (take-over surface, assist secrets, file routes, the heal's YAML write), `python-reviewer`
and `code-reviewer` (against this plan) read the change in fresh contexts and probed it with throwaway scripts (a dying
browser, a reader holding the database, 60 commands at once, fuzzed YAML values). Nothing was CRITICAL. Every HIGH and
MEDIUM was fixed; each fix's test was written first and failed first (7 engine, 15 API, 8 old-dashboard, 2 YAML tests).
| # | Found by | Severity | Finding | Fixed |
|---|---|---|---|---|
| 1 | security | HIGH | the old dashboard's help box, visual review and heals skipped every Phase C rule: a Viewer saw the screenshot, a 2 MB `type`, a click at (99999999, -5) and 300 queued commands were accepted, decisions had no who or why | the old help-box routes call `gates.helpbox` with the signed-in person (the API's guard hands it on as `request.state.agentqa_user`) and the new schemas; a Viewer gets an empty list and 403 on the screenshot; the old visual and heal pages and their POSTs send the person to `/app/projects/{slug}/visual` / `heals` and decide nothing (`test_dashboard_assist.py`) |
| 2 | security, python, code | HIGH / MEDIUM | a one-time code typed into a plain box with "hide" unticked was echoed (`Typed '…'`) into the command row, the help-box log and the recording, and stayed in the database file | typed text is never echoed: always "Typed N character(s)"; `e2e_assist.py` now types the code unticked and its scans still find it nowhere |
| 3 | python | HIGH | when the browser died during a take-over the question stayed "pending" for an hour and its typed text survived | `takeover` ends in `try/finally`: the question is expired, every typed command wiped, its screenshot deleted |
| 4 | code | HIGH | a `confirm` question (the visual check's "Check the expected result", with two choices) refused `{option}` | `confirm` takes option, ok or skip |
| 5 | security, python | MEDIUM | a checkpoint held up by a reader stalled the agent for the 30 s busy timeout, and nothing tried again | `assist_wipe.checkpoint` waits at most 1 s; the once-a-minute sweep always ends with one |
| 6 | security, python | MEDIUM | a secret answer racing the time-out stayed readable (the expiry overwrote "answered"); the sweep looked at "answered" rows only | the expiry is conditional and re-reads; unread secret answers are wiped after 60 s in any status |
| 7 | security | MEDIUM | typed commands of a dead agent waited an hour | any typed command waiting over 60 s is wiped and marked "dropped" |
| 8 | security, python, code | MEDIUM / LOW | the first answer did not always win, and the 20-command cap could be passed by requests at once (60 of 60 queued) | `assist_wipe.atomic` (`BEGIN IMMEDIATE`): the answer is a conditional `UPDATE`, the command an `INSERT … WHERE EXISTS … AND COUNT < 20` |
| 9 | security | MEDIUM | Cancel or Continue did not stop a batch already fetched | the status is checked before each command |
| 10 | security, python | MEDIUM | `approve-all` that failed part-way left approved baselines with no who or why | the change-log row is written in `finally`; a copy error answers 503 `file_error` |
| 11 | security | MEDIUM | the YAML edit replaced the first match in the workflow, not the heal's own step and key; a rename onto an existing key lost a value | `replace_in_workflow(…, step=, key=)` tries each match and keeps only the intended one; a rename onto a key the form already has is refused |
| 12 | python | MEDIUM | a locator fix whose rename could not reach `project.yaml` still said nothing | "Could not rename '…' in project.yaml: change it there by hand" |
| 13 | python | MEDIUM | the sweep decoded every historical row once a minute (3.2 s at 25 000 rows) and a locked database turned `GET /assist` into a 500 | JSON filters in SQL; the sweep runs after the read and never fails the list |
| 14 | python | MEDIUM | the list read the oldest 20 questions, through a read-write connection, and swallowed errors | the newest 20 (shown oldest first), `mode=ro`, errors logged |
| 15 | python | MEDIUM | the production warning failed open | an unreadable flag counts as production |
| 16 | python, security | MEDIUM / LOW | a question's last screenshot was kept for ever (a code may show in a plain box) | deleted when the question ends; the sweep deletes leftovers |
| 17 | python, code | MEDIUM | `heals.decide` could apply a fix twice on a double-click | one decision at a time (a lock) in heals and visual review |
| 18 | code | MEDIUM | tests missing for production true, the once-a-minute sweep, Pause through a command-line run, approve-all while a run goes | added |
| 19 | security | LOW | `/x/../admin`, `//admin`, `/%61dmin` passed the goto scope check | decoded, and `.`/`..` steps, `//` and backslashes refused, before the scope check |
| 20 | several | LOW | command-line runs did not block visual and heal decisions; one pruned recording folder hid every command-line run; `shot_v` capped at 10 000; the screenshot name's id not checked against the question; uncapped heal reason and case ids; a parity test that compared the moved code with itself; `KEYS` not tied to the schema's list; a test that returned early; dead constants; raw U+2028/U+FEFF in a regex source; `assist.py` 560 lines; three functions of `e2e_assist.py` over 50 lines | fixed (`gates.run_going`; per-folder errors; the parity test now compares with the v0.8 code kept word for word in the test; `assist.py` 405 lines, the wipe, the screenshots and the recorder in `assist_wipe.py`, `assist_screen.py`, `assist_recorder.py`) |

**Not changed, and why:**
- **`yamledit` writes CRLF on Windows and not atomically.** It did so before Phase C for every edit, and a failed check
  writes nothing. A separate small change can make the write atomic.
- **Keys such as `on`, `yes` or `null` cannot be renamed into a fill block** (YAML reads them as values); the edit is
  refused and the note says to change it by hand.
- **`approve_row` copies the current picture as the layout too when its name lacks `-current.png`.** That is the v0.8
  behaviour, kept so the move stays a move; the runtime always writes `-current.png`.
- **`report_row` turns an earlier report of the same screen back to draft,** as v0.8 did.
- **A visual key outside `^[\w@.\-]{1,200}$`** (the designer builds keys from raw paths) is listed but cannot be decided
  (422, or "skipped" in approve-all). No demo screen has one.
- **Values recorded during a take-over reach other places by design:** `login_flow` names the steps it learned in the
  live feed, and the Explorer keeps navigation steps in the vault (encrypted). A box AgentQA does not recognise as secret
  is treated as test data there. Recorded for M2.x hardening.
- **A Viewer sees who paused** (`paused.by`, an email); the Change log page shows the same to a Viewer.
- **`visual.item` checks three pictures per row** (50 rows by default, at most 200). Not measured on Drive; revisit if
  the Visual review page is slow there.

**App.** `typescript-reviewer`, `react-reviewer` (with a WCAG 2.2 AA pass) and `security-reviewer` (untrusted text,
typed secrets, the take-over guard rails) read the app in fresh contexts. Nothing was CRITICAL. Every HIGH and MEDIUM
was fixed, and the LOW items too; each fix's test failed first, except where the last column says otherwise. What jsdom
cannot see (`inert`, real focus return, a drag released on the backdrop, the dock's clearance on a phone) is checked in
the browser by `check_gates_c.py`.
| # | Found by | Severity | Finding | Fixed |
|---|---|---|---|---|
| 1 | typescript | HIGH | on Android Chrome `new Notification()` throws inside an effect, and the dock sat outside any error boundary: the whole app would blank | caught, and the dock has its own `ErrorBoundary` in the Shell |
| 2 | react, typescript | HIGH / MEDIUM | focus was not returned when the dialog was minimised or answered (the page was still inert) (2.4.3) | the `Modal` removes `inert`, then returns focus to the button that opened it (the dock's or the Live View banner's), else the page's `h1` |
| 3 | react, typescript | HIGH / LOW | the open question's id was kept across projects: another project with the same id popped its dialog open | kept per project and cleared when the dock unmounts |
| 4 | react | HIGH | "Approve fix 3" did not contain the visible "Approve the fix" (2.5.3) | "Approve the fix 3" |
| 5 | react | HIGH | three pollers on the Live View (dock, banner, page) tripled the requests | the dock polls; the others read the same query |
| 6 | react | MEDIUM | a drag from the type box released on the backdrop closed the dialog and lost the typed text and the production tick (also the Lightbox) | `useBackdropClose`: closes only when the press and the release are both on the backdrop |
| 7 | react | MEDIUM | the dock could cover the last controls on a phone (2.4.11) | the page's bottom room follows the dock's measured height (`--dock-h`) |
| 8 | react | MEDIUM | sent commands and Pause gave no status; Pause lost focus while pending (4.1.3) | a polite status line ("Sent: Enter"); `aria-disabled` while pending |
| 9 | react | MEDIUM | a box chip's "filled" mark was not in its name; the screenshot had no keyboard route and was silent to a screen reader | "(filled)" in the name; the screenshot is described by the chips and says to use them |
| 10 | react | MEDIUM | the announcement sat inside the inert page, was repeated on every return and named only the first new question | outside the inert page, remembered per project, every new question |
| 11 | react, typescript | MEDIUM / LOW | `useCallback` depended on the whole mutation, so the memoised cards re-rendered on every poll | depends on `mutate` |
| 12 | security | MEDIUM | a password clicked on the screenshot (not chosen from the chips) was shown in clear on screen | the take-over box hides what is typed by default ("Show what I type" opts out); the chosen box resets on a screenshot click, Tab, Enter, Back and an address |
| 13 | security | MEDIUM | the browser checks' throwaway server inherited the owner's environment (his AI key folder, any `*_API_KEY`) | its own `AGENTQA_HOME`, a fresh vault key, no `*_API_KEY`; both checks refuse to run if the server can see a key (`test_check_app_env.py`) |
| 14 | typescript | MEDIUM | a failed poll read as "nothing is waiting" closed an open take-over | the server answers 503 when it cannot read (backend test red first); the page keeps the dialog on an error (its test passed at once: the query already kept its data, kept as a guard) |
| 15 | typescript, security | MEDIUM / LOW | a double-click sent two real clicks; commands could reorder; the production tick was only an HTML attribute | double-clicks ignored, the screenshot disabled while a command is on its way, commands one at a time (`scope`), and the send checks the tick |
| 16 | typescript, security | MEDIUM / LOW | spaces in a password or code were collapsed and trimmed | control characters are removed, nothing else |
| 17 | typescript | MEDIUM | a click was scaled against the button's border box, not the picture (2–4 px off at the edges) | the picture's own box, clamped inside the screen; the browser check's tolerance tightened to 1–2 px |
| 18 | several | LOW | `//host` and `/../` in the address box; text cleared before a refusal; `shot_v` capped at 10 000; one 404 stopped polling; approve-all hid "skipped"; Yes/No beside a confirm's own choices; no "Scroll up"; two Pause buttons on the Live View; a test that never restored `scrollIntoView`; typed text kept in the mutation cache; password boxes offered to password managers; bidi controls and inline paths not isolated; focus lost when the notify button went; `role=alert` on a new dialog; empty chip labels; the phone's safe area; "missing" said for any picture error | fixed |

**Not changed, and why:**
- **Viewing an older run in the Live View while paused** shows no Resume there (the dock's Pause hides on the Live
  View, and the page's shows for the newest run only). Resume is on every other project page and on the newest run.
- **oxlint's React rules** (`rules-of-hooks`, `exhaustive-deps`): the config lists only `jsx-a11y`, which may switch the
  default plugins off (react review, unverified). A config change for the whole app, not Phase C: proposed as its own
  small change.
- **A 1 px border error is about 1.6 px of the agent's screen,** below what a real pointer resolves; only the Vitest
  test pins it exactly.

### Sitting 1 fixes (5 Nov 2026)
`python-reviewer`, `react-reviewer` (with a WCAG 2.2 pass) and `code-reviewer` read the fixes for S1–S5 in fresh contexts.
None found anything CRITICAL. Every HIGH and MEDIUM was fixed; its test was written before the code.
| # | Found by | Severity | Finding | Fixed |
|---|---|---|---|---|
| 1 | code | HIGH | The first fix gave an answered vague requirement the disposition "manual", which the Requirements page shows as "tested by hand": no one had tested it | it stays **"not_testable"** (AgentQA cannot test it yet) with the answer in its note, `answered "…": check it by hand (AgentQA does not test this answer yet)`; the coverage buckets are as before the answer |
| 2 | react | HIGH | "Select every defect shown" also took defects sent to a tracker, which have no box: the server refuses the whole batch (409 `exported`) | `isDecidableDefect`, shared by the card and the box; a test with an exported defect |
| 3 | python | HIGH | An answered contradiction reached only the first requirement it names; the others kept "an open question must be answered first" with nothing left to answer | `requirements.answered_disposition`: the answer reaches every requirement in the contradiction |
| 4 | python, code | MEDIUM | The new branch skipped unanswered contradictions and `Ambiguous` rules | any unanswered contradiction or unresolved rule (`Ambiguous`, `Divergent`, `Proposed`) keeps the requirement open |
| 5 | python, code | MEDIUM | The report re-derived the note with weaker rules than the Requirements stage (a person's "out of scope" still read "check it by hand") | the report shows the stored note (`is_hand_check`) |
| 6 | python | MEDIUM | "Not testable: leave for manual review" turned into "Manual test only", and coverage counted it as a gap | solved by 1 |
| 7 | python | MEDIUM | `reconciler._choice` raised on valid JSON that is not an object (`[1]`, `null`), and now runs inside the Requirements stage and the report | reads as no choice |
| 8 | python | MEDIUM | A stale answer (the requirement no longer vague) still counted; two answers for one requirement overwrote each other | a vague answer counts only while the requirement is vague; answers are joined with "; " |
| 9 | react | MEDIUM | With `keepPreviousData`, a tab change or a refresh under a selection could decide rows no longer shown | `inView`: the bar's count and the ids sent are the selected rows shown now (Defects and Test plan) |
| 10 | react | MEDIUM | "Select every … shown" reads as "all of them" on a list that shows the first 50 or 30 | "Select the 19 defects shown", "Select the 30 cases shown" |
| 11 | react | MEDIUM | With some selected the box read as plain "not checked" (4.1.2) | part-ticked (`indeterminate`); a click selects all |
| 12 | react | MEDIUM | The note said "Your answer" to a Viewer and was not read with the options | "An answer to this question" for a Viewer; `aria-describedby` on the radio group |
| 13 | react, code | MEDIUM / LOW | The change log's "The question:" depended on an English prefix tested in the page | `whyIsQuestion` in `lib/gates.ts` with unit cases; the engine's "answered '…'" wording is pinned by `test_gates_engine.py` |
| 14 | all three | LOW | curly quotes in the RTM CSV and no ellipsis; the page path in the change text uncapped; `needsYou`'s boolean defaulted; visual and heals items not worded for a Viewer; an unclosed file and casts in tests; a duplicated Viewer check; the `requirements` import name in `gates/questions.py` | fixed |

**Not changed, and why:**
- **`requirements.check()` is about 60 lines, and `requirements.py` is 483 lines.** Both were over the targets before this change; the ceiling is 800. The new rule went into `answered_disposition` rather than growing `check()`.
- **`reconciler._choice` stays private** and `requirements` imports it in one place; making it public would touch the engine's other callers.
- **S4's reflow.** The reason panel opens in place inside the sticky bar. That is Phase B's design (Record → Phase B item 8: a non-modal panel in place, the bar at most 60 vh). With the stray rules gone, the bar reads as one group. Sitting 2 can reopen this.
- **`GateCounts` while the signed-in role loads.** `RequireSignIn` holds every page until it has loaded, so the heading never flips in the app.
- **A test that parses `wizard.css`.** Vitest reads `?raw` CSS as empty, and the app's TypeScript has no Node types, so the WhyButton test names the class instead.
- **The Test plan's "what the plan does not cover" panel and the acceptance verdict list neither `not_testable` nor `manual` requirements.** This was so before, and the fix does not widen it.

### Phase B (4 Nov 2026)
`typescript-reviewer`, `react-reviewer` (with an accessibility pass, WCAG 2.2 AA) and `security-reviewer` (untrusted text) read the change in fresh contexts. Security: approve, no CRITICAL, HIGH or MEDIUM. Every HIGH and MEDIUM was fixed test-first.

| # | Found by | Severity | Finding | Fixed |
|---|---|---|---|---|
| 1 | typescript | HIGH | `PlanGaps.unread` and `production` are objects in the API, typed as strings: a real unread document blanked the page | types as `plan.py` sends them; "Scan.pdf (no text layer)", "Not run on production: …"; a test with real-shaped gaps |
| 2 | react, typescript | HIGH | no error boundary above the lazy routes: a stale chunk after an update or a page that throws blanked the app | `PageFrame` (ErrorBoundary + Suspense, reset on navigation; `App.test.tsx`) |
| 3 | react | HIGH | the disposition menu opened the reason panel on change, so arrow keys could not reach the last options (WCAG 3.2.2) | the menu changes nothing; "Set…" opens the reason |
| 4 | react | HIGH | "Select every case shown" sat in the header row that is hidden under 1 024 px | a labelled box above the table at every width; `scroll-padding-bottom` under the sticky bar (2.4.11); the bar scrolls inside 60 vh |
| 5 | react, typescript | HIGH | the Test plan read "a run is going" from a query nothing refreshed; refusals that mean "out of date" did not reload | the polled gate counts decide; `useRefreshWhenRunEnds` reloads Test plan, Questions and Defects when a run ends; `isStale` refusals reload |
| 6 | react | MEDIUM | a reason panel outlived its selection ("Reject 0 cases") | the panel hides when its button is disabled and is keyed by the count |
| 7 | react, typescript | MEDIUM | focus came back through `document.activeElement` (body in Safari; stolen in StrictMode dev) | the button that opened the panel refocuses itself |
| 8 | react | MEDIUM | the decision bar came before the list in reading order | after the list (still sticky) |
| 9 | react | MEDIUM | each tick re-rendered every row | `CaseRow` and `DefectCard` memoised with stable callbacks |
| 10 | react, typescript | MEDIUM | no error or empty state for the cases; tab switches blanked the counts and reset "Include drafts" | messages; `keepPreviousData`; the downloads card always mounted |
| 11 | all three | MEDIUM / LOW | the case selection survived a filter change, so hidden cases could be decided | cleared on every filter change |
| 12 | typescript | MEDIUM | select-all after "Show more" could send more than the API's 500 ids | decisions go in slices of 500 |
| 13 | typescript | MEDIUM | an older error hid a newer one; casts `as CaseDecision` / `as Disposition` | one current error, cleared on the next decision; `DecisionBar<D>` generic; the menu value looked up |
| 14 | react | MEDIUM | "Reopen" and "Save answer" repeated 15 times with the same name; Save disabled without a reason | "Reopen question N"; Save described by its question and saying what is missing |
| 15 | react | MEDIUM | results were not announced and focus fell to the page when a card left the list | one always-present live region per page ("Answer saved.", "The test plan is approved."); focus to the list's or the Approval heading |
| 16 | react, typescript | MEDIUM | polling stopped for good after one error | 60 s after a blip; stops only on 401 / 403 / 404 (`gatePollMs`) |
| 17 | security | LOW | `policy:` left empty in project.yaml answered 500; any text passed through | read safely; unknown values read "ask", as the Reconciler treats them |
| 18 | security | LOW | the tested site (same-site, another port) could probe which evidence exists | the origin check on the evidence route too |
| 19 | security | LOW | right-to-left overrides in application text could reorder what a reviewer reads | `unicode-bidi: isolate` on that text |
| 20 | security | LOW | no tests for a hostile defect, a `BR/01` id or the address as text | added |
| 21 | several | LOW | a value sent for an option without one; a failed fetch worded generically; exported defects selectable; a Viewer told about buttons they lack; heading order on Defects; no "Select" column name; "verb:" labels; counts not refreshed after starting a run; "0 cases · waiting" with no plan | fixed |

**Not changed, and why:**
- **Explicit table roles on `.rows`.** The build targets current engines (`cssTarget` Safari 17.5), which keep table semantics under `display: block`, and oxlint flags the roles as redundant. A screen-reader check in sitting 1 can reopen it.
- **A requirement id of exactly `.` or `..`** cannot be dispositioned (the browser collapses the segment). Only a hostile document does this; M1.5's ingestion should refuse such ids.
- **LOW items kept:** the reason is lost when a confirmed decision is refused; several reason panels can be open at once; the selection boxes are 17.6 px (they pass WCAG 2.5.8 by spacing); list roles after `list-style: none` in Safari; the scrolling `<pre>` is not focusable; the breadcrumb is not a `<nav>`; raw case-type names; three page components are 55–60 lines of JSX.
- **A second review round** was not run; the fixes are covered by the tests above and both browser checks, re-run after them.

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

### Phase B (4 Nov 2026, branch `claude/pensive-zhukovsky-481d45`, on Phase A `8c9d651`)

**Built as planned.**
- **Logic:** `lib/gatesApi.ts` (requests, types, download and evidence addresses), `lib/gates.ts` (pure: selection, which decisions need a reason, export links, who in words, the policy in words, error words, nav badges, "What needs you", the Live View's gate text), `lib/useGateCounts.ts` (one shared `GET /gates` query: every 5 s while a run goes, 30 s otherwise, stops on an error).
- **Pages**, each loaded with its route (`App.tsx`, `lazy` + `Suspense`): `pages/gates/{Questions,TestPlan,Defects,ChangeLog}.tsx`, at `/projects/:slug/questions`, `/plan`, `/defects`, `/changes`.
- **Components** in `components/gates/`: `QuestionCard`, `ReasonDialog` (+ `WhyButton`), `DecisionBar`, `CaseTable`, `TypeTable`, `PlanSummary`, `PlanApproval`, `DefectCard`, `ExportLinks`, `DispositionControl`, `GateCounts`, `GateTop`.
- **Navigation:** Questions, Test plan, Defects (each with a badge whose spoken name says it, e.g. "Questions, 15 open") and Change log.
- **Project page:** the "What needs you" card; the switch reads "Approve the test plan automatically (demos)", is **off** by default and says what it does.
- **Requirements page:** dispositions limited to the four values, always with a reason; `total` and "Show more" (200 at a time); the RTM download.
- **Live View:** the pipeline card's gates are links to their pages; for the newest run they add what is open now ("15 asked · 3 open", "19 found · 2 to confirm") and the plan gate reads the store, because an approval made in the app leaves no line in the recording (fact 12).
- **Styles:** `styles/gates.css` (111 lines); two new contrast pairs in `check_contrast.py`; `.g-dash` fixed (C12); MASTER §6 records the breakpoint convention.
- **Checks:** `check_app.py` measures the four gate pages (the demo project now holds the gates fixture); `check_gates.py` (`make gates-check`) is the Phase B part.

**Where the code disagreed with the plan, and what was done.**
1. **The API did not say which policy a re-plan uses** (Phase A item 1 asked the page to say it). `GET /questions` now returns `policy` (`divergence`, `inferred_access`) from project.yaml: 5 lines in `questions.policy` and the route, test first (`test_api_questions.py`). The fixture tool writes it too; the frontend fixture was patched by hand with the demo's values.
2. **The Run button and "Apply" use different rules.** `Project.tsx` starts every pipeline with `policy: "srs_wins"`; `replan` uses project.yaml's (`ask` on the demo). After a run from the app, "Apply my answers and re-plan" can therefore bring back questions the run had settled (the 4 "Decided" divergences on the demo). **Decided by the owner, 4 Nov 2026: a re-plan reuses the rule the run used.** The reconcile stage notes its `--policy` in the store (`replan.POLICY_KEY`; none means project.yaml's). `replan` without `--policy` reuses it, and `GET /questions` reports it with `source` ("run" or "project"), so the page says which rule a re-plan will use. The earlier warning is gone; `cli.py` changed one line and stays at 785 lines; tests first in `test_replan.py` and `test_api_questions.py`. A fresh-context `python-reviewer` approved it with one MEDIUM, fixed test-first: the rule is noted only after the Reconciler succeeds, so a failed reconcile keeps it, and one validated reader (`replan.remembered_policy`) serves both `replan` and the page. Unattended demo regression on a fresh copy: **19/19, 0 unexpected**, with `srs_wins` remembered in its store; `make gates-check` green.
3. **Imported manual cases have counts but no list in the API**, so the page offers "Approve the N ready imported cases" (`approve_ready`) only; per-case decisions on imported cases wait for a list route.
4. **Visual changes and heals** are named in "What needs you" without a link until their Phase C pages exist.
5. **Wide tables:** the `.assign` pattern turns into a table at 760 px, where the case table (7 columns) overflowed its card beside the sidebar until about 1 100 px. A `.rows` pattern stacks labelled blocks under 1 024 px and is a table from 1 024 px (the 1 024 / 1 400 convention). The type table shows one "Decided" column instead of three counts so it fits at 1 024 px.
6. **Filter chips** are `.filters` / `.filter`: the existing `.chip` is the Live View's small label.
7. **Requirements page** is one column (sources below the table) and shows section and source file under each requirement, so the disposition menu fits; `api.requirements` and `RequirementsView` were removed (`gatesApi.requirements` replaces them).
8. **The "why?" box is a non-modal panel in place** (role `dialog`, focus into the box, Escape or Cancel closes it and focus returns to its opener). The Lightbox pattern is for Phase C's help dialog.
9. **Defects list** shows the first 200 (the API's cap) and says so when there are more; the demo has 19.
10. **`check_app.SECRET`** is a module constant so `check_gates.py` can mint a Viewer pass for the throwaway server; nothing writes it anywhere.
11. **Test speed:** jsdom's accessible-name queries over 200 rows took more than 5 s under load, so the Test plan tests render 30 of the 206 cases (the "Show more" button proves the rest are there) and that file allows 20 s per test.

### Sitting 1 fixes (5 Nov 2026, branch `claude/pensive-zhukovsky-481d45`, on `f1ad631`)

**What changed, finding by finding** (the findings are under Verification → Sitting 1; the review is under Review → Sitting 1 fixes).
- **S1, the owner's decision "honest words now, real later".**
  - Engine (`agents/requirements.py`): `NOTE_ONLY` (question keys `ambiguous:` and `contradiction:`, which no stage reads), `answered_notes`, `answered_disposition`, `hand_check` and `is_hand_check`.
  - `check()`: a requirement whose open points are all answered with such notes stays **`not_testable`**, and its note quotes the answers and says "check it by hand". A person's disposition and "covered by tests" still come first. Any unanswered contradiction, open question or unresolved rule keeps it at `clarify`.
  - `reporter.py` shows that stored note as the requirement's gap in the HTML report. `reconciler._choice` reads a damaged answer as no choice.
  - API: `GET /questions` items carry `note_only` (the key itself stays private).
  - App: the question card says "Your answer (An answer to this question) is kept as a note for checking by hand: re-planning does not change the automated tests for it yet", tied to the options.
  - **Later, in its own plan:** a typed rule becomes a tested rule, and "use the suggestion" becomes a hand-check case.
- **S2.** `components/gates/SelectAll.tsx`, shared by the Test plan (in `CaseTable`) and the Defects page:
  - it reads "Select the N <things> shown" and is part-ticked when only some are selected;
  - defects sent to a tracker are never in it (`isDecidableDefect`);
  - on both pages only the selected rows still shown are counted and sent (`inView`).
- **S3.**
  - Engine: `reconciler.answer_question` names the question's page ("for /apply", at most 200 characters) where it has no requirement or rule, instead of "for the plan".
  - App: the Change log shows an answer's question as "The question: …" (`whyIsQuestion`).
- **S4.** The "why?" button's wrapper class `.why` was also the wizard's explanation box (`wizard.css`: blue left rule, padding, background). It is now `.why-button`.
- **S5.** `needsYou(counts, slug, mayDecide)`: a Viewer's Project page reads "What is waiting", with "15 open questions", "19 defects waiting for a decision" and so on.
- **Test fixture.** `frontend/src/test-fixtures/gates-demo.json` gained `note_only` on its 15 questions by a one-off script (the 3 "A vague requirement" ones are true). `tools/make_gates_fixture.py` writes it by itself from now on, because it uses `questions.listing`.
- **Tests:**
  - backend: `test_answer_notes.py` (new);
  - frontend: `SelectAll.test.tsx` and `WhyButton.test.tsx` (new);
  - extended: `QuestionCard`, `Defects`, `ChangeLog`, `Project`, `lib/gates` and `TestPlan` (label).

**Merged.** The owner said yes on 5 Nov 2026: `main` was fast-forwarded to `301fb3d` (Phases A and B plus these fixes). He then
looked at the fixes on a fresh throwaway server built from `main`, with the gates fixture seeded: the note on the three vague questions,
"Select the 19 defects shown", the Reject buttons without stray rules.

**Open (small, for Phase C or D):** a defect's evidence picture whose file is missing (404) shows a broken-image icon. It should say
that the file is missing. This was seen with the gates fixture, which keeps 6 pictures; a real run has them all.
(Done in Phase C: `components/gates/Picture.tsx`.)

### Phase C (5 Nov 2026, branch `claude/compassionate-goldwasser-e62a07`, on `main` `118080d`)

**Built as planned.**
- **Engine, decision 2** (`assist.py`, with `assist_wipe.py`): a typed take-over command keeps only its length once it
  has run or can no longer run; a password or one-time-code box counts as secret; a secret answer becomes "[given]"
  once the agent has read it; overwrites use `secure_delete` and a write-ahead-log checkpoint, so the text is gone from
  the file too; `expire_stale` also sweeps what a crashed run left. What the agent does with a value is unchanged.
- **Visual review** (`orchestrator/gates/visual.py`): `approve_row` and `report_row` are the old dashboard's code,
  moved; the current picture is copied only when the `files` guard serves it and the key is a plain name; a reason is
  required to accept a change; `approve-all` writes one row.
- **Heals** (`orchestrator/gates/heals.py`): proposed locator and workflow fixes only; `healer.approve_heal(…, by=, why=)`.
- **Help box** (`orchestrator/gates/helpbox.py`): the pending list from one bare read-only query with the plan's caps
  (answers never sent), the once-a-minute sweep, exactly one answer that fits its question, take-over commands bounded
  by the schemas (`api/schemas_review.py`) and checked again by the service (inside the screen, in scope, 20 waiting),
  the screenshot by id, Pause and Resume, the teach routes' role check.
- **Routers** `api/routes_review.py` and `api/routes_assist.py`; `SHOT_PATH` covers visual pictures, help-box
  screenshots and the polled list. Nine new writes; the Viewer-rule floor is 33.
- **`yamledit`**: a value or field name from the tested site is written double-quoted, and an edit is kept only when the
  file, read back, differs from before in exactly the intended place.
- **`tools/e2e_assist.py`** ported to the signed-in API with the CSRF header and the teach routes; its last checks scan
  the logs, recordings, the vault and the database file.
- **App:** `lib/assist.ts` (pure: caps, `pollMs`, `scalePoint`, answer and command bodies), `lib/useAssist.ts`,
  `lib/reviewApi.ts`; `components/assist/` (`NeedsYouDock` in the Shell on every project page, `AssistDialog` and
  `TakeOver` in a `Modal` with the page behind made inert, `ScreenShot`, `PauseButton`, `NeedsYouBanner`);
  `pages/gates/{Visual,Heals}.tsx` with `VisualCard`, `HealCard`, `Picture`; navigation "Visual review" and "Heals"
  with spoken badges, and "What needs you" links to both; the Live View banner and Pause button; B22 (a backdrop click
  closes the Lightbox); C13 (the focus column scrolls into view on choice under 1 024 px); `styles/assist.css`.
- **Checks:** `check_app.py` measures the Visual and Heals pages and the dock and dialog; `check_gates_c.py` is the
  Phase C part of `check_gates.py`.

**Where the code disagreed with the plan, and what was done.**
1. **A Viewer** gets only who is waiting (`{id, kind, role, agent, at}`) and the screenshot answers 403: the plan's
   "no screenshot" is kept by the server too, not only the page.
2. **`GET /assist` uses the screenshot bucket** (1 200 a minute), not the general 240: every open tab polls it.
3. **"Took over … as <role>"** is logged at the first command of a take-over (a Pause take-over has no answer to log);
   the answer "Let me take over" logs "asked to take over …". No typed value is ever logged.
4. **Answers must fit the question kind** (`helpbox.ANSWERS`); `confirm` also takes a choice (the visual check asks it
   with two). Typed text is never echoed, not even when "hide" is unticked (the plan kept the echo for plain typing;
   review finding 2).
5. **Visual and heal decisions wait while a run goes** (a job or a command-line run), and Pause reaches a command-line
   run through its live marker (`orchestrator/live.cli_run_going`).
6. **Lists** default to 50 rows with `total` (the plan said LIMIT 200 for heals), like the other gate lists.
   `approve-all` answers `{approved, skipped}`. A heal's reason, when given, replaces the Healer's in the log row.
7. **The old dashboard, Phase D's work, moved partly here** on the security review: its help box goes through the new
   service, and its visual-review and heal pages send the person to the app and decide nothing. The parity test compares
   the moved code with the v0.8 functions kept word for word in the test.
8. **`assist.py` became four modules** (moved code): the wipe, the screenshots and the recorder have their own files.
9. **`e2e_assist.py` presses Pause after the run has started** (the server refuses a pause with nothing running) and
   types the one-time code with "hide" unticked.
10. **`GET /assist` answers 503 when the database cannot be read** (TypeScript review), so a page never mistakes a busy
    database for "nothing is waiting" and closes a take-over.

**Still not verified:** acceptance sitting 2 with the owner (take-over, Pause, visual review, heals on the demo's own
copies).
