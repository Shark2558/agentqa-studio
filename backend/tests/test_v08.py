"""v0.8: API testing against token-authenticated back ends, multi-portal manual paths, master plan,
Zoho export and the standard test case template.

The API tests here use a real browser against a tiny token-auth server, so the whole path is exercised:
the Explorer learns where the screens keep their bearer token, and the generated runtime rebuilds the same
Authorization header to call the API itself (the v0.7 runtime sent no header, so every secured API answered 401
and the API tests "failed" - the regression this fixes).
"""
from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import ROOT, free_port

TOKEN = "tok-" + "a1b2c3d4e5f6" * 3           # a long value, like a real JWT/session token


class _Handler(BaseHTTPRequestHandler):
    """A single-page app whose screens authenticate API calls with a bearer token kept in localStorage."""

    def log_message(self, *a):  # noqa: D401, ANN002
        pass

    def _send(self, status, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, f"""<!doctype html><html lang="en"><head><title>Token SPA</title></head><body>
<h1>Dashboard</h1><a href="/profile">Profile</a>
<script>
localStorage.setItem('session', JSON.stringify({{auth: {{token: '{TOKEN}'}}, name: 'Asha'}}));
fetch('/api/me', {{headers: {{Authorization: 'Bearer ' + JSON.parse(localStorage.session).auth.token}}}})
  .then(r => r.json()).then(j => {{ document.title = 'me:' + j.role; }});
</script></body></html>""", "text/html")
            return
        if path.startswith("/api/"):
            auth = self.headers.get("Authorization") or ""
            if auth != f"Bearer {TOKEN}":
                self._send(401, json.dumps({"detail": "Not authenticated"}))
                return
            if path == "/api/me":
                self._send(200, json.dumps({"username": "asha", "name": "Asha", "role": "citizen"}))
            else:
                self._send(200, json.dumps({"id": 1, "status": "Submitted", "cert_type": "birth"}))
            return
        self._send(404, "<h1>Page not found</h1>", "text/html")


@pytest.fixture
def token_server():
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


def _project(tmp_path, base_url):
    root = tmp_path / "proj"
    (root / "srs").mkdir(parents=True)
    (root / "project.yaml").write_text(
        f"project: Token SPA\nbase_url: {base_url}\n"
        "roles:\n  citizen: {username: asha}\n", encoding="utf-8")
    from agentqa.config import Project
    from agentqa.store import Store
    p = Project(root)
    return p, Store(p.db_path)


def test_explorer_learns_where_the_api_token_is_kept(tmp_path, token_server):
    """The core of the fix: the Explorer must find that the screens send an Authorization header and that its
    value is 'Bearer ' + a token kept at session.auth.token in local storage."""
    from playwright.sync_api import sync_playwright
    from agentqa.agents import explorer
    p, _ = _project(tmp_path, token_server)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context()
        page = ctx.new_page()
        calls = []
        page.on("response", lambda r: calls.append(r) if r.request.resource_type in ("xhr", "fetch") else None)
        page.goto(token_server + "/", wait_until="load")
        page.wait_for_timeout(500)
        prof = explorer.api_auth_profile(page, p, "citizen", calls, None)
        b.close()
    assert prof and prof["header"].lower() == "authorization"
    assert prof["source"] == "local" and prof["key"] == "session"
    assert prof["path"] == ["auth", "token"] and prof["prefix"] == "Bearer "
    assert TOKEN not in json.dumps(prof)                 # the place, never the value


def test_api_tests_send_the_learnt_header_and_pass(tmp_path, token_server):
    """End to end: with the learnt profile, the generated runtime rebuilds the bearer header from the saved
    session and the secured API answers 200 (a logged-in caller) and 401 (anonymous) - both correct verdicts."""
    from playwright.sync_api import sync_playwright
    p, _ = _project(tmp_path, token_server)
    profile = {"citizen": {"header": "Authorization", "api": "/api/me", "source": "local",
                           "key": "session", "path": ["auth", "token"], "prefix": "Bearer "}}
    # a generated tests folder, as the Script Generator writes it
    tdir = tmp_path / "tests"
    tdir.mkdir()
    for f in ("agentqa_runtime.py", "conftest.py"):
        shutil.copy(ROOT / "agentqa" / "runtime" / f, tdir / f)
    shutil.copy(ROOT / "agentqa" / "live.py", tdir / "agentqa_live.py")
    shutil.copy(ROOT / "agentqa" / "runtime" / "widgets.js", tdir / "agentqa_widgets.js")
    (tdir / "agentqa_settings.json").write_text(json.dumps({
        "base_url": token_server, "login_url": "/login", "oracles": p.cfg["oracles"], "headless": True,
        "timeout_ms": 8000, "apps": {"main": {"base_url": token_server, "login_url": "/login", "name": "Token SPA",
                                              "production": False}},
        "primary_app": "main", "api_auth": profile, "landing": {"citizen": "/"},
        "evidence": "failures", "language": {}}), encoding="utf-8")

    import importlib
    import sys
    sys.path.insert(0, str(tdir))
    for m in ("agentqa_live", "agentqa_runtime"):
        sys.modules.pop(m, None)
    importlib.import_module("agentqa_live")  # the runtime expects the live module to be importable beside it
    rt = importlib.import_module("agentqa_runtime")
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            # a logged-in citizen: the page keeps the token in local storage, as a saved session would
            ctx = b.new_context()
            page = ctx.new_page()
            page._aq_role = "citizen"
            page._aq_case = "TC-TOKEN"
            page.goto(token_server + "/", wait_until="load")
            page.wait_for_timeout(300)
            headers = rt.api_headers(page)
            assert headers.get("Authorization") == f"Bearer {TOKEN}"
            status, _ms, data, _r = rt._api(page, "/api/me")
            assert status == 200 and data and data["role"] == "citizen"    # the v0.7 runtime got 401 here
            # anonymous: no token, the API must refuse
            actx = b.new_context()
            apage = actx.new_page()
            apage._aq_role = "anonymous"
            apage._aq_case = "TC-ANON"
            astatus, _m, _d, aresp = rt._api(apage, "/api/me")
            assert astatus == 401 and rt._refused(astatus, aresp)
            b.close()
    finally:
        sys.path.remove(str(tdir))
        for m in ("agentqa_live", "agentqa_runtime"):
            sys.modules.pop(m, None)


