# AgentQA Studio — developer commands. Use Git Bash (or any POSIX shell) on Windows.
#
# The virtual environment lives OUTSIDE the repository on purpose: this repo is in a Google Drive folder, and
# Drive's virtual filesystem makes OpenSSL's read of the certificate bundle take ~45 s per httpx.Client()
# (ADR 0001, M0.1 plan). Override with `make PY=/path/to/python <target>` if you keep your venv elsewhere.
VENV ?= $(or $(HOME),$(USERPROFILE))/.venvs/agentqa-studio
PY ?= $(VENV)/Scripts/python.exe
ifeq (,$(wildcard $(PY)))
PY := $(VENV)/bin/python
endif
DEMO := projects/demo

COMPOSE := docker compose -f deploy/docker-compose.yml
IMAGE ?= agentqa-studio:dev

.PHONY: setup test lint demo-portal demo-regression demo-check dev image up down smoke

setup:            ## create the venv outside the repo and install everything
	py -3.13 -m venv "$(VENV)" || python3 -m venv "$(VENV)"
	"$(PY)" -m pip install -q -r backend/requirements.txt pyflakes
	"$(PY)" -m playwright install chromium

test:             ## unit tests (no browser, no portal)
	cd backend && "$(PY)" -m pytest -q tests

lint:             ## unused and undefined names; design-token contrast (WCAG) in both themes
	cd backend && "$(PY)" -m pyflakes agentqa demo tools tests
	"$(PY)" -I frontend/design-system/check_contrast.py

demo-portal:      ## the two demo portals on 8800 (citizen) and 8810 (department); keep it running in its own terminal
	cd backend && "$(PY)" -m agentqa demo-portal --port 8800

demo-regression:  ## full demo pipeline, then the 19-seeded-bug check (needs `make demo-portal` running elsewhere)
	cd backend && "$(PY)" -m agentqa demo-project $(DEMO)
	cd backend && "$(PY)" -m agentqa pipeline -p $(DEMO) --policy srs_wins --auto-approve
	cd backend && "$(PY)" tools/check_demo.py $(DEMO)

demo-check:       ## only the 19-seeded-bug check against an already completed demo run
	cd backend && "$(PY)" tools/check_demo.py $(DEMO)

dev:              ## the v0.8 dashboard at http://127.0.0.1:8700 (until the new UI lands in M0.5)
	cd backend && "$(PY)" -m agentqa ui --port 8700 --projects-dir projects

image:            ## build the container image (dashboard + jobs)
	docker build -f deploy/Dockerfile -t $(IMAGE) .

up:               ## dashboard + demo portals in Docker: http://127.0.0.1:8700
	$(COMPOSE) up -d portal dashboard

down:             ## stop the containers (keeps the data volume)
	$(COMPOSE) --profile demo down --remove-orphans

smoke:            ## M0.2 acceptance: build, unit tests in the image, dashboard up, demo pipeline finds 19/19
	bash deploy/smoke.sh
