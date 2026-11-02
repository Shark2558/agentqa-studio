# AgentQA Studio

A multi-agent software-testing platform. Upload the requirements (or type them), point it at the application, and a
team of specialised agents understands the requirements, explores the application, designs and writes the tests, runs
them, files defects with evidence and delivers the report — on a schedule, with a live view of every agent, with or
without an AI model.

- **PRD:** `../01-PRD-AgentQA-Studio-v1.md` · **Discovery:** `../00-DISCOVERY-AND-QUESTIONS.md`
- **Engine:** `backend/` — the AgentQA Studio v0.8 engine (its own README is `backend/README.md`)
- **Frontend:** `frontend/` — new React + TypeScript app (from milestone M0.5)
- **Process:** ECC engineering loop, see `CLAUDE.md` and `.claude/rules/ecc/`

## Status

Milestone **M0.1** (repo, ECC, CI): in progress. See `docs/plans/m0-1-repo-and-ecc.md`.

## Quick start (developers)

```bash
make setup           # venv (outside the repo, see CLAUDE.md) + dependencies + Chromium
make test            # unit tests
make demo-portal     # in its own terminal: the demo portals on 8800 and 8810
make demo-regression # full demo pipeline; must find all 19 seeded bugs and nothing else
make dev             # v0.8 dashboard at http://127.0.0.1:8700
```

Non-technical owners: wait for the setup guide that ships with milestone M2.3.
