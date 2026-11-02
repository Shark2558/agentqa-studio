"""Test data setup and cleanup around a run, through the portal's API or its database.

project.yaml:

  data:
    around: [explore, run, exploratory]  # stages that run setup first (explore: setup only), the default
    setup:
      - name: Reset demo data
        http: {method: POST, url: /test-support/reset, headers: {X-Test-Key: demo-reset-key}, expect_status: 200}
      - name: Create a pending application as citizen
        http: {method: POST, url: /api/applications, as_role: citizen, json: {cert_type: income}}
    cleanup:
      - name: Remove applications made by tests
        sql: {dsn_env: AGENTQA_DB_DSN, statement: "DELETE FROM applications WHERE applicant_name LIKE 'Test%'"}

HTTP steps can send the saved login of a role (as_role). SQL steps accept sqlite:///path, and
postgresql:// or mysql:// when psycopg or pymysql is installed. Put connection strings in an
environment variable (dsn_env), never in project.yaml. A failing setup step stops the run; a
failing cleanup step is reported and the run continues.
"""
from __future__ import annotations

import json
import os
import time
from urllib.parse import urlparse

import httpx

from agentqa import live
from agentqa.util import log, warn


def _cookies(project, role: str | None) -> dict:
    if not role:
        return {}
    f = project.auth_file(role)
    if not f.exists():
        return {}
    state = json.loads(f.read_text(encoding="utf-8"))
    host = urlparse(project.base_url).hostname
    return {c["name"]: c["value"] for c in state.get("cookies", []) if (c.get("domain") or "").lstrip(".") in (host, "")}


def _http(project, spec: dict) -> str:
    method = str(spec.get("method", "GET")).upper()
    url = project.url(str(spec["url"]))
    headers = {k: os.environ.get(v[4:], "") if isinstance(v, str) and v.startswith("env:") else v
               for k, v in (spec.get("headers") or {}).items()}
    r = httpx.request(method, url, headers=headers, json=spec.get("json"), data=spec.get("form"),
                      cookies=_cookies(project, spec.get("as_role")), timeout=float(spec.get("timeout_s", 30)),
                      follow_redirects=bool(spec.get("follow_redirects", False)))
    want = spec.get("expect_status")
    ok = (r.status_code == int(want)) if want else r.status_code < 400
    if not ok:
        raise RuntimeError(f"{method} {url} answered HTTP {r.status_code}: {r.text[:200]}")
    return f"{method} {spec['url']} -> HTTP {r.status_code}"


def _sql(spec: dict) -> str:
    dsn = os.environ.get(spec.get("dsn_env") or "") or spec.get("dsn")
    if not dsn:
        raise RuntimeError(f"Set the {spec.get('dsn_env') or 'dsn_env'} environment variable to the database address")
    statements = spec.get("statements") or [spec["statement"]]
    u = urlparse(dsn)
    if u.scheme == "sqlite":
        import sqlite3
        path = dsn.split("sqlite:///", 1)[-1]
        with sqlite3.connect(path) as db:
            n = sum(db.execute(st).rowcount for st in statements)
        return f"{len(statements)} SQL statement(s) on {os.path.basename(path)}, {n} row(s) changed"
    if u.scheme.startswith("postgres"):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("pip install psycopg[binary] to run PostgreSQL steps") from exc
        with psycopg.connect(dsn) as db, db.cursor() as cur:
            n = 0
            for st in statements:
                cur.execute(st)
                n += max(cur.rowcount, 0)
        return f"{len(statements)} SQL statement(s), {n} row(s) changed"
    if u.scheme.startswith("mysql"):
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("pip install pymysql to run MySQL steps") from exc
        db = pymysql.connect(host=u.hostname, port=u.port or 3306, user=u.username, password=u.password or "",
                             database=u.path.lstrip("/"), autocommit=True)
        try:
            with db.cursor() as cur:
                n = sum(cur.execute(st) or 0 for st in statements)
        finally:
            db.close()
        return f"{len(statements)} SQL statement(s), {n} row(s) changed"
    raise RuntimeError(f"Unsupported database address '{u.scheme}://' (use sqlite, postgresql or mysql)")


def run_steps(project, which: str, stage: str, agent: str = "executor") -> list[dict]:
    cfg = project.cfg.get("data") or {}
    if stage not in (cfg.get("around") or ["explore", "run", "exploratory"]):
        return []
    steps = cfg.get(which) or []
    out = []
    for i, st in enumerate(steps, 1):
        name = st.get("name") or f"{which} step {i}"
        t = time.time()
        try:
            detail = _http(project, st["http"]) if "http" in st else _sql(st["sql"]) if "sql" in st else None
            if detail is None:
                raise RuntimeError("a data step needs 'http' or 'sql'")
            out.append({"name": name, "ok": True, "detail": detail, "ms": int((time.time() - t) * 1000)})
            log(f"  [data] {which}: {name}: {detail}")
            live.emit(agent, "data", f"Test data {which}: {name} ({detail})", level="ok")
        except Exception as exc:  # noqa: BLE001
            out.append({"name": name, "ok": False, "detail": str(exc)[:300]})
            live.emit(agent, "data", f"Test data {which} failed: {name}: {exc}", level="bad")
            if which == "setup" and not st.get("optional"):
                raise RuntimeError(f"Test data setup '{name}' failed: {exc}") from exc
            warn(f"[data] {which} '{name}' failed: {exc}")
    return out
