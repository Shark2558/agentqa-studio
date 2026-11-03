# AgentQA Studio

AgentQA Studio is a self-hosted tool that tests a web portal end to end. It runs on your own computer, needs no API key and has no per-use cost. AI models (OpenAI, Anthropic, Gemini, DeepSeek, Groq, Mistral, OpenRouter, Azure OpenAI, any OpenAI-compatible server, or Ollama) can be added if you want them; every stage still works without one.

You give it the portal's test URL, a test account per role and the SRS. It reads the SRS, logs in as every role, maps every screen and compares the SRS with what the portal actually does. Where the two disagree, it asks you. It then designs test cases, writes real pytest + Playwright code, runs it, explores the portal like a curious user to catch what the SRS never mentioned, groups failures into defect reports with evidence, and produces a report with a traceability matrix.

Version 0.8 fixes API testing on token-secured portals, lets you show the Explorer around, and tells you what to do next:

- **API tests that log in the way the portal does.** On a portal whose screens call the API with an `Authorization` header (a bearer token kept in the browser's storage, as single-page apps do), v0.7's API tests sent no header: every secured API answered 401 and the tests failed. The Explorer now watches how each role's screens authenticate their API calls and notes *where* the token lives (a local-storage or session-storage key, a path inside a stored JSON object, or a cookie; never the value). The generated runtime reads the same place from the role's saved session and sends the same header, so an API test fails only when the API is wrong. APIs on another address than the portal (an `api.` sub-domain, another port, `api.hosts` in project.yaml) are tested too. A token kept only in the page's memory is read from the page's own first API call.
- **Show AgentQA around.** On the App map page, pick a role and press **Show AgentQA around**: it logs in and hands you the browser. Open a menu, search, pick a record, type an address: every page you open goes on the map, and the way you got there is remembered, so the next exploration reaches it alone. **Pause and take over** now works while the Explorer is crawling, not only during a login, and the pages you visit while paused are mapped the same way. The take-over box has an **Open an address** field.
- **Master plan.** A new page lists every activity from set-up to the shared report, in order: done, running, waiting for you, ready to run, later. A **Next step** banner on every page says the one thing to do now (answer questions, approve the plan, confirm defects, add a password...) with the button that does it.
- **Test data, simplified.** The page opens with *What AgentQA will use for testing*: one card per account with **Active** or **Needs attention** (and exactly what to add), how it logs in, the learnt way in and the last login result. Adding an account is a four-step form that shows only the fields that way of logging in needs (a mobile login asks for a mobile number and where the OTP comes from, nothing else). Portals, the project model fallback and the login log are folded away until needed.
- **Live View keeps its place.** Leaving Live View and coming back resumes where you were (a live run jumps to its latest step) instead of replaying from the beginning; opening Live View picks the run in progress or the newest run that has something to show.
- **Test cases in the standard template.** The Excel download now follows the team's template, in this order: Test Case Id, User Access, Module, Test Case Name, Test Case Description, Pre-Condition, Actions, Test Data, Expected Result, Test Result, Remarks; then Requirement ID, Scenario, Test Type, Priority, Defect ID and Evidence. **Download test cases (Excel)** on the Test plan page exports every prepared case (functional, access, API, security, pages, accessibility, performance, visual) with its last result; the Functional tests page still exports the functional subset.
- **Export for Zoho.** The Defects page writes a CSV in the column layout Zoho BugTracker / Zoho Projects / Zoho Sprints import ("Import bugs", map by header: Title, Description, Severity in Zoho's words, Classification, Reproducible, Module, Status), with the AgentQA defect id for tracing. Jira CSV, Jira and Azure DevOps sync stay as before.
- **Fixes from an end-to-end audit of the dashboard** (27 pages, 574 links, every form): a manual test's unqualified path (`/officer/queue`) now resolves to the role's own portal instead of 404-ing on the primary one, and a page that does not exist for a role counts as access denied, not as a false defect; a new project is refused unless the address is a full URL; a heal action on an unknown proposal answers 404 instead of crashing; Ask AgentQA accepts a form post as well as JSON; a run asked to show a browser window where there is no screen carries on headless; the home page facts were brought up to date.

Version 0.7 made the agents easier to help, and made them remember the help:

- **Take over the browser.** When an agent is stuck, the help box offers **Let me take over the browser**. You then drive AgentQA's browser from the dashboard: click on the live screen (or on the buttons and boxes listed beside it), type into the selected box (passwords and OTPs stay hidden), press Enter, Tab or Back. When the browser window is visible on your computer, you can use it directly instead. Press **Continue** and the agent carries on from that screen.
- **AgentQA remembers what you did.** Your clicks become the role's login steps, and so does what you typed: the username, mobile number and password are saved, encrypted, on the Test data page. The next login repeats your steps without asking. What you showed on each screen is also kept when a login does not finish, so you are not asked the same thing twice. A saved login is reused for as long as the portal still accepts it, so a live portal does not ask for a new OTP on every run.
- **Pause and take over.** While anything is running, **Pause and take over** in the top bar stops every agent at its next step and hands you its browser. **Continue** resumes it.
- **Show how to log in.** On the Test data page, each role has this button. You log in once yourself in AgentQA's browser: open the login, type the username or mobile number, the password, and the OTP when it arrives. AgentQA records the path and keeps the details.
- **Live screenshots.** The help box now refreshes its screenshot while AgentQA waits and after every action, so it always shows the screen as it is.
- **English first.** Every agent checks the page's language before working on it. If the portal opens in Malayalam, Hindi or another language, the agent clicks the switch to English (a link or button called English, ENG or EN, the word written in an Indian script, or an English option in a language list). It remembers per application which switch worked, so the generated tests switch the same way. If it finds no switch, it asks you once. Crawlers never follow a switch to another language.
- **Requirement Analyst and Requirement Writer.** The SRS Analyst is now the **Requirement Analyst**: it reads the documents and pulls out the requirements, their rules and anything vague. A new **Requirement Writer** comes next. For every requirement it writes a clear statement, a user story, the steps (who does what), alternate flows, exceptions, Given/When/Then acceptance criteria and the points still open. An AI model does this writing when one is set up. Every number, limit and role in the rewrite is checked against the source, and anything the model added is flagged for review. The Test Case Generation agent drafts its cases from these steps.

`tools/e2e_assist.py` tests all of this end to end on the demo running in its hard mode (Malayalam first, an unlabelled login icon, an unnamed mobile box), with a person simulated through the dashboard's own calls.

Version 0.6 implemented the eight areas of the Master Requirements document:

- **AI providers page.** Several keys per provider, each with priority, model and fallback model. On a rate limit, used-up quota, outage, timeout or repeated connection failure, AgentQA moves to the next key and then the next provider. A rejected key, a billing problem or a retired model is never retried in a loop. You can test the connection, list models and set retries, cool-downs and the fallback order. An audit log records every switch. Keys are encrypted and never shown in full.
- **Requirement documents in any common format.** Upload several at once: Word (.docx, .doc), PDF (scanned pages read with OCR), Excel (.xlsx, .xls), CSV, HTML, JSON, Markdown, text and images.
  - Every passage goes into a source ledger. Requirement-like text that produced no requirement is listed for review.
  - Each requirement is standardised: title, actors, preconditions, trigger, main flow, exceptions, expected outcome, acceptance criteria, use case and source reference.
  - Duplicates and contradictions are flagged.
  - Every requirement ends up either covered by tests or marked out of scope, not testable, manual or needing clarification. The traceability matrix (source → requirement → use case → case → execution → result → defect) downloads as Excel.
  - Coverage is never called complete while a gap, an unread document or an unexplained passage remains.
- **Test Case Generation agent.** It drafts cases in the standard template for requirements nothing else covered: TC ID, requirement ID, module, scenario, objective, test type, Critical/High/Medium/Low priority, role, preconditions, test data, steps, expected, actual, status, defect ID and evidence.
  - With a model, every step it names is checked against the app map. A step the app map does not know is kept as an *intent* step instead of being dropped.
  - Without a model, the use case becomes intent steps.
- **Visual QA agent.** It carries out intent steps and judges expected results from the screenshot (only when you allow screenshots to be sent), the visible text, the numbered controls and the accessibility tree.
  - It acts only on a control it was shown, types only test-data tokens, and changes nothing on a production application.
  - A Pass needs words copied from the page that prove it. Without a model or a person, the step is Not Run, with the reason.
- **Several applications per project.** For example a Citizen Portal and a Department Portal, each with its own URL, environment, login and accounts. A workflow crosses them, carrying the application number from one portal to the next: citizen applies → clerk verifies → citizen sees Verified → officer approves → citizen sees Approved.
- **Evidence for every test.** Each test keeps a screenshot and a step log. A test that checked nothing fails as NOT VERIFIED. When a login fails, the tests that need it are **Blocked**, never Passed. Waits longer than `functional.max_wait_s` without a test clock are **Not Run**.
- **Execution page.** Shows requirements, cases, pending, executed, passed, failed, blocked, not run and defects. It breaks coverage down by module, requirement, application and role, shows each workflow's progress, and lists defect records with requirement, case, URL, time and logs. You can run everything or a module, role, application, test type, workflows, the failed and blocked cases, what has not run, or a full regression, and resume an interrupted pipeline.
- **Agent contracts and checkpoints.** Every stage is recorded with its result. What it hands on is checked against its contract: a case without an expected result, a Pass without evidence or a defect without its case is reported. The change log records who changed a disposition, answered a question or approved a heal, and why.

`tools/acceptance.py` maps each of the 14 acceptance criteria to the evidence an executed run left behind (see *Acceptance* below).

Version 0.5 made the agents work like a manual tester:

- **Logging in.** They log in the way a person does: open the home page, click **Login**, choose **Citizen Login** or **Department Login**, type the mobile number, press **Get OTP**, type the OTP and check they are in. AgentQA records these steps and repeats them on later runs. The Explorer also clicks buttons, drop-down menus, tabs and pop-ups, not just links.
- **Asking you when stuck.** On a live portal the OTP goes to your phone, so AgentQA pauses on the live screen and an **AgentQA needs you** box opens on every dashboard page. You type the OTP or CAPTCHA there, or show it where to click.
- **Test data page.** One encrypted place on your computer holds the accounts (username and password, or mobile number), where each OTP comes from, data sets and keys.
- **Functional test cases.** A new Functional Test Analyst drafts them for every login, menu, form and search: valid logins per role; mobile numbers that are blank, too short, contain letters or start with a wrong digit; wrong and blank OTPs; Resend OTP; wrong, case-changed and blank passwords; logout and the Back button; and a check that every menu opens the right page. Each case has preconditions, steps, test data and an expected result. The cases run with the rest of the suite and export to an Excel workbook that includes the actual results.

Version 0.4 made it ready for a pilot on a real portal: logins with a one-time password (OTP) read from a mock SMS and email inbox, file uploads and custom widgets (date pickers, rich text editors, multi-selects) in tests, test data reset through the portal's API or database, an OWASP ZAP security scan as every role, two-way sync with Jira and Azure DevOps (fixed issues are re-tested, then closed or reopened), the Healer for multi-role workflows, a pilot readiness check, AgentQA's own test suite and CI, and a Windows installer build.

Version 0.3 added API testing from the traffic the screens make (and from an OpenAPI file), record-isolation tests with a second account per role, session, CSRF and security-header checks, a small load test, visual regression with a review page, full axe-core accessibility, import of existing manual test cases from Excel, a plain-English assistant, a release-readiness score, CI pipelines with JUnit output, and a new blue-and-white dashboard.

**Live View** shows all of this as it happens: the SRS being read line by line, each browser's screen with the field or button it is acting on outlined, the site map growing, rules being matched, test tiles turning green or red, and defects being filed. Every run is recorded, so you can replay it later step by step.

Every stage works without an AI model. Generated tests call one only for intent and verify steps (the Visual QA agent); recorded steps never do. A model is optional: it helps with SRS sentences the built-in rules cannot interpret, fills in standardised requirements, drafts test cases and drives the Visual QA agent, and anything it proposes about the SRS waits for a person to confirm.

## What to expect on your laptop

Built for a Ryzen 5 5600U with 16 GB of RAM and integrated graphics, which is fine for everything except large AI models.

| Item | On this laptop |
| --- | --- |
| Test execution | 2-4 parallel browsers (`execution.workers: auto` picks 4 on a 6-core Ryzen 5). The 215-test demo suite (52 functional cases, forms with uploads and widgets, load, visual) ran in about 3 minutes on the 2-thread build machine with 2 browsers. Tests that log in afresh (wrong OTPs, logout) run last, one at a time, so they never disturb the other tests |
| Explorer | A few seconds per role for a 40-page portal |
| Exploratory Tester | About 30 s for the demo (20 steps and up to 15 address probes per role) |
| Whole demo pipeline | About 5 minutes on the build machine, including about a minute for the OWASP ZAP scan; expect 4-6 minutes on the laptop |
| OWASP ZAP | About 1 GB of RAM while it scans; it starts for the scan and stops afterwards |
| Live View | Screenshots use about 15-20 MB per demo run, and the last 15 runs are kept. Turning them off (`live: {screenshots: false}`) makes runs about a third faster; the step-by-step view still works, without pictures |
| Optional Google Gemini | Free-tier keys work; the Functional Test Analyst makes a few calls per project, and logins ask Gemini only when the screen is unclear |
| Optional local model | CPU only. Use a 4B model such as `qwen3:4b` (about 2.5 GB). Expect roughly 20-60 s per SRS sentence, so run it on SRS text the rules could not interpret |
| Disk | About 1 GB including Chromium; each run keeps screenshots and traces of failures only |

## Setup on Windows

1. Install Python 3.11 or newer from https://www.python.org/downloads/ and tick **Add python.exe to PATH**. If you have winget, `winget install Python.Python.3.12` also works.
2. Unzip this folder somewhere without spaces in the path, for example `C:\AgentQA`.
3. Double-click **setup.bat**. It creates a virtual environment, installs the packages and downloads Chromium. Behind a corporate proxy, first run `set HTTPS_PROXY=http://proxy:port` in a terminal, then run `setup.bat` from that terminal.
4. Optional, for the security scan: install OWASP ZAP from https://www.zaproxy.org/download/ (the Windows installer includes Java). AgentQA finds it on its own; without it the Security Scanner stage is skipped.

A one-click Windows installer (Python, packages, Chromium and optionally ZAP bundled, no administrator rights needed) can be built with `installer\build_installer.ps1` on any Windows machine, or by running the **AgentQA release** workflow in GitHub Actions. It installs to your user folder and keeps projects in `%USERPROFILE%\AgentQA\projects`.

## Try the demo first (5 minutes)

Double-click **demo.bat**. It starts a small four-role demo portal and the dashboard, opens **Live View** in your browser so you can watch the agents work, runs every agent and opens the report. The demo works like many government portals. The header has a **Login** button that offers **Citizen Login** (mobile number, **Get OTP**, six OTP boxes) and **Department Login** (username and password; officers then get an OTP). Citizens reach their pages through a JavaScript **Services** menu. The demo SRS is deliberately imperfect. The portal also has a small REST API, and the application form has a file upload, a custom date picker, a rich text editor and a custom multi-select. There are nineteen seeded bugs, and AgentQA should report all nineteen and nothing else (`python tools\check_demo.py projects\demo` checks this):

| Seeded bug | Expected defect | Found by |
| --- | --- | --- |
| Approval Queue has no role check | Critical: open to citizen, clerk, admin and anonymous | tests and Exploratory Tester |
| Admin Reports crashes | High: HTTP 500 | tests and Exploratory Tester |
| Search shows what you type as HTML | High: possible cross-site scripting | Exploratory Tester only (not in the SRS) |
| Applicant Name allows 100 characters (SRS: 50) | Medium: accepts 51 characters; form limit is 100 | tests |
| Mobile Number accepts letters and a leading 0 | Medium | tests |
| Certificate Type options differ from the SRS | Medium: Caste missing, Nativity extra | tests |
| Help links to a missing FAQ page | Medium: broken link, 404 | tests and Exploratory Tester |
| No security headers | Medium: clickjacking and MIME-sniffing protection missing | Exploratory Tester only |
| Home image has no alt text; search box has no label | Low: accessibility | tests |
| My Applications has a script error | Low: JavaScript error | Exploratory Tester only |
| `/api/applications/{id}` has no ownership check | Critical: one citizen can read another citizen's application, mobile and email | record isolation test (second citizen account) |
| `/api/users` checks login but not the Administrator role | Critical: every role can list all users | API access test (the screen itself is protected) |
| Logout only deletes the browser cookie | High: a copied session cookie still works after logout | session test |
| Forms have no anti-CSRF token | Medium: cross-site request forgery possible | CSRF test and OWASP ZAP |
| A used OTP is accepted again | High: the officer's login code works twice | OTP test (reads the SMS from the mock inbox) |
| Supporting Document accepts any file type (SRS: PDF, JPG, PNG) | Medium: an .exe upload is accepted | file upload test |
| Documents Attached (custom multi-select) offers Driving Licence instead of Passport | Medium | option test on the custom widget |
| Citizen login accepts a 9-digit mobile number and moves on to the OTP step | High | functional login test (and the SRS field rule on the login form) |
| **Resend OTP** does nothing | High: no new OTP SMS arrives | functional login test (counts the SMS in the mock inbox) |

When a test, a functional case, the Exploratory Tester and OWASP ZAP find the same problem, Triage files one defect, not four.

The demo also imports `imports/manual_tests.xlsx`, a sheet of ten manual test cases written the way testers usually write them ("Login as Citizen", "Enter valid details", "Upload the supporting document", "Confirmation email is received"). Nine convert fully into automated tests; one is flagged for review because it does not say which application the clerk should verify.

More to try on the demo:

- **Jira and Azure DevOps**: run `python -m agentqa demo-trackers` (a mock of both on port 8900), add the `trackers:` block from the **Jira and DevOps** page to Settings with `base_url: http://127.0.0.1:8900/jira`, confirm a few defects and press **Sync now**. Mark issues fixed on http://127.0.0.1:8900, restart the portal with `set DEMO_FIXED=B4,B5`, run again and sync: fixed issues are closed as verified, the rest reopened with the new evidence.
- **The Healer on a workflow**: restart the portal with `set DEMO_VERIFY_LABEL=Mark verified`. The maker-checker workflow breaks; the Healer proposes the renamed button, and approving it edits that one line of project.yaml.

To see visual testing, stop the demo portal, start it again with `set DEMO_VISUAL_CHANGE=1` (it restyles the header and moves the Apply button), and run `python -m agentqa pipeline --from run -p projects\demo`. The **Visual review** page then shows each changed screen with the approved snapshot, the new one and the difference highlighted; approve it as the new baseline or report it as a defect.

The demo also shows the three human gates. In the dashboard (**start.bat**), the Questions page lists what the SRS got wrong or left vague: the TBD Remarks field, the PDF download the portal never built, "appropriate error messages", and so on.

## Testing your own portal

1. **Prefer a test (UAT) environment.** You need:
   - one test account per role;
   - for OTP logins, either the OTP routed to AgentQA's inbox or a fixed test OTP (fully automatic), or you at hand to type the OTP from your phone when AgentQA asks;
   - CAPTCHA switched off or fixed for tests (AgentQA never bypasses CAPTCHA; if one appears, it asks you to type it);
   - test data that can be reset, through a test API or the database.
   On a live production portal, keep to logins, menus, page checks and searches. Switch off form submission, the exploratory form filling, the security scan and the load test, and get the portal owner's permission first.
2. Open **start.bat** and create a **New project** with the portal URL.
3. Open **Test data** and add one account per role:
   - the **login option** the portal shows (for example *Citizen Login*);
   - how the account logs in (username and password, or a mobile number and OTP);
   - where its OTP comes from (**Ask me on screen** for a live portal).
   Everything there is encrypted on this computer and never written to project.yaml.
4. Open **Pilot readiness** and run the check. It logs in as every role, shows the steps it found ("open / > click 'Login' > click 'Citizen Login' > type mobile > click 'Get OTP' > type the OTP"), and says how to fix each problem. Add `aliases` in **Settings** so the SRS's names for each role match (for example `[Approving Officer, AO]`).
5. Upload the requirement documents on **Requirements**: several at once, in Word, PDF (scanned pages too), Excel, CSV, HTML, JSON, Markdown, text or image form. Field tables with columns such as Field Name, Type, Mandatory, Length and Validation, and requirement lists (ID and Requirement columns) are read directly. Check the document list (each shows *read in full*, *partly read* or *not read*, and why) and the **Text no requirement came from** box, then set a disposition for any requirement that should not be tested (out of scope, not testable, manual).
6. Click **Run full pipeline**. It stops at the plan gate.
7. **Gate 1: Questions.** Answer the clarification queue, then re-run Reconciler and Designer. Rules behind open questions are not tested, so a wrong SRS line can never become a false pass or a false failure.
8. **Gate 2: Test plan.** Review the cases and approve them (all at once, or by type). Then click **Continue after approval**.
   The **Functional tests** page lists the manual-tester style cases by module (Login, Logout, Navigation, Forms, Search). **Approve** and **Run functional tests** run just those, and **Excel workbook** downloads them with steps, expected and actual results.
9. **Gate 3: Defects.** Confirm the real defects and reject the rest. Rejections are remembered on later runs. Send them to Jira or Azure DevOps from **Jira and DevOps**, or download the CSV.
10. Re-run on every build. Defects that stop failing are marked resolved automatically, and their issues are closed as verified.

**Several portals.** When the citizen site and the department site have different addresses, add each on **Test data → Applications** (name, URL, environment, login page, scope and priority) and pick each account's application. Mark a live site's environment *production*: AgentQA then only reads there (no form submissions, workflows, attacks or load), and the Execution page lists what it left out.

**Multi-role flows** such as maker-checker are derived from the SRS's status rules and the screens each role sees, across applications. To describe one by hand, use `workflows:` in project.yaml.

Further options in project.yaml:

- **Second account per role** (`roles: {citizen: {..., peer: {username: citizen2, password_env: AGENTQA_PW_CITIZEN2}}}`). Enables record-isolation tests: the second account must not be able to read the first one's records through the API.
- **APIs** (`api: {openapi: /openapi.json, prefix: /api/, max_ms: 2000, hosts: []}`). Endpoints are found from the screens' own traffic; an OpenAPI file (a path on the portal or a local file) adds the ones no screen calls. A back end on the portal's own domain (an `api.` sub-domain, another port) is recognised by itself; list any other address in `hosts`. How each role's screens authenticate (an `Authorization` header and where its token is kept) is learnt by the Explorer and repeated by the tests; no value is stored.
- **Visual** (`visual: {threshold: 0.002, mask: ['.clock', '#banner']}`). Masked selectors are ignored when comparing.
- **OTP logins**: set the OTP source per account on the **Test data** page. **Ask me on screen** (live portals) pauses and asks you. The **mock inbox** (test environments) reads the SMS or email. A **fixed test OTP**, an **authenticator secret** (TOTP) or a **test API** of the portal (`login: {otp: {api: ...}}`) also work. The **OTP and email inbox** page shows where a test environment should send SMS (an HTTP webhook) and email (SMTP), and every message caught.
- **Functional cases** (`functional: {login_tests: true, unregistered_mobile: null, llm_cases: true}`). `unregistered_mobile` is a number known to have no account. On a live portal it is unset, so AgentQA never sends an OTP to a stranger's phone.
- **Test data** (`data: {setup: [...], cleanup: [...]}`). Steps call the portal's API (`http:`, optionally logged in as a role) or run SQL (`sql:` with the connection string in an environment variable) before and after each run, so results do not depend on earlier runs.
- **Security scan** (`zap: {active: false, min_risk: Medium}`). Passive by default; `active: true` adds ZAP's attack probes, for test environments only.
- **Jira and Azure DevOps** (`trackers:`): see the **Jira and DevOps** page for the settings; tokens go in environment variables.
- **Security** (`security: {logout_url: /logout}`) and **load** (`performance: {users: 5, seconds: 8, max_error_rate: 0.01}`). The load test is a smoke test for a test environment, not a capacity test.

## Logins, OTPs and when AgentQA asks you

AgentQA does not need login selectors. For each role it:

1. **Repeats the recorded steps**, if it has logged in before.
2. **Reads the screen, if not.** It looks for a Login button or link, picks the login option for the role (the **Login option** on the Test data page, the role name or its aliases), and types what the form asks for (username and password, mobile number, or email). It then presses **Get OTP** or **Sign in**, fills the OTP (one box or six) and presses **Verify**.
3. **Does what you showed it on that screen before**, if a person helped there once (even in a login that did not finish).
4. **Asks for help when stuck.** It asks the model if one is switched on, then you. The **AgentQA needs you** box shows the live screenshot (it refreshes while the agent waits), the buttons it can see, and a box to type into. You can:
   - click a button name;
   - click on the screenshot itself;
   - type the text;
   - press **skip**;
   - choose **Let me take over the browser** and do several steps yourself: open the login, type the username, password or mobile number, type the OTP. Then press **Continue**.

   When AgentQA runs from a command window, you can also type the answer there.

**Show how to log in** on the Test data page does step 4 from the very start: you log in once, AgentQA watches.

What AgentQA keeps from your help:
- The steps, per role. See them on the Test data page; **Re-learn** forgets them.
- The details you typed that it did not have (username, mobile number, password). They are saved encrypted on the Test data page and never written to a log or a step.
- The OTPs and CAPTCHAs you typed are **not** kept. Next time it asks for them again, or reads them from the inbox.

**Pause and take over** (top bar, while anything runs) stops every agent at its next step and hands you its browser. Continue resumes it.

A saved login is reused for as long as the portal still accepts it. AgentQA checks it by opening the landing page; set `login.session_minutes` to put an upper limit on that. So with **Ask me on screen** you type an OTP about once per role, not once per run. The functional login tests log in afresh, so on a live portal expect a few more OTP requests (a valid login and a Resend OTP check per OTP role). Wrong-OTP tests type `000000` and need nothing from you.

## English first

Before working on a page, every agent (Explorer, login, Exploratory Tester, the generated tests, Visual QA, the readiness check) checks its language. It looks at the page's `lang` attribute and the share of English letters in the visible text. A page in another language is switched with the portal's own control:
- a link or button called English, ENG or EN, or the word English written in an Indian script;
- a link whose address carries `lang=en`;
- an English option in a language drop-down.

The switch that worked is kept per application (`.agentqa/language.json`) and handed to the generated tests. If no switch is found, AgentQA asks you once. The readiness check reports the result. To test a portal in its own language, set `language: {switch: false}`.

## Functional test cases

The **Functional Test Analyst** runs inside the Designer. It drafts cases the way a manual tester writes them, from what AgentQA actually saw (the recorded logins, the screens, the buttons and menus the Explorer clicked) and the SRS:

| Module | Cases |
| --- | --- |
| Login | valid login per role; mobile number left blank, 9 digits, letters, starting with 5, valid but unregistered, more than 10 digits; wrong and blank OTP; Resend OTP; the OTP screen shows only the last 4 digits; wrong, case-swapped and blank password; unknown username; password box masked; wrong OTP after the password |
| Logout | Logout ends the session, and Back, reload or typing the dashboard address does not bring it back |
| Navigation | every menu item, drop-down menu, pop-up and link opens the right page or shows the right choices, per role |
| Forms | the empty form; each mandatory field left empty; wrong formats per kind of field (mobile, email, PIN code, name, date of birth, Aadhaar, PAN, numbers, file type). Fields the SRS already covers keep their SRS-based cases instead of duplicates |
| Search | no match says so; special characters are shown as typed (not turned into HTML); an empty search does not break the page |
| Workflows | multi-user journeys across roles and applications, with a rejection path when the SRS has one |
| Requirements | the Test Case Generation agent's template cases for requirements nothing else covers: with a model, steps on known screens plus intent steps; without one, the use case as intent steps run by the Visual QA agent |

Each case has preconditions, numbered steps, test data, an expected result and requirement IDs. Values from the Test data page stay as tokens in the generated tests (`{mobile}`, `{password:wrong}`) and are filled in at run time, so no password or real mobile number is ever written to the tests folder. `python -m agentqa run --type functional -p projects\<name>` runs only these, and `python -m agentqa export-cases -p projects\<name>` writes the Excel workbook.

## AI providers (optional)

AgentQA works fully without a model. To add one, open **AI providers**:

1. Add a key: provider, label, the key, priority (1 is tried first), model (`auto` picks a current one) and a fallback model. Add as many keys per provider as you like. Azure OpenAI also needs the endpoint and deployment; an OpenAI-compatible server needs its base URL; Ollama needs no key.
2. Press **Test**. AgentQA lists the models the key can use and makes one small call.
3. Set the order of providers, retries per key, the timeout, and cool-down times per kind of failure.
4. Switch the model on for the project. Leave **Send screenshots** off unless the portal owner allows it.

What happens when a call fails:

| Failure | What AgentQA does |
| --- | --- |
| Rate limit, quota | the key cools down for the set time (or the provider's Retry-After); the next key is tried |
| Timeout, connection error, outage | retried up to the set number of times, then the next key |
| Invalid key, billing problem | the key is marked and not used again until you edit it |
| Model not found | the fallback model is tried; the retired model is not asked again |
| Every key fails | logged as *all failed*; the work continues without a model |

Every call, failure and switch is in the audit log at the bottom of the page. Keys are encrypted with the same key as the Test data page, are shown masked, and are scrubbed from every log. Before anything is sent, mobile numbers, email addresses and 12-digit numbers (such as Aadhaar) are masked. SRS text and screen text do go to the provider, so use one only where the portal owner allows it. `python -m agentqa ai-test` tests every key from the command line, and `python -m agentqa demo-ai` starts local stand-ins for the provider APIs, to try failover without a real key. The older per-project settings (Gemini key under Test data → Keys, or Ollama) still work when no key is on the AI providers page.

## Bringing your existing manual test cases

Open **Imported tests**, upload the Excel or CSV sheet your team already uses, and AgentQA matches each step to a real screen, field and role from the App map. Headings are found by name (Test Case ID, Title, Role or Precondition, Steps, Test Data, Expected Result), and a case may span several rows. Fully understood cases can be approved in one click; steps it cannot match say why ("no field on the current screen matches", "which record to click is not specified"). Approved cases become `manual_converted` tests the next time the Designer runs. Sheets left in the project's `imports` folder are imported automatically by the pipeline.

## Asking questions (Ask AgentQA)

**Ask AgentQA** answers questions such as "How ready is this release?", "Why did TC-0016 fail?", "Explain FR-05", "What is not tested yet?" or "Show high defects for clerk" from the project's own records, and lists the records it used. It can also act: "Add a test that clerk cannot open /admin/users" creates an access test, and "Re-run the failed tests" starts a run you can watch in Live View. It works without a model; with the optional local model on, questions the rules do not cover are answered by the model from the most relevant records. From the command line: `python -m agentqa ask "how ready is this release" -p projects\<name>`.

## Release readiness and CI

The dashboard's **Release readiness** score (0-100) combines tests passed weighted by priority (50%), open defects weighted by severity (30%) and requirement coverage (20%), and gives a verdict: **Ready** (85 or more, no open Critical or High), **Ready with risks** (70 or more, no open Critical) or **Not ready**. The reasons are listed under the gauge.

`python -m agentqa ci -p projects\<name> --fail-on High --min-score 70` runs the approved suite headless and exits with 1 when a defect at that severity or worse is found in this run or the score is below the minimum, and with 2 when the plan is not approved. Each run writes `runs/<run-id>/junit.xml`. Ready-made pipelines for GitHub Actions, GitLab CI, Jenkins and Azure DevOps are in the `ci` folder; CI never approves a plan.

## Watching the agents (Live View)

Open **Live View** in the dashboard's side bar. Runs started from the dashboard open it automatically while **Watch in Live View** is ticked; runs started from the command line or demo.bat appear there too.

- **Pipeline strip**: one card per agent with a live counter (requirements read, screens visited, cases designed, tests passed, defects filed). The active agent pulses; finished ones get a tick. Click a card to jump to its view.
- **Document**: the SRS as the analyst reads it. Each requirement is highlighted in turn, vague words (appropriate, quickly, TBD) are marked, and the rules it extracted appear as chips underneath.
- **Screens**: one live browser frame per worker, showing the screenshot after each step with an orange box on the field or button being used, the role, the test case, the last few steps and the verdict. Typed passwords are always hidden. Below it, the **site map** grows as screens are discovered, coloured by HTTP status, with a dot for each role that reached the screen. Click a node to see that screen.
- **Rules**: every rule as the Reconciler decides it (Confirmed, Divergent, SRS-only and so on) and each question it raises for you.
- **Tests**: a tile per test case, grouped by type, turning blue while running and then green, red, amber (test issue) or violet (visual change). Click a tile to see its last screenshot.
- **Code**: the test files as the generator writes them.
- **Findings**: defects as Triage files them, with severity, roles and requirement IDs, plus Healer proposals and the report link.
- **Activity** (right): every step with a thumbnail. Filter by agent, or tick **problems only**.

The player at the top replays any recorded run: pause, step, change speed (up to instant), drag the timeline, or **Go live** to jump to the newest step. Pick older runs from the list at the top right.

To watch the real browsers instead, tick **Also show real browser windows on this computer (slow motion)** before starting a run. Chromium windows then open on your screen, the element being used is outlined in orange, and each action pauses briefly (`live.slowmo_ms`, default 400 ms). This is slower and is meant for demos and for understanding a failure, not for daily runs.

## How it works

| # | Agent | Uses a model? | What it does |
| --- | --- | --- | --- |
| 1 | Requirement Analyst | optional | Splits the SRS into requirements; extracts field rules, access rules, features, status changes, performance targets; flags vague text and TBDs |
| 2 | Explorer | optional (only when a login is unclear) | Logs in like a tester (recorded steps, or reads the screen, or asks you) as each role and anonymously. Maps every reachable screen, form, field attribute, link, load time and accessibility gap, and every API call each screen makes. Clicks buttons, drop-down menus, tabs and pop-ups and records where each one leads. It never submits forms and never clicks logout, delete or similar actions |
| 3 | Reconciler | no | Compares the SRS with the app and gives every rule a status: Confirmed, Divergent, SRS-only, App-only, Ambiguous, Decided, Workflow or Not automated |
| 4 | Planner + Designer | no | Boundary values, invalid formats, empty mandatory fields, role-permission matrix, login enforcement, page health, links, accessibility, workflows, API health and access, record isolation, session and CSRF checks, load smoke, visual snapshots, imported manual cases |
| 4a | Functional Test Analyst | optional | Manual-tester style cases for logins, logout, navigation, forms and search, with preconditions, steps, test data and expected results (see Functional test cases) |
| 5 | Script Generator | no | One readable pytest function per case, traced to rule and requirement IDs |
| 6 | Executor | no | Runs the suite in parallel. Forms are submitted with browser validation bypassed, so the server's own validation is tested |
| 7 | Exploratory Tester | no | Acts as a curious user for each role (seeded, so a run can be repeated exactly): wanders the menus, fills data-entry forms with harmless markers such as `x<b>aq12345</b>`, and types the addresses of other roles' screens. Checks for server errors, JavaScript errors, missing scripts or images, input echoed back as HTML, and permission leaks against the approved access rules. Once per run it makes passive security checks: security headers, cookie flags and server-version disclosure |
| 8 | Security Scanner | no | Starts OWASP ZAP on this computer, spiders the portal, then browses every screen as each role through ZAP so it sees the logged-in pages. Passive by default (reads responses); active attack probes only when switched on |
| 9 | Triage + Bug Reporter | optional | One defect per root cause, with severity, steps, expected vs actual, screenshots and Playwright traces. Test failures and exploratory findings about the same problem merge into one defect |
| 10 | Healer | no | When a UI change breaks a locator or a workflow step (a renamed button), proposes the replacement for review; approving a workflow fix edits that line of project.yaml and keeps its comments. It never changes an expected result |
| 11 | Reporter | no | `reports/report.html`, `reports/rtm.csv`, `reports/rtm.xlsx`, `reports/defects.csv` |
| 1a | Requirement Writer | yes when configured | Rewrites every requirement into a clear statement, user story, steps (who does what), exceptions and Given/When/Then criteria; flags any number or role the source does not have. Without a model it writes the same fields from the standardised requirement |
| 4b | Workflow agent | no | Multi-user workflows from the SRS's status rules and each role's screens, across applications |
| 4c | Test Case Generation agent | yes when configured | Template cases for requirements nothing else covered (intent steps without a model) |
| 6a | Visual QA agent | yes when configured | Carries out intent steps and judges verify steps from the page; asks a person when it cannot |

Each agent's inputs, outputs and the agents it waits for are listed on the Execution page. A stage's hand-over is checked against its contract when it finishes, and the result is kept with the stage's checkpoint, so `pipeline --resume` continues from the first stage that did not finish.

The Exploratory Tester changes data, so use it only on a test environment. It never follows logout or delete links, and never submits a form that has a password or file field or whose button matches `exploratory.never_submit` (approve, reject, verify, pay, cancel and similar business actions; those belong in YAML workflows). Set `exploratory.submit_forms: false` on a shared environment, or `exploratory.enabled: false` to leave it out of the pipeline. Its security checks are passive: it reads headers and cookies and never attacks the site.

The 21 test types: functional cases (manual-tester style), page loads, access denied, links, form attributes, option lists, field rejects invalid, field accepts valid (both including file uploads and custom widgets), valid submission, workflows, OTP used only once, accessibility (axe-core, WCAG 2.2 AA), API health, API access, record isolation, security headers, session ends at logout, CSRF protection, load smoke, visual snapshot and imported manual tests. A test that fails is classed as a **defect** (the app is wrong), a **test issue** (the test is wrong, sent to the Healer), an **environment** problem (retried), or a **visual change** (waiting for review).

Every expected result says where it came from:
- **srs**: stated in the SRS;
- **decided**: you answered a question;
- **workflow**: you described the flow;
- **baseline**: rules every portal should meet, such as pages loading without HTTP errors, login enforced, links working and basic accessibility.

## Optional AI (No-AI, Local, Cloud or Hybrid)

Every project chooses an AI mode on its AI page (`/app/projects/<slug>/ai`); the default is **No AI**, where every
agent works with rules only. Agents ask for a *tier* (cheap, balanced, strong or vision), never a model.

- **Local**: a model on this computer, nothing leaves it. Install Ollama from https://ollama.com, run
  `ollama pull qwen3:4b`, and the AI page detects it (LM Studio on port 1234 works too).
- **Cloud**: provider keys (Anthropic, Gemini, OpenAI and friends) entered on the AI page, used only after you allow
  text (and separately screenshots) to be sent. Personal data is masked first. Each project has a monthly budget
  (default $10, warning at 80 %); at the cap the project drops back to No AI for the rest of the month and you are told.
- **Hybrid**: cheap work on the local model, demanding work in the cloud; at the cap it keeps the local model.

Check the keys with `python -m agentqa ai-test` (one tiny call per key); `python -m agentqa doctor -p projects\<name>`
shows which agent would use which model and why an agent has none. The model only sees what the rules could not
interpret, and its readings appear as Proposed rules with a confirmation question.

## Command line

```
.venv\Scripts\activate
python -m agentqa init projects\ur-uat --url https://uat.example.gov.in
python -m agentqa pipeline -p projects\ur-uat            # stops at the plan gate
python -m agentqa questions -p projects\ur-uat
python -m agentqa answer 12 0 -p projects\ur-uat
python -m agentqa approve --all -p projects\ur-uat
python -m agentqa pipeline --from generate -p projects\ur-uat
python -m agentqa defects --confirm DEF-001 DEF-003 -p projects\ur-uat
python -m agentqa pipeline --resume -p projects\ur-uat              # continue from the first unfinished stage
python -m agentqa teach-login --role citizen -p projects\ur-uat     # log in once yourself; AgentQA learns the steps
python -m agentqa write -p projects\ur-uat                          # Requirement Writer on its own
python -m agentqa run --only TC-0001 TC-0002 -p projects\ur-uat     # regenerate, run these, draft defects
python -m agentqa run --all-approved -p projects\ur-uat
python -m agentqa run --type functional -p projects\ur-uat     # regenerate, run the functional cases, draft defects
python -m agentqa export-cases -p projects\ur-uat              # functional test cases with results, as Excel
python -m agentqa import tests.xlsx --approve-ready -p projects\ur-uat
python -m agentqa ask "what failed in the last run" -p projects\ur-uat
python -m agentqa ci --fail-on High --min-score 70 -p projects\ur-uat
python -m agentqa doctor -p projects\ur-uat             # pilot readiness: logs in as every role and shows the steps
python -m agentqa security -p projects\ur-uat           # OWASP ZAP scan on its own
python -m agentqa sync -p projects\ur-uat               # two-way Jira / Azure DevOps sync (--test checks the connection)
python -m agentqa inbox -p projects\ur-uat              # keep the mock SMS/email inbox running while you test by hand
python -m agentqa ai-test                                # test every key on the AI providers page
python -m agentqa demo-portal                            # the two demo portals (8800 citizen, 8810 department)
python tools/acceptance.py --project projects\demo      # the 14 acceptance criteria against an executed run
```

Stages can also run one at a time: `analyze`, `explore`, `reconcile`, `write`, `design`, `generate`, `run`, `exploratory`, `security`, `triage`, `heal`, `report`. Every command-line run is recorded for Live View as well.

## Current limits (v0.8)

- **No real AI provider has been tried.** The failover logic, the Test Case Generation agent and the Visual QA agent were tested against local stand-ins for the provider APIs (`demo/mock_ai.py`); no AI service is reachable from the environment AgentQA is built in. The stand-in answers the Visual QA and test-case tasks by word overlap, which exercises the plumbing (grounding, quote checks, failover), not a model's judgement. Add a real key and press **Test** to confirm it in one call.
- **Vision needs a key that accepts images, with Send screenshots switched on.** Otherwise the Visual QA agent reads the page's text, controls and accessibility tree only.
- **No dashboard user accounts yet.** Role-based permissions on the dashboard (who may see or edit keys and passwords) need user accounts, planned for v1.0. Until then, keep the dashboard on this computer (it listens on 127.0.0.1 only) and rely on the Windows account.
- **Long timers need a clock hook.** OTP-expiry and idle-session tests run in seconds when the test environment has a clock hook (`functional.clock_hook`). Without one, waits longer than `functional.max_wait_s` are Not Run, not guessed.
- **Take-over is recorded as clicks and typing.** Drag-and-drop, file pickers and canvas drawing done by a person are not turned into steps, so AgentQA asks again for those.
- **Not unattended on live portals.** With **Ask me on screen**, OTPs, CAPTCHAs and steps the Visual QA agent cannot work out wait for you (`assist.timeout_s`, `visual_qa.ask_timeout_s`). A fixed test OTP or the mock inbox makes test-environment runs unattended.
- **Web portals and their REST APIs only.** No native mobile apps, and no GraphQL or SOAP yet.
- **CAPTCHA is never bypassed.** File downloads are not checked yet.
- **Security and load tests are smoke-level.** The ZAP scan is passive unless active scans are switched on, and neither is a penetration test. The load test is a few users for a few seconds.
- **The Windows installer build has not been run on Windows yet.** The zip with setup.bat is the tested way to install.
- **Zoho is an export, not a live sync.** The Zoho CSV imports into Zoho BugTracker / Projects / Sprints; two-way sync (issue states back into AgentQA) exists for Jira and Azure DevOps only. A Zoho API connector needs an OAuth client in your Zoho account and was not built or tested in this round.
- **API token detection covers the common cases.** A token in local/session storage (plain or inside JSON), in a cookie, or only in the page's memory (read from the page's own first API call). A token that changes on every request (request signing) or lives in a web worker is not recovered; those API tests are reported Blocked, never Passed.
- **Navigation teaching records clicks, typed text and addresses.** Drag-and-drop, file pickers and canvas are not replayed; a remembered path that no longer works is reported in Live View and can be shown again.

The full list of pending features, by release, is in the roadmap document.

## Acceptance

`python tools/acceptance.py --project <executed project> --junit <pytest junit xml>` writes `reports/acceptance.md`. For each of the 14 criteria it gives the executed evidence (counts, file paths, test names) and says plainly when something was shown only against the local AI stand-in. `--blocked` points at a run made with a deliberately wrong password, to show dependent tests Blocked. `--production` points at a design made with an application marked production, to show the data-changing cases left out. `docs/acceptance-v0.6-demo.md` is the report from the release run on the two-portal demo.

## AgentQA's own tests

`python -m pytest tests` runs AgentQA's unit tests (no browser or portal needed): OTP extraction, the mock inbox, SRS reading, Excel conversion against a real app map, project.yaml edits, the Jira and Azure DevOps loop, readiness and the assistant. v0.5 adds tests for the encrypted vault, how login boxes are recognised, the ask-the-tester box, the Gemini client (against a local stand-in for Google's API), the Functional Test Analyst and the Excel export. `python tools/e2e_assist.py` runs the human-in-the-loop check end to end (English first, take-over, remembered login, pause, Show how to log in, and since v0.8 Show AgentQA around: 25 checks) on the demo in its hard mode. v0.8 added tests that run a real browser against a small token-secured server: the Explorer must find where the bearer token is kept, and the generated runtime must send the same header so the API answers 200 for a logged-in role and 401 for an anonymous caller; plus the standard-template export, the Zoho export and multi-portal manual paths. v0.6 added tests for AI key failover (against local provider stand-ins), reading every document format including OCR, the source ledger and honest coverage, dispositions and the change log, the Test Case Generation agent, the stage contracts, execution statuses and scopes, pipeline resume, and the Visual QA agent in a real browser on the demo portal. `../.github/workflows/agentqa-selftest.yml` runs them on Linux and Windows with Python 3.12 and 3.13, adds a static security check and a dependency audit, then runs the full demo and fails if any seeded bug is missed or an unexpected defect appears.

## Folder layout

```
agentqa/            the agents, runtime library and web UI
demo/               demo portal (FastAPI), demo SRS, demo project.yaml, manual_tests.xlsx
ci/                 GitHub Actions, GitLab CI, Jenkins and Azure DevOps pipelines for your portal
installer/          Windows installer build (PowerShell + Inno Setup)
tests/, tools/      AgentQA's own tests, the demo regression check and the acceptance report
%APPDATA%\AgentQA\  AI providers: ai.vault (keys, encrypted) and ai.db (key states and the audit log)
projects/<name>/    one folder per portal
  project.yaml      settings
  srs/              uploaded SRS files
  imports/          manual test case sheets (.xlsx, .csv) to convert
  tests/            generated pytest + Playwright suite (commit it to git)
  runs/<run-id>/    results, screenshots and traces of failures
  runs/exploratory-<time>/  screenshots of exploratory findings
  reports/          report.html, rtm.csv, rtm.xlsx, defects.csv, acceptance.md
  visual/baselines/ approved screen snapshots for visual comparison
  .agentqa/         SQLite store, saved role sessions and the mock inbox's messages (keep private)
  .agentqa/vault.json  Test data page: accounts, recorded logins, data sets, keys (encrypted; the key stays
                    in your Windows profile, so a copied project folder cannot be read elsewhere)
  .agentqa/live/    Live View recordings: one folder of events and screenshots per run
```
