# ADR 0001 — Mono-repo; keep the v0.8 engine, rebuild the shell

**Date:** 3 Nov 2026 · **Status:** accepted · **Decides:** PRD decisions D1, D9 (layout consequences)

## Context

AgentQA Studio v0.8 is ~21,500 lines of Python with 20 agents, a proven evidence model and a 19-seeded-bug demo
regression. The v1 vision adds a new onboarding flow, a React UI, a scheduler, accounts, reports in every format and
cloud deployment. The owner is non-technical and will have an AI agent build v1 slice by slice.

## Decision

- One repository `agentqa-studio/` holds everything: `backend/` (the engine, moved byte-for-byte), `frontend/`
  (new), `deploy/`, `docs/`, `.claude/rules/ecc/`.
- The engine package stays `agentqa` and keeps its CLI, tests, demo, tools and installer so that every existing
  command still works from `backend/`. New code is added beside it (`agentqa/api`, `agentqa/orchestrator`,
  `agentqa/scheduler`, `agentqa/reports`), never by rewriting agents without a plan.
- The demo regression (`tools/check_demo.py`, 19 found / 0 extra) is the contract that the engine still works
  after every slice; CI runs it on every push.
- CI workflows live at the repo root and run with `working-directory: backend`.

## Consequences

- Moving first and changing nothing let M0.1 prove the move with the engine's own tests.
- The Python matrix moves to 3.12/3.13 (the owner's machine has 3.13 and 3.14; 3.11 is dropped from CI).
- Google Drive hosts the repo; the virtual environment lives **outside** it at `~/.venvs/agentqa-studio`.
  Measured in M0.1: with the venv on Drive, `ssl.SSLContext.load_verify_locations(certifi)` took 45–57 s
  (0.35 s from a local folder), so every `httpx.Client()` stalled and a gateway test timed out. Drive's virtual
  filesystem serves OpenSSL's many small reads slowly; Python's own `read()` of the same file is fast.
  Playwright browsers are in the user profile (`%LOCALAPPDATA%\ms-playwright`) as usual.
- The old flat `AgentQA-Studio-v0.8-clean/` folder stays untouched as the reference copy until v1 ships.
