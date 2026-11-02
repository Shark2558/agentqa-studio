# Plan — M0.2 Docker

**Milestone:** M0.2 (PRD §9, Phase 0). **Marker:** none (🔒 not required; no auth, secrets or network exposure beyond localhost).

## Goal

One container image that (a) serves the current v0.8 dashboard with `docker compose up` on the owner's laptop and
(b) runs the pipeline as a job, so the Google Cloud edition (M2.3) can reuse it unchanged.

## Acceptance (from the PRD)

The demo pipeline completes inside the container on Windows (Docker Desktop) and `tools/check_demo.py` reports
19/19 seeded bugs, 0 unexpected.

## Design

- **Base image:** `python:3.12-slim` + `playwright install --with-deps chromium`. Chosen over Microsoft's Playwright
  image (~2 GB) because the owner's connection pulled 320 MB in 8 minutes before failing in the earlier attempt; the
  slim route downloads ~600 MB in total. Python 3.12 matches the Windows installer bundle and the CI matrix.
- **Layout in the image:** engine at `/srv/backend`; data under `/data` (projects at `/data/projects`, AgentQA home
  with the AI key vault and audit db at `/data/home`), owned by a non-root user `agentqa`. `/data` is a named volume.
- **Entry points (same image):** default `CMD` = dashboard `python -m agentqa ui --host 0.0.0.0 --port 8700
  --projects-dir /data/projects`; any other `python -m agentqa …` command works as a job
  (`docker compose run runner pipeline -p /data/projects/demo …`).
- **Compose (`deploy/docker-compose.yml`):** services `portal` (the two demo portals, 8800/8810), `dashboard`, and
  `runner` (profile `demo`, one-shot: demo-project → pipeline → check_demo). `dashboard` and `runner` use
  `network_mode: service:portal` so the engine's demo `project.yaml`, which points at `127.0.0.1:8800/8810`, works
  unchanged; the ports are therefore published on `portal`. For a real portal the owner edits `base_url`, and the
  demo `portal` service is simply not started.
- **Secrets:** `AGENTQA_VAULT_KEY` may be passed from a `.env` file (never committed); otherwise the vault key file is
  created inside `/data/home` on the volume (Linux path of `vault._key_path`).
- **OWASP ZAP:** not bundled in M0.2 (the Security Scanner stage is skipped, as designed); revisit with the cloud image.
- **Smoke test (`deploy/smoke.sh`), written first:** builds the image, runs the unit tests inside it, starts
  portal + dashboard, checks `GET /` on 8700, runs the `runner` job, asserts `check_demo` passes, tears down.
  CI gets a `docker` job that runs it on `ubuntu-latest`.

## Out of scope

New UI, API, scheduler, cloud deployment, ZAP in the image, multi-arch builds.

## Risks

- Download size on a slow connection: build in the background; layers cache, so a retry resumes.
- Docker Desktop on Windows with a Google Drive bind mount is slow/unreliable: use a named volume for `/data`, and
  copy reports out with `docker compose cp` when needed.
- `network_mode: service:` is unsupported in Compose's Swarm mode only; fine for Docker Desktop and Cloud Run Jobs
  (which do not use compose at all).

## Review (fresh context, code-reviewer + security-reviewer role)

First verdict **Block**: 1 CRITICAL, 2 HIGH, 6 MEDIUM, 4 LOW. The CRITICAL was real and would have hurt the owner:
`smoke.sh` tore down the *same* compose project that `make up` creates, deleting the data volume (projects, reports,
**vault key**). Fixed before any commit:
- CRITICAL-1: the smoke test runs under its own compose project (`-p agentqa-smoke`), so its volume is separate.
- HIGH-2: step 5 now greps the project card link `href="/p/demo"` as a standalone statement (the old check matched
  the "Try the demo" button on an empty dashboard and was exempt from `set -e`).
- HIGH-3: on failure the smoke test prints the last container logs and archives `projects/demo/{reports,runs}` to
  `smoke-reports.tgz`, which CI uploads as an artifact, before tearing down.
- MEDIUM-4: base image pinned to `python:3.12-slim-trixie` (the release the first build resolved to) and every
  package pinned through `deploy/constraints.txt` (41 lines, `pip freeze` of the good build).
- MEDIUM-5: `restart: on-failure` instead of `unless-stopped` (no auto-start on every boot; documented recovery is
  `make up`). MEDIUM-6: documented that `portal` must always run because it owns the network namespace and ports.
- MEDIUM-7: engine code is no longer writable by the runtime user (chown only `/data`; `PYTHONDONTWRITEBYTECODE=1`);
  verified by the smoke run after the change. MEDIUM-8: `.dockerignore` gained the state globs from
  `backend/.gitignore`. LOW-10/11/13: README notes on the vault key and bind mounts; `ui` log line shows the real host.
- Deferred, recorded as follow-ups: MEDIUM-9 (CI builds the 1.3 GB Chromium layer cold on every run and runs the
  demo twice — add buildx GHA cache or gate the `docker` job on `deploy/**` changes once the repo is on GitHub);
  LOW-12 (Chromium is unsandboxed inside the container, as Playwright defaults; never run the image as root; add
  `shm_size: 1g` if Chromium ever crashes on heavy pages).

## Verification (3 Nov 2026, Docker Desktop on Windows)

`bash deploy/smoke.sh` on alternate host ports (18700/18800/18810): image built on `python:3.12-slim-trixie`;
**67 unit tests passed inside the image**; portal + dashboard healthy; `runner` job: pipeline 214 tests in 178 s,
exploratory 144 steps, security skipped (no ZAP), triage 19 defects; **`check_demo`: 19/19 seeded bugs, 0 unexpected**;
dashboard shows `/p/demo`. Clean tear-down of the `agentqa-smoke` project only. Host lint clean.

## Record of changes

- New: `deploy/Dockerfile`, `deploy/docker-compose.yml`, `deploy/smoke.sh`, `.dockerignore`; Makefile targets `image`,
  `up`, `down`, `smoke`; README "Run it in Docker" section; CI job `docker` (runs `deploy/smoke.sh`).
- Engine: **one small, TDD'd change.** The demo portals were hard-wired to 127.0.0.1, which Docker cannot publish
  (the first smoke run came up healthy inside the container but unreachable from the host). `demo/portal/serve.py`
  gained `--host` (default still loopback) with `parse_args()`/`build_servers()` split out, and `agentqa demo-portal`
  passes it through; `tests/test_demo_portal_host.py` (3 tests) was RED, then GREEN. The dashboard already had
  `--host`; the demo project's `127.0.0.1` URLs are honoured by sharing the portal's network namespace.
- First build on this machine: 4 min 40 s (Chromium 120 MiB + system libraries; layers cached afterwards).
- `useradd` warns that uid 10001 exceeds `SYS_UID_MAX`; harmless (a fixed uid makes volume ownership predictable).
- Image size 2.1 GB (Chromium + its system libraries dominate). Slimming (headless-shell only, removing build tools)
  is a follow-up, not an M0.2 requirement.
- First smoke run: unit tests passed inside the image (64), then `compose up` failed because host port 8810 was still
  held by the demo portal started during the M0.1 regression. Host ports are now configurable
  (`AGENTQA_DASHBOARD_PORT`, `AGENTQA_PORTAL_PORT`, `AGENTQA_DEPT_PORT`; container ports fixed) and `smoke.sh` reads
  the same variables.
