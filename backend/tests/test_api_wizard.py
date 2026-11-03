"""The onboarding wizard's endpoints: documents, typed requirements, accounts, preflight, requirements list."""
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.settings import Settings
from agentqa.orchestrator import intake
from agentqa.orchestrator.projects import ROOT
from agentqa.orchestrator.projects import open_project

OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}
DEMO_DOCX = ROOT / "demo" / "srs" / "Demo_Certificate_Portal_SRS.docx"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    c = TestClient(create_app(settings))
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    return c


@pytest.fixture
def slug(client):
    r = client.post("/api/v1/projects", json={"name": "UR Portal", "url": "https://ur.example", "environment": "UAT"}, headers=CSRF)
    assert r.status_code == 201
    return r.json()["data"]["slug"]


class Portal(BaseHTTPRequestHandler):
    PAGES = {"/": "<html><a href='/account/login'>Log in</a><p>Welcome</p></html>",
             "/account/login": "<form><input name=u><input type='password' name=p><button>Sign in</button></form>",
             "/app": "<html><button type=button id=login-open>Login</button>"
                     "<button type=button data-go='http://127.0.0.1:1/citizen/login'>Citizen Login</button></html>",
             "/plain": "<html><button type=button id=login-open>Login</button></html>"}

    def do_GET(self):
        body = self.PAGES.get(self.path, "nope").encode()
        self.send_response(200 if self.path in self.PAGES else 404)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def portal():
    srv = HTTPServer(("127.0.0.1", 0), Portal)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


# ---- step 1 -----------------------------------------------------------------------------------------

def test_create_records_the_environment(client, slug):
    _, _ = open_project(slug)
    r = client.get(f"/api/v1/projects/{slug}")
    assert r.json()["data"]["environment"] == "UAT"


def test_preflight_reports_reachability_and_a_login_page(client, portal):
    r = client.post("/api/v1/preflight", json={"url": portal}, headers=CSRF)
    d = r.json()["data"]
    assert r.status_code == 200 and d["reachable"] is True and d["status"] == 200
    assert d["login_detected"] is True and d["login_url"] == "/account/login"
    assert "fix" not in d or d["fix"] is None
    # portals built as apps use buttons, not links (the demo Citizen Portal does)
    d = client.post("/api/v1/preflight", json={"url": portal + "/app"}, headers=CSRF).json()["data"]
    assert d["login_detected"] is True and d["login_url"] == "/citizen/login"
    d = client.post("/api/v1/preflight", json={"url": portal + "/plain"}, headers=CSRF).json()["data"]
    assert d["login_detected"] is True and d["login_url"] is None


def test_preflight_explains_a_refused_connection_in_plain_english(client):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    r = client.post("/api/v1/preflight", json={"url": f"http://127.0.0.1:{port}"}, headers=CSRF)
    d = r.json()["data"]
    assert r.status_code == 200 and d["reachable"] is False and "refused" in d["fix"].lower()


def test_preflight_only_accepts_web_addresses(client):
    r = client.post("/api/v1/preflight", json={"url": "file:///etc/passwd"}, headers=CSRF)
    assert r.status_code == 422


# ---- step 2 -----------------------------------------------------------------------------------------

def test_documents_upload_probe_list_and_delete(client, slug):
    files = [("files", ("Demo_Certificate_Portal_SRS.docx", DEMO_DOCX.read_bytes(), "application/octet-stream")),
             ("files", ("../notes.txt", b"The system shall log every change.", "text/plain"))]
    r = client.post(f"/api/v1/projects/{slug}/documents", files=files, headers=CSRF)
    assert r.status_code == 201
    by_name = {d["name"]: d for d in r.json()["data"]}
    assert by_name["Demo_Certificate_Portal_SRS.docx"]["status"] == "read" and by_name["notes.txt"]["status"] == "read"

    listed = client.get(f"/api/v1/projects/{slug}/documents").json()["data"]
    assert {d["name"] for d in listed} == {"Demo_Certificate_Portal_SRS.docx", "notes.txt"}

    assert client.delete(f"/api/v1/projects/{slug}/documents/notes.txt", headers=CSRF).status_code == 200
    assert {d["name"] for d in client.get(f"/api/v1/projects/{slug}/documents").json()["data"]} == {"Demo_Certificate_Portal_SRS.docx"}
    assert client.delete(f"/api/v1/projects/{slug}/documents/..%2Fproject.yaml", headers=CSRF).status_code == 404


