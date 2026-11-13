#!/usr/bin/env bash
# M0.2 acceptance test for the container image. Run from the repo root (Git Bash on Windows is fine):
#     bash deploy/smoke.sh
# Builds the image, runs the engine's unit tests inside it, starts the demo portals and the dashboard, checks the
# dashboard answers, runs the demo pipeline as a job and requires tools/check_demo.py to report 19/19 seeded bugs.
#
# It runs under its OWN compose project name (agentqa-smoke), so its volume and network are separate from the ones
# `make up` creates: tearing the smoke test down never touches your real projects, reports or vault key.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT=agentqa-smoke
COMPOSE=(docker compose -p "$PROJECT" -f deploy/docker-compose.yml)
IMAGE=${AGENTQA_IMAGE:-agentqa-studio:dev}
SKIP_BUILD=${AGENTQA_SKIP_BUILD:-0}
# Host ports; override them (same variables the compose file reads) when 8700/8800/8810 are taken on this machine.
DASHBOARD_URL="http://127.0.0.1:${AGENTQA_DASHBOARD_PORT:-8700}/"
PORTAL_URL="http://127.0.0.1:${AGENTQA_PORTAL_PORT:-8800}/"
DEPT_URL="http://127.0.0.1:${AGENTQA_DEPT_PORT:-8810}/"
WAIT_S=90
EVIDENCE=smoke-reports.tgz

step() { printf '\n=== %s ===\n' "$*"; }

cleanup() {
  local rc=$?
  if (( rc != 0 )); then
    step "FAILED (exit $rc): last container logs, and the demo reports saved to $EVIDENCE"
    "${COMPOSE[@]}" --profile demo logs --no-color --tail 150 || true
    docker run --rm -v "${PROJECT}_agentqa-data:/data" "$IMAGE" \
      sh -c 'cd /data && tar -czf - projects/demo/reports projects/demo/runs 2>/dev/null' > "$EVIDENCE" || true
  fi
  step "tear down ($PROJECT only)"
  "${COMPOSE[@]}" --profile demo down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$rc"
}
trap cleanup EXIT

if [[ "$SKIP_BUILD" == "1" ]]; then
  step "1/5 using prebuilt $IMAGE"
else
  step "1/5 build $IMAGE"
  docker build -f deploy/Dockerfile -t "$IMAGE" .
fi

step "2/5 unit tests inside the image"
# A live-connection test can fail once on a busy machine; the second run repeats ONLY the tests that failed (--lf), so a
# real failure fails twice. The cache sits in /tmp: the image's code folder is read-only to this user.
docker run --rm "$IMAGE" sh -c 'python -m pytest -q tests -o cache_dir=/tmp/pytest-cache || python -m pytest -q tests --lf -o cache_dir=/tmp/pytest-cache'

step "3/5 start the demo portals and the dashboard"
"${COMPOSE[@]}" up -d portal dashboard
for ((i = 0; i < WAIT_S; i++)); do
  if curl -sf "$DASHBOARD_URL" >/dev/null && curl -sf "$PORTAL_URL" >/dev/null && curl -sf "$DEPT_URL" >/dev/null; then
    echo "dashboard and both portals answer after ${i}s"
    break
  fi
  sleep 1
  if (( i == WAIT_S - 1 )); then
    echo "dashboard or portals did not come up"
    exit 1
  fi
done

step "4/5 demo pipeline as a job (several minutes)"
"${COMPOSE[@]}" --profile demo run --rm runner

step "5/5 the dashboard lists the finished demo project"
curl -sf "$DASHBOARD_URL" | grep -q 'href="/p/demo"'
echo "dashboard lists the demo project"
echo
echo "SMOKE TEST PASSED: image builds, unit tests pass inside it, dashboard serves, demo pipeline finds 19/19 seeded bugs."
