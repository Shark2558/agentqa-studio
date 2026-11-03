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

**Phase 0 complete** (M0.1 repo+ECC+CI · M0.2 Docker · M0.3 real-AI validation · M0.4 design system · M0.5 `/api/v1` + React app shell at `/app`). **Phase 1:** M1.1 onboarding wizard done (six steps at `/app/projects/new`: documents with read verdicts, typed requirements with the Requirement Chat agent, accounts into the vault, address check). Next: M1.2 AI modes & selector. Plans in `docs/plans/`.

## Quick start (developers)

```bash
make setup           # venv (outside the repo, see CLAUDE.md) + dependencies + Chromium
make test            # unit tests
make demo-portal     # in its own terminal: the demo portals on 8800 and 8810
make demo-regression # full demo pipeline; must find all 19 seeded bugs and nothing else
make dev             # v0.8 dashboard at http://127.0.0.1:8700
```

## Run it in Docker (laptop)

Needs Docker Desktop. From the repo root:

```bash
make up              # builds the image on first use; dashboard at http://127.0.0.1:8700, demo portals on 8800/8810
```

```bash
docker compose -f deploy/docker-compose.yml --profile demo run --rm runner   # the demo pipeline as a job (5-10 min)
```

```bash
make down            # stop (your projects and reports stay in the data volume)
```

Projects, reports and the encrypted vault live in the Docker volume `agentqa-studio_agentqa-data`. Deleting that
volume (`docker compose -f deploy/docker-compose.yml down --volumes`) also deletes the **vault key**, after which saved
test accounts and AI keys cannot be read; set `AGENTQA_VAULT_KEY` in `deploy/.env` first if you want the key to survive.
Keep the data in a named volume, not a bind mount of a Google Drive folder (Drive is slow and its permissions break
the non-root container user). If 8700/8800/8810 are already in use on your machine, set `AGENTQA_DASHBOARD_PORT`,
`AGENTQA_PORTAL_PORT` and/or `AGENTQA_DEPT_PORT` before the commands above. The `portal` container (the demo portals)
always runs: the dashboard shares its network, and it is harmless when your project points at your own application. `make smoke` runs the whole M0.2
acceptance test (build, unit tests inside the image, dashboard up, demo pipeline finds 19/19 seeded bugs).

Non-technical owners: wait for the setup guide that ships with milestone M2.3.
