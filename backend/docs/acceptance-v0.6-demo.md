# AgentQA Studio 0.6: acceptance against Requirement 8

Evidence from the executed project at `projects/demo (two-portal demo, run 30 Oct 2026)`. Statuses: Demonstrated (executed evidence), Demonstrated with a stand-in (only the local AI stand-in), Partly, Not demonstrated.

## 1. LLM configuration: Demonstrated with a stand-in

- 6/6 gateway tests passed against local provider stand-ins (OpenAI, Anthropic, Gemini, Azure APIs): edit gives a dead key a fresh chance, failover walks the keys and never retries a rejected key, keys are encrypted scrubbed from logs and masked for the dashboard, provider fallback model fallback and billing, quota timeouts and all failed, connection lists models and picks one
- Ten providers on the AI providers page; several keys per provider with priority, model and fallback model; keys encrypted, masked on screen and scrubbed from logs.
- **Not shown:** No real provider key was used: none is reachable from the build environment. Add yours on the AI providers page and press Test.

## 2. Document processing: Demonstrated

- 6 documents in 6 formats read: Demo_Certificate_Portal_SRS.docx (docx, read, 35 requirement(s)); annexure_scan.png (png, read, read with Tesseract OCR, 2 requirement(s)); api_rules.json (json, read, 1 requirement(s)); notifications.csv (csv, read, 2 requirement(s)); portal_faq.html (html, read, 2 requirement(s)); scheme_requirements.xlsx (xlsx, read, 3 requirement(s))
- 45 of 45 requirements standardised (title, actors, flows, exceptions, acceptance criteria, use case, source reference)
- 59 passages kept in the source ledger

## 3. Requirement traceability: Demonstrated

- 45 requirements: Needs clarification 7, Covered by tests 38
- 7 requirement(s) have no case, each with its reason: FR-11 waits for clarification (open question); its expected result is not known yet; FR-13 waits for clarification (needs clarification: tbd); its expected result is not known yet; TBL-031 waits for clarification (needs clarification: tbd); its expected result is not known yet; NFR-01 waits for clarification (needs clarification: quickly); its expected result is not known yet; NFR-04 waits for clarification (needs clarification: as applicable, multiple languages); its expected result is not known yet; SRS-041 waits for clarification (open question); its expected result is not known yet; TBL-042 waits for clarification (open question); its expected result is not known yet
- RTM (source → requirement → use case → case → execution → result → defect): projects/demo (two-portal demo, run 30 Oct 2026)/reports/rtm.xlsx (present)
- Coverage claimed complete: False (it is not claimed while any gap, clarification, unread document or unexplained passage remains: 1 passage(s) to review)

## 4. Test case generation: Partly

- 214 cases in the standard template, by test type: Access control (RBAC) 31, Field validation 28, Exception handling 27, Navigation 25, Authentication 24, Visual 20, Accessibility 15, Boundary 13, Session 7, Positive 6, API 5, Negative 4, Integration 3, Performance 3, Security 2, End to end 1
- 9 case(s) from the Test Case Generation agent for requirements nothing else covered (API-01, BR-01, BR-02, BR-03, FR-16, FR-30, FR-31, NT-01, NT-02); without a model they are use-case intent steps
- Model path (grounding, intent steps for unknown controls, every case traced): unit test passed
- **Not shown:** In this run there was no AI key, so the generated cases came from the use cases, not from a model. With a key on the AI providers page the model drafts up to four cases per requirement.

## 5. Credential management: Demonstrated

- Logins that succeeded, per role and application: admin@department, citizen@citizen, citizen__peer@citizen, clerk@department, officer@department
- Applications: Citizen Portal http://127.0.0.1:8800 (Test / QA); Department Portal http://127.0.0.1:8810 (Test / QA)
- 261 generated tests, step logs, run logs, Live View events and reports searched for the accounts' passwords: none found; tests carry tokens ({password}, {mobile}) filled in at run time
- The demo keeps its demo passwords in project.yaml (marked demo data); real accounts go on the Test data page, encrypted (unit test test_vault_keeps_secrets_encrypted_and_keeps_them_when_the_box_is_left_empty: passed)

## 6. OTP authentication: Demonstrated

- 4 OTP login(s) in this run (4 ok); the demo's OTPs come from its SMS inbox, so no person was needed
- Pause on the live screen and resume with the OTP a person types: unit test passed
- Live portals: the run stops at the OTP screen, asks in every open dashboard page, and records 'otp_timeout' when nobody answers

## 7. Mandatory login validation: Demonstrated

- 29 login and session cases executed: Passed 27, Failed 2
- They run in their own serial phase (aq_login) and none was skipped. The 2 failures are the demo's seeded login bugs (a 9-digit mobile accepted, Resend OTP sends nothing). When a login fails, the tests that need it are Blocked (criterion 13)

## 8. Visual QA: Demonstrated with a stand-in

- 4/4 Visual QA tests passed in a real browser on the demo portal: a quote that is not on the page is never a pass, act clicks only a control it was shown and verify quotes the page, grounding and production guards, without a model or a person nothing is guessed
- In this run (no AI key) the 9 intent case(s) were Not Run 9, each with the reason: never Passed without a check
- Same 9 case(s) run with the stand-in key (run-20261030-165434): the Visual QA agent was called from the tests through the AI gateway; Blocked 9; every verdict NOT VERIFIED because the page did not show the expected result, so none was Passed
- **Not shown:** The model judgement was exercised with the word-overlap stand-in, not a real vision model.

## 9. Multi-user workflows: Demonstrated

- TC-0052 End to end: application submitted by citizen, then verified by clerk, then approved by officer; citizen sees 'Approved': Passed, 6 check(s) passed across Citizen Portal → Department Portal → Citizen Portal → Department Portal → Citizen Portal

## 10. Multiple URLs: Demonstrated

- 2 applications; cases per application (the workflow counts in both): Citizen Portal 134 (107 passed, 20 failed), Department Portal 82 (72 passed, 8 failed)
- Cross-portal workflow passes the application number from one portal to the next

## 11. Evidence-based results: Demonstrated

- 177 Passed result(s) in run-20261030-164403: 177 with every evidence file on disk, 177 whose step log records at least one checked expected result
- 0 test(s) that checked nothing were turned into failures (NOT VERIFIED), not passes
- Run contract: 0 issue(s)

## 12. Reporting: Demonstrated

- Execution page: 45 requirements, 214 cases, 205 executed, 177 passed, 28 failed, 0 blocked, 9 not run, 19 open defects; coverage by module, requirement, application and role; workflow status; defect records with requirement, case, URL, time and logs
- Reports: acceptance.json, acceptance.md, defects.csv, report.html, rtm.csv, rtm.xlsx

## 13. Failure handling: Demonstrated

- run-20261030-164403: 177 passed, 28 failed, 0 blocked, 9 not run
- Broken officer password (second run): 21 officer case(s) Blocked, 0 Passed; login log: ok, refused
- Every AI key failing: the gateway reports 'all_failed' and work continues without a model (unit test passed)

## 14. Security: Demonstrated

- Production applications are read-only: with the Department Portal marked production, 2 data-changing case(s) were left out and listed, 34 remain on the citizen test site
- AI keys and passwords encrypted (Fernet); keys masked on screen and scrubbed from logs; mobile numbers, emails and 12-digit numbers redacted before any AI call; screenshots sent only when allowed
- OWASP ZAP active scan only on non-production applications; CAPTCHAs are never bypassed (a person types them)