def test_unsupported_and_oversized_documents_are_refused(client, slug, monkeypatch):
    r = client.post(f"/api/v1/projects/{slug}/documents", files=[("files", ("run.exe", b"MZ", "application/octet-stream"))], headers=CSRF)
    assert r.status_code == 422 and "run.exe" in r.json()["error"]["message"]
    monkeypatch.setattr("agentqa.orchestrator.intake.MAX_UPLOAD", 10)
    r = client.post(f"/api/v1/projects/{slug}/documents", files=[("files", ("big.txt", b"x" * 11, "text/plain"))], headers=CSRF)
    assert r.status_code == 413


def test_typed_requirements_return_the_chat_and_are_stored_as_a_document(client, slug):
    r = client.post(f"/api/v1/projects/{slug}/requirements/typed",
                    json={"text": "- Reports can be exported.\n- Export must finish quickly."}, headers=CSRF)
    d = r.json()["data"]
    assert r.status_code == 200 and d["source"] == "rules" and len(d["items"]) == 2 and 1 <= len(d["questions"]) <= 5
    r = client.post(f"/api/v1/projects/{slug}/requirements/typed",
                    json={"text": "- Reports can be exported.\n- Export must finish quickly.",
                          "answers": [{"question": d["questions"][0]["question"], "answer": "Clerks and admins."}]}, headers=CSRF)
    assert r.status_code == 200
    p, _ = open_project(slug)
    text = (p.srs_dir / intake.TYPED_NAME).read_text(encoding="utf-8")
    assert "Clerks and admins." in text
    assert any(d["name"] == intake.TYPED_NAME for d in client.get(f"/api/v1/projects/{slug}/documents").json()["data"])


def test_a_manual_sheet_is_imported_into_the_imports_folder(client, slug):
    r = client.post(f"/api/v1/projects/{slug}/imports", files=[("files", ("manual.csv", b"ID,Title\nTC-1,Login\n", "text/csv"))], headers=CSRF)
    assert r.status_code == 201 and r.json()["data"][0]["folder"] == "imports"


# ---- step 3 -----------------------------------------------------------------------------------------

def test_accounts_round_trip_without_echoing_secrets(client, slug):
    body = {"no_login": False, "roles": [
        {"role": "clerk", "login_option": "Department Login", "method": "password", "username": "clerk1", "password": "Clerk@123"},
        {"role": "citizen", "login_option": "Citizen Login", "method": "mobile_otp", "mobile": "9847012345", "otp_source": "ask"}]}
    r = client.put(f"/api/v1/projects/{slug}/accounts", json=body, headers=CSRF)
    assert r.status_code == 200 and "Clerk@123" not in r.text
    view = client.get(f"/api/v1/projects/{slug}/accounts").json()["data"]
    clerk = next(x for x in view["roles"] if x["role"] == "clerk")
    assert clerk["has_password"] is True and "Clerk@123" not in str(view)
    bad = client.put(f"/api/v1/projects/{slug}/accounts", json={"roles": [{"role": "x", "method": "telepathy"}]}, headers=CSRF)
    assert bad.status_code == 422


# ---- after the run ----------------------------------------------------------------------------------

def test_requirements_list_shows_each_one_with_its_source(client, slug):
    _, s = open_project(slug)
    s.insert("requirements", {"id": "FR-1", "seq": 1, "section": "Apply", "text": "Citizens can apply online.", "kind": "functional",
                              "priority": "M", "roles": ["citizen"], "ambiguity": [], "source_file": "Demo.docx"})
    s.insert("documents", {"name": "Demo.docx", "kind": "docx", "size": 10, "segments": 3, "status": "read", "detail": ""})
    d = client.get(f"/api/v1/projects/{slug}/requirements").json()["data"]
    assert d["requirements"][0]["id"] == "FR-1" and d["requirements"][0]["source_file"] == "Demo.docx"
    assert d["documents"][0]["name"] == "Demo.docx" and d["documents"][0]["status"] == "read"


def test_wizard_routes_need_a_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    c = TestClient(create_app(Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)))
    assert c.get("/api/v1/projects/demo/documents").status_code == 401
    assert c.post("/api/v1/preflight", json={"url": "https://x.example"}, headers=CSRF).status_code == 401
