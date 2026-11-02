# Plan — M0.1 Repo & ECC

**Milestone:** M0.1 (PRD §9, Phase 0). **Owner approval:** direction approved 2 Nov 2026; this slice has no 🔒 marker.

## Goal

A mono-repo `agentqa-studio/` that holds the v0.8 engine **unchanged**, proven by its own unit tests and the 19-seeded-bug demo regression, with the ECC rules installed, a `CLAUDE.md` that binds the engineering loop, and CI that runs on every push.

## Out of scope

Any change to agent behaviour, UI, API, Docker (M0.2), real-AI validation (M0.3), design system (M0.4).

## Steps

1. Create `agentqa-studio/` next to the planning docs; `git init`; `.gitignore` (venvs, caches, projects data, secrets).
2. Copy `AgentQA-Studio-v0.8-clean/AgentQA-Studio-v0.8/` → `backend/` (package `agentqa`, `demo/`, `tests/`, `tools/`, `ci/`, `installer/`, `requirements.txt`, `.bat` launchers). Byte-for-byte; no edits in this slice except path fixes forced by the move (recorded below).
3. Install ECC rules: copy `rules/common`, `rules/python`, `rules/typescript` **whole** into `.claude/rules/ecc/`. The ECC plugin itself (`/plugin marketplace add https://github.com/affaan-m/ECC` → `/plugin install ecc@ecc`) is a Claude Code command the owner runs once; recorded as a follow-up for him.
4. Write `CLAUDE.md` (template in `02-BUILD-HANDOFF.md`), `README.md`, `Makefile`.
5. Backend venv (Python 3.12 preferred; 3.14 is what the machine has — verify compatibility), `pip install -r requirements.txt`, `playwright install chromium`.
6. Verify: `pytest backend/tests` green; demo regression (`demo-portal` + `demo-project` + `pipeline` + `tools/check_demo.py`) finds 19/19 seeded bugs and nothing else.
7. CI: adapt `.github/workflows/agentqa-selftest.yml` to the `backend/` layout.
8. Fresh-context review of the slice (`code-reviewer`), commit.

## Tests first

This slice adds no behaviour, so the "failing tests" are the **existing** suites run from the new location: they fail until the move and path fixes are right. The demo regression is the integration test.

## Verification (3 Nov 2026, this machine)

- `pyflakes agentqa demo tools tests`: clean.
- `pytest -q tests`: **64 passed** in 52 s (63 existing + `test_store.py`).
- Demo regression: portal on 8800/8810, `demo-project` → `pipeline --policy srs_wins --auto-approve` (5 min 52 s,
  OWASP ZAP not installed so the Security Scanner stage was skipped, as designed) → `tools/check_demo.py`:
  **19/19 seeded bugs found, 0 unexpected defects.**
- Git: 175 files staged; `.gitattributes` pins LF (CRLF for `.bat/.cmd/.ps1`); index verified with `git ls-files --eol`.

## Review (fresh context, code-reviewer + python-reviewer role)

Verdict **Approve**: 0 CRITICAL, 0 HIGH, 4 MEDIUM, 9 LOW. Confirmed independently that the engine diff is limited to the
stated changes and that the WAL retry is bounded and correct (RED 3/3 on the old store, GREEN 3/3 on the new).
Fixed before commit: all four MEDIUMs (`.gitignore` patterns anchored; `test_store.py` asserts no opener hung;
`_enable_wal` checks the PRAGMA's answer instead of trusting the absence of an error; `make demo-regression` now runs
the whole pipeline, `demo-check` only the check) and LOW 1, 2, 4, 5, 7, 8. Left for later: LOW-3 (style only), LOW-6
(the first venv at `backend/.venv` still exists on Drive — git-ignored; owner to delete), LOW-9 (fake `sk-ant-…`
fixture keys in `tests/test_ai_gateway.py` will trip GitHub secret scanning on first push; allow-list them then).
Re-verified after the fixes: lint clean, `test_store.py` 3/3, full suite 64 passed.

## Done criteria

- `pytest` green from `backend/`.
- `python tools/check_demo.py projects/demo` reports all 19 seeded bugs, 0 unexpected.
- `.claude/rules/ecc/{common,python,typescript}` present; `CLAUDE.md` present.
- CI workflow updated; first commit made.

## Risks

- Google Drive folder: the venv and Playwright browsers must stay out of git and ideally out of Drive sync (use `backend/.venv`, ignored; note for the owner).
- Python 3.14 on this machine vs. 3.11/3.12 in the engine's CI: run tests on 3.14; if a dependency fails, pin a 3.12 venv.
- Paths in `.bat` files, workflows and docs that assume repo root = engine root.

## Record of forced changes

- Engine copied to `backend/` unchanged (no edits to any `.py`, `.bat`, template or data file). The `.bat` launchers
  use `%~dp0`, so they work from `backend/` as before.
- `.github/workflows/*.yml` moved to the repo root; added `defaults.run.working-directory: backend`,
  `cache-dependency-path: backend/requirements.txt`, and `backend/` prefixes on artifact paths. Python matrix 3.11/3.12 →
  3.12/3.13 (ADR 0001).
- ECC rules copied from `affaan-m/everything-claude-code` @ `b38be6a7f635` (29 Oct 2026): `common`, `python`,
  `typescript`, `react`, `web`, plus the rules README and the MIT licence as `LICENSE-ECC-MIT`.
- Backend venv created with Python 3.13 (`py -3.13`), the closest installed version to the engine's 3.11/3.12 CI matrix.
- **Venv moved out of Google Drive** (`~/.venvs/agentqa-studio`). First run of `tests/test_ai_gateway.py::
  test_failover_walks_the_keys_and_never_retries_a_rejected_key` took 101 s and failed on a 30-second cooldown
  assertion. Diagnosis: not the engine; `httpx.Client()` creation took 45–57 s because OpenSSL read certifi's bundle
  through Drive's virtual filesystem (0.35 s from a local folder). Makefile, CLAUDE.md and ADR 0001 updated.
- **Lint fixes only (no behaviour change):** `agentqa/masterplan.py` dropped two unused imports and one `f` prefix on a
  string with no placeholders; `tests/test_v08.py` dropped an unused import and replaced `import agentqa_live  # noqa`
  with `importlib.import_module("agentqa_live")` (pyflakes does not honour `noqa`). v0.8's lint step would have failed
  on these, so they were committed after its last CI run.
- **One engine fix, TDD'd:** `tests/test_v05.py::test_assist_waits_for_an_answer_from_the_dashboard` failed
  deterministically (3/3) with `sqlite3.OperationalError: database is locked` from `PRAGMA journal_mode=WAL` when an
  agent thread and the main thread both created `Store()` on a brand-new database (Python 3.13.9 / SQLite 3.51.0; the
  busy timeout does not cover a journal-mode switch). New test `tests/test_store.py` (6 threads open the same fresh DB
  at once) was RED 2/3, then `agentqa/store.py` gained `_enable_wal()` (retry on "locked", 100 × 50 ms) and it is GREEN
  5/5. Behaviour is otherwise unchanged. Full suite: 64 passed, lint clean.
