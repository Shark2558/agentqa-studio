# AgentQA Studio — one image for the dashboard and for pipeline jobs.
# Build from the repo root:   docker build -f deploy/Dockerfile -t agentqa-studio:dev .
# Dashboard (default):        docker run --rm -p 127.0.0.1:8700:8700 -v agentqa-data:/data agentqa-studio:dev
# Any engine command as a job: docker run --rm -v agentqa-data:/data agentqa-studio:dev python -m agentqa pipeline -p /data/projects/<name>
#
# python:3.12-slim (Debian 13 "trixie", pinned so `playwright install --with-deps` always meets the release it was
# built for) + Playwright's Chromium and its system libraries + Tesseract for scanned requirement documents.
# Chosen over Microsoft's 2 GB Playwright image to keep the download small (ADR 0001 / plan m0-2-docker.md).
# ---- stage 1: build the React app (frontend/dist), served by the backend at /app ----
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: the backend image ----
FROM python:3.12-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    HOME=/data/home \
    AGENTQA_HOME=/data/home/.agentqa \
    AGENTQA_PROJECTS=/data/projects

# curl: health checks. tesseract-ocr: OCR of scanned pages (documents.py finds it on PATH).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend

# Dependencies first, so code changes do not re-download Chromium. deploy/constraints.txt pins every package to the
# versions of the last good build (regenerate: docker run --rm agentqa-studio:dev pip freeze > deploy/constraints.txt).
COPY backend/requirements.txt ./requirements.txt
COPY deploy/constraints.txt /tmp/constraints.txt
RUN pip install -r requirements.txt -c /tmp/constraints.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/ms-playwright

COPY backend/ ./
COPY --from=web /web/dist /srv/frontend/dist

# Run as an unprivileged user. Only /data (a volume) is writable; the engine's code stays read-only to the user
# that executes generated tests (PYTHONDONTWRITEBYTECODE keeps Python from wanting to write there).
RUN useradd --system --uid 10001 --home-dir /data/home --shell /usr/sbin/nologin agentqa \
    && mkdir -p /data/projects /data/home/.agentqa \
    && chown -R agentqa:agentqa /data
USER agentqa
VOLUME ["/data"]
EXPOSE 8700

CMD ["python", "-m", "agentqa", "ui", "--host", "0.0.0.0", "--port", "8700", "--projects-dir", "/data/projects"]