def test_token_source_finds_values_in_storage_and_cookies():
    from agentqa.agents.explorer import _token_source, _find_in
    stores = {"local": {"session": json.dumps({"auth": {"token": "ABCDEF1234567890"}})},
              "session": {"jwt": "Z9Y8X7W6V5U4T3S2"}}
    cookies = [{"name": "sid", "value": "cookieVALUE12345678"}]
    assert _token_source("Bearer ABCDEF1234567890", stores, cookies) == {
        "source": "local", "key": "session", "path": ["auth", "token"], "prefix": "Bearer "}
    assert _token_source("Z9Y8X7W6V5U4T3S2", stores, cookies)["source"] == "session"
    assert _token_source("cookieVALUE12345678", stores, cookies)["source"] == "cookie"
    assert _token_source("nothing-matches-here", stores, cookies) is None
    assert _find_in({"a": [{"b": "LONGTOKENVALUE123"}]}, "LONGTOKENVALUE123")[0] == ["a", 0, "b"]


def test_manual_step_path_resolves_to_the_role_portal(tmp_path):
    """A manual test for a department role that says 'Open URL /officer/queue' must open the department
    portal's queue, not 404 on the primary citizen portal."""
    from agentqa.config import Project
    from agentqa.store import Store
    from agentqa.agents.importer import Context
    root = tmp_path / "multi"
    (root / "srs").mkdir(parents=True)
    (root / "project.yaml").write_text(
        "project: Multi\nbase_url: http://127.0.0.1:8800\n"
        "applications:\n"
        "  citizen: {name: Citizen, base_url: 'http://127.0.0.1:8800'}\n"
        "  department: {name: Department, base_url: 'http://127.0.0.1:8810'}\n"
        "roles:\n"
        "  citizen: {app: citizen, username: c1}\n"
        "  clerk: {app: department, username: k1}\n", encoding="utf-8")
    p = Project(root)
    s = Store(p.db_path)
    for path, role in [("/apply", "citizen"), ("@department/officer/queue", "officer")]:
        s.insert("screens", {"role": role, "path": path, "url": p.url(path), "status": 200, "title": "", "headings": [],
                             "links": [], "forms": [], "buttons": [], "a11y": {}, "console": [], "load_ms": 1,
                             "pattern": path, "server_error": 0, "final_url": p.url(path)})
    ctx = Context(p, s)
    assert ctx.screen("/officer/queue", "clerk") == "@department/officer/queue"   # resolved to the clerk's portal
    assert ctx.screen("/apply", "citizen") == "/apply"                            # a real primary-portal page stays put


def test_zoho_export_has_the_columns_the_zoho_bug_importer_maps(tmp_path):
    """Zoho BugTracker / Projects 'Import Bugs' maps by header: Title, Description, Severity, Classification,
    Reproducible, Module, Status. Severity uses Zoho's own words (Show Stopper / Critical / Major / Minor)."""
    import csv
    from agentqa.agents.triage import export_zoho_csv
    from agentqa.config import Project
    from agentqa.store import Store
    root = tmp_path / "z"
    (root / "srs").mkdir(parents=True)
    (root / "project.yaml").write_text("project: Z\nbase_url: http://127.0.0.1:1\nroles: {citizen: {username: a}}\n", encoding="utf-8")
    p = Project(root)
    s = Store(p.db_path)
    s.insert("defects", {"id": "DEF-001", "seq": 1, "run_id": "r", "case_ids": ["TC-0001"], "signature": "x", "severity": "Critical",
                         "priority": "P1", "role": "citizen", "url": "http://127.0.0.1:1/apply?x=1", "steps": "1. Open /apply",
                         "expected": "Mobile accepts digits only", "actual": "Letters accepted", "evidence": [], "rule_ids": [],
                         "req_ids": ["FR-03"], "status": "confirmed", "created_at": "2026-10-31T00:00:00", "notes": "",
                         "title": "Mobile Number accepts letters"})
    path = export_zoho_csv(p, s)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and set(rows[0]) >= {"Title", "Description", "Severity", "Classification", "Reproducible", "Module", "Status"}
    r = rows[0]
    assert r["Title"] == "Mobile Number accepts letters" and r["Severity"] == "Show Stopper" and r["Module"] == "/apply"
    assert "Steps to reproduce" in r["Description"] and "FR-03" in r["Description"] and r["AgentQA ID"] == "DEF-001"
