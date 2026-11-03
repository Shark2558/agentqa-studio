"""Findings of the M1.1 review, each pinned by a test before the fix."""
from __future__ import annotations

import io
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.settings import Settings
from agentqa.config import Project, init_project
from agentqa.orchestrator import intake, preflight
from agentqa.orchestrator.projects import open_project

OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    c = TestClient(create_app(Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)))
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    c.post("/api/v1/projects", json={"name": "P", "url": "https://p.example"}, headers=CSRF)
    return c


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    init_project(tmp_path / "p", "Portal", "https://portal.example")
    return Project(tmp_path / "p")


# ---- HIGH-1: parsers off the event loop, zip bombs refused before parsing ----------------------------

def test_a_docx_whose_members_unpack_far_beyond_the_cap_is_refused(project, monkeypatch):
    monkeypatch.setattr(intake, "MAX_UNPACKED", 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"\0" * (2 * 1024 * 1024))     # 2 MB of zeros, a few KB compressed
    with pytest.raises(intake.TooLarge):
        intake.save_document(project, "bomb.docx", buf.getvalue())
    assert not (project.srs_dir / "bomb.docx").exists()


def test_uploads_are_probed_in_a_worker_thread(client, monkeypatch):
    seen = {}

    def probe(path, folder="srs"):
        seen["thread"] = threading.current_thread().name
        return {"name": path.name, "folder": folder, "size": 1, "kind": "txt", "status": "read", "detail": "", "segments": 1}

    monkeypatch.setattr("agentqa.orchestrator.intake.probe_document", probe)
    r = client.post("/api/v1/projects/p/documents", files=[("files", ("a.txt", b"The system shall work.", "text/plain"))], headers=CSRF)
    assert r.status_code == 201 and seen["thread"] != "MainThread"


# ---- HIGH-2 / LOW-16: every bad address gets a plain-English answer ----------------------------------

def test_an_address_with_a_space_or_a_bad_host_is_refused_with_a_message(client):
    for url in ("http://my site", "http://a..b/", "http://[::1"):
        r = client.post("/api/v1/preflight", json={"url": url}, headers=CSRF)
        assert r.status_code == 422, url
        assert "address" in r.json()["error"]["message"].lower()


def test_an_unclassified_network_error_is_not_called_a_timeout():
    assert preflight.FIXES[preflight._classify(httpx.RemoteProtocolError("peer closed"))] == preflight.FIXES["unreadable"]


# ---- HIGH-3: a total deadline, not only a per-read timeout ----------------------------------------

def test_the_whole_check_stops_at_the_deadline(monkeypatch):
    monkeypatch.setattr(preflight, "DEADLINE_S", 0.3)

    def drip():
        while True:
            time.sleep(0.1)
            yield b"x"

    started = time.monotonic()
    with pytest.raises(httpx.ReadTimeout):
        list(preflight._limited(drip(), started))
    assert time.monotonic() - started < 2


# ---- MEDIUM-8: link-local / metadata addresses are never fetched, even after a redirect -----------------

class Portal(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/meta":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><a href='/login'>Log in</a></html>")

    def log_message(self, *a):
        pass


@pytest.fixture
def portal():
    srv = HTTPServer(("127.0.0.1", 0), Portal)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_metadata_addresses_are_blocked_directly_and_behind_a_redirect(portal):
    direct = preflight.check("http://169.254.169.254/latest/meta-data/")
    assert direct["reachable"] is False and direct["fix"] == preflight.FIXES["blocked"]
    via = preflight.check(portal + "/meta")
    assert via["reachable"] is False and via["fix"] == preflight.FIXES["blocked"]
    ok = preflight.check(portal)                                 # loopback and private LANs stay allowed
    assert ok["reachable"] is True and ok["login_url"] == "/login"


# ---- MEDIUM-4 / MEDIUM-5: the accounts answer is fresh, and recorded logins survive "no login" ------------

