"""The /api/v1 sign-in: one owner account from settings, signed HttpOnly cookie, CSRF header, rate limit."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.settings import Settings

OWNER = "owner@example.com"
PASSWORD = "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD),
                       secret_key="test-secret-key-that-is-long-enough-0123456789", login_attempts=3)
    return TestClient(create_app(settings))


def login(client: TestClient, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": OWNER, "password": password}, headers=CSRF)


def test_health_needs_no_sign_in(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["data"]["status"] == "ok"


def test_everything_else_needs_a_sign_in(client):
    r = client.get("/api/v1/projects")
    assert r.status_code == 401
    assert r.json() == {"ok": False, "error": {"code": "unauthenticated", "message": "Sign in first"}}


def test_login_sets_a_secure_session_cookie_and_me_works(client):
    # Act
    r = login(client)

    # Assert
    assert r.status_code == 200 and r.json()["data"]["email"] == OWNER and r.json()["data"]["role"] == "owner"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert client.get("/api/v1/auth/me").json()["data"]["email"] == OWNER


def test_wrong_password_is_refused_without_saying_which_part_was_wrong(client):
    r = login(client, "nope")
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"
    wrong_email = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}, headers=CSRF)
    assert wrong_email.status_code == 401 and wrong_email.json() == r.json()     # the same answer either way


def test_state_changing_calls_need_the_csrf_header(client):
    r = client.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"


def test_login_is_rate_limited(client):
    for _ in range(3):
        login(client, "nope")
    r = login(client)                                   # even the right password is refused once locked
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_logout_ends_the_session(client):
    login(client)
    assert client.post("/api/v1/auth/logout", headers=CSRF).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_a_tampered_cookie_is_not_a_session(client):
    login(client)
    client.cookies.clear()
    client.cookies.set("agentqa_session", "forged.value")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_without_an_owner_configured_login_is_refused_with_a_clear_code(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    c = TestClient(create_app(Settings(owner_email="", owner_password_hash="", secret_key="x" * 40)))
    r = c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    assert r.status_code == 503 and r.json()["error"]["code"] == "owner_not_configured"