def test_put_accounts_answers_with_what_was_just_saved(client):
    r = client.put("/api/v1/projects/p/accounts", json={"no_login": True, "roles": []}, headers=CSRF)
    assert r.status_code == 200 and r.json()["data"] == {"no_login": True, "roles": []}
    r = client.put("/api/v1/projects/p/accounts", json={"roles": [{"role": "clerk", "login_option": "Dept", "method": "password",
                                                                   "username": "c1", "password": "x" * 10}]}, headers=CSRF)
    assert r.json()["data"]["roles"][0]["login_option"] == "Dept" and r.json()["data"]["no_login"] is False


def test_no_login_keeps_accounts_that_have_recorded_login_steps(project):
    project.vault.set_account("officer", {"username": "o1", "password": "Secret!1"})
    project.vault.set_login_steps("officer", [{"kind": "click", "text": "Login"}])
    project.vault.save()
    intake.save_accounts(project, [], no_login=True)
    fresh = Project(project.root)
    assert fresh.vault.account("officer")["username"] == "o1"
    assert yaml.safe_load(project.config_path.read_text(encoding="utf-8"))["roles"] == {}


# ---- MEDIUM-6: one bad file refuses the whole batch before anything is written ---------------------------

def test_a_batch_with_one_bad_file_writes_nothing(client):
    files = [("files", ("good.txt", b"The system shall work.", "text/plain")), ("files", ("bad.exe", b"MZ", "application/octet-stream"))]
    r = client.post("/api/v1/projects/p/documents", files=files, headers=CSRF)
    assert r.status_code == 422
    assert client.get("/api/v1/projects/p/documents").json()["data"] == []


# ---- MEDIUM-7: the list the owner confirmed is what gets written; AI questions fit the answer schema -------

def test_confirmed_items_are_written_instead_of_re_splitting_the_text(project):
    intake.save_typed(project, "- A\n- B", items=["Citizens can apply online.", "Clerks verify within 2 days."])
    text = (project.srs_dir / intake.TYPED_NAME).read_text(encoding="utf-8")
    assert "REQ-001: Citizens can apply online." in text and "REQ-002: Clerks verify within 2 days." in text and "- A" not in text


def test_ai_questions_are_cut_to_the_answer_schema_length(project):
    from agentqa.agents import req_chat

    class Gw:
        def available(self):
            return True

        def complete_json(self, *a, **k):
            return {"requirements": [{"text": "X must Y."}], "questions": ["q" * 900]}

    project.cfg["ai"] = {"mode": "cloud"}
    out = req_chat.chat(project, "X must Y.", gateway=Gw())
    assert len(out["questions"][0]["question"]) <= 500


def test_ai_topic_answers_are_kept_as_question_and_answer(project):
    intake.save_typed(project, "X must Y.", answers=[{"topic": "ai", "question": "Which IDs?", "answer": "Aadhaar and PAN."}])
    assert "REQ-002: Which IDs? Aadhaar and PAN." in (project.srs_dir / intake.TYPED_NAME).read_text(encoding="utf-8")


# ---- MEDIUM-11 / LOW-14: no server paths in a document verdict; sane file names ---------------------------

def test_a_corrupt_docx_verdict_names_no_server_path(project):
    out = intake.save_document(project, "broken.docx", b"not a zip at all")
    assert out["status"] == "unread" and str(project.root) not in out["detail"] and "G:\\" not in out["detail"]


def test_long_and_reserved_file_names_are_refused():
    with pytest.raises(intake.Unsupported):
        intake.safe_name("a" * 200 + ".txt")
    with pytest.raises(intake.Unsupported):
        intake.safe_name("CON.txt")


# ---- LOW-13: the schema already knows the login methods ---------------------------------------------------

def test_an_unknown_method_is_refused_by_the_schema(client):
    r = client.put("/api/v1/projects/p/accounts", json={"roles": [{"role": "x", "method": "telepathy"}]}, headers=CSRF)
    assert r.status_code == 422 and "method" in r.json()["error"]["message"]


# ---- LOW-20: the old dashboard's upload goes through the same checks --------------------------------------

def test_the_old_dashboards_upload_uses_intake(client, tmp_path, monkeypatch):
    from agentqa.web import app as dashboard
    assert dashboard.upload_srs.__module__ == "agentqa.web.app"
    import inspect
    assert "intake.save_document" in inspect.getsource(dashboard.upload_srs)


def test_project_open_helper(client):
    p, _ = open_project("p")
    assert p.name == "P"
