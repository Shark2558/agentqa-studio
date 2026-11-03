"""M1.2 slice 5: the AI endpoints under /api/v1 — catalogue, keys (masked, tested, never echoed), local detection,
policy, the project's AI block with its effective table, and the usage meter. Owner-only, envelope, CSRF rule."""
from __future__ import annotations

import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from conftest import free_port

from agentqa.ai import local as L
from agentqa.ai import usage as U
from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.settings import Settings
from agentqa.orchestrator.projects import open_project
from demo import mock_ai

OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}
PLANTED = "sk-planted-SECRET-0123456789abcdef"


@pytest.fixture
def base(monkeypatch):
    port = free_port()
    srv = mock_ai.serve(port)
    mock_ai.CALLS.clear()
    b = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(L, "PROBES", (("ollama", f"{b}/ollama/api/tags"), ("lmstudio", f"{b}/lmstudio/v1/models")))
    yield b
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def client(tmp_path, monkeypatch, base):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    c = TestClient(create_app(settings))
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    return c


@pytest.fixture
def slug(client):
    r = client.post("/api/v1/projects", json={"name": "AI Portal", "url": "https://ai.example", "environment": "UAT"}, headers=CSRF)
    assert r.status_code == 201
    return r.json()["data"]["slug"]


def cloud_key(client, base, key=PLANTED, **over) -> dict:
    body = {"provider": "openai", "label": "OpenAI", "key": key, "base_url": base + "/openai/v1", "model": "gpt-4o-mini", **over}
    r = client.post("/api/v1/ai/keys", json=body, headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ---- catalogue -----------------------------------------------------------------------------------------

def test_the_catalogue_lists_providers_flags_and_tiers(client):
    r = client.get("/api/v1/ai/catalog")
    d = r.json()["data"]
    assert r.status_code == 200 and r.json()["ok"]
    lm = next(p for p in d["providers"] if p["id"] == "lmstudio")
    assert lm["local"] and lm["keyless"] and lm["family"] == "openai" and "prefer" not in lm
    ant = next(p for p in d["providers"] if p["id"] == "anthropic")
    assert ant["tiers"]["strong"] == ["claude-opus-5-5"] and ant["vision"]
    assert d["tiers"] == ["cheap", "balanced", "strong", "vision"]
    assert {a["agent"] for a in d["agents"]} >= {"req_chat", "visual_qa", "documents", "triage"}


# ---- keys -----------------------------------------------------------------------------------------------

def test_keys_are_added_masked_edited_tested_and_deleted(client, base):
    k = cloud_key(client, base)
    assert "key" not in k and k["masked"] == "sk-p…cdef" and k["provider"] == "openai" and k["scope"] == "cloud"
    kid = k["id"]
    r = client.get("/api/v1/ai/keys")
    assert [x["id"] for x in r.json()["data"]] == [kid] and "key" not in r.json()["data"][0]
    r = client.patch(f"/api/v1/ai/keys/{kid}", json={"label": "Renamed", "key": "", "timeout_s": 30, "priority": 2}, headers=CSRF)
    assert r.status_code == 200 and r.json()["data"]["label"] == "Renamed" and r.json()["data"]["timeout_s"] == 30
    r = client.post(f"/api/v1/ai/keys/{kid}/test", headers=CSRF)
    d = r.json()["data"]
    assert r.status_code == 200 and d["ok"] and d["model"] == "gpt-4o-mini" and "gpt-4o" in d["models"] and d["kind"] == "ok"
    assert mock_ai.CALLS[PLANTED] >= 1                                       # the stored key was kept through the PATCH
    r = client.delete(f"/api/v1/ai/keys/{kid}", headers=CSRF)
    assert r.status_code == 200 and client.get("/api/v1/ai/keys").json()["data"] == []
    assert client.delete(f"/api/v1/ai/keys/{kid}", headers=CSRF).status_code == 404


def test_a_keyless_local_provider_needs_no_key_but_a_cloud_one_does(client, base):
    r = client.post("/api/v1/ai/keys", json={"provider": "ollama", "label": "Ollama", "key": "", "base_url": base + "/ollama",
                                             "model": "qwen3:4b"}, headers=CSRF)
    assert r.status_code == 201 and r.json()["data"]["scope"] == "local" and r.json()["data"]["masked"] == "(none)"
    r = client.post("/api/v1/ai/keys", json={"provider": "openai", "label": "x", "key": ""}, headers=CSRF)
    assert r.status_code == 422 and "key" in r.json()["error"]["message"]


@pytest.mark.parametrize("body,word", [
    ({"provider": "nope", "label": "x", "key": "sk-x"}, "provider"),
    ({"provider": "openai", "label": "x", "key": "sk-x", "base_url": "ftp://x.example/v1"}, "address"),
    ({"provider": "openai", "label": "x", "key": "sk-x", "base_url": "http://169.254.169.254/v1"}, "address"),
    ({"provider": "openai", "label": "", "key": "sk-x"}, "label"),
    ({"provider": "openai", "label": "x", "key": "sk-x", "priority": 0}, "priority"),
    ({"provider": "openai", "label": "x", "key": "sk-x", "timeout_s": 5000}, "timeout_s"),
])
def test_bad_keys_are_refused_with_422(client, body, word):
    r = client.post("/api/v1/ai/keys", json=body, headers=CSRF)
    assert r.status_code == 422 and word in r.json()["error"]["message"].lower(), r.text


def test_a_planted_secret_never_appears_in_any_response_body(client, base, slug):
    k = cloud_key(client, base)
    client.put(f"/api/v1/projects/{slug}/ai", json={"mode": "cloud", "consent": {"send_text": True}}, headers=CSRF)
    responses = [client.get("/api/v1/ai/catalog"), client.get("/api/v1/ai/keys"), client.get("/api/v1/ai/local"),
                 client.get("/api/v1/ai/policy"), client.post(f"/api/v1/ai/keys/{k['id']}/test", headers=CSRF),
                 client.patch(f"/api/v1/ai/keys/{k['id']}", json={"model": "retired-model"}, headers=CSRF),
                 client.post(f"/api/v1/ai/keys/{k['id']}/test", headers=CSRF),          # fails: the detail is scrubbed
                 client.get(f"/api/v1/projects/{slug}/ai"), client.get(f"/api/v1/projects/{slug}/ai/usage"),
                 client.get("/api/v1/ai/keys")]
    for r in responses:
        assert PLANTED not in r.text and "SECRET" not in r.text, r.request.url
    assert responses[6].json()["data"]["ok"] is False


def test_unknown_key_is_404_and_signed_out_is_401(client, tmp_path):
    assert client.post("/api/v1/ai/keys/nope/test", headers=CSRF).status_code == 404
    assert client.patch("/api/v1/ai/keys/nope", json={"label": "x"}, headers=CSRF).status_code == 404
    anonymous = TestClient(client.app)
    assert anonymous.get("/api/v1/ai/keys").status_code == 401
    assert anonymous.get("/api/v1/ai/catalog").status_code == 401
    assert client.post("/api/v1/ai/keys", json={"provider": "openai", "label": "x", "key": "sk-x"}).status_code == 403   # no CSRF header


# ---- local detection -----------------------------------------------------------------------------------

def test_local_detection_reports_both_servers_and_takes_no_address(client, base):
    r = client.get("/api/v1/ai/local?url=http://10.0.0.5:11434")
    d = {row["provider"]: row for row in r.json()["data"]}
    assert r.status_code == 200 and d["ollama"]["running"] and d["ollama"]["models"] == ["qwen3:4b"]
    assert d["ollama"]["base_url"] == base + "/ollama" and d["lmstudio"]["running"]


# ---- policy ---------------------------------------------------------------------------------------------

def test_policy_is_read_and_written(client):
    pol = client.get("/api/v1/ai/policy").json()["data"]
    assert pol["order"][0] == "gemini" and pol["redact"] is True and pol["prices"] == {} and "send_screenshots" not in pol
    r = client.put("/api/v1/ai/policy", json={"order": ["anthropic", "gemini"], "timeout_s": 30,
                                               "prices": {"openai": {"gpt-4o-mini": [1, 2]}}}, headers=CSRF)
    d = r.json()["data"]
    assert r.status_code == 200 and d["order"][:2] == ["anthropic", "gemini"] and "openai" in d["order"]
    assert d["timeout_s"] == 30 and d["prices"] == {"openai": {"gpt-4o-mini": [1.0, 2.0]}} and d["redact"] is True
    assert client.put("/api/v1/ai/policy", json={"order": ["nope"]}, headers=CSRF).status_code == 422
    assert client.put("/api/v1/ai/policy", json={"attempts_per_key": 99}, headers=CSRF).status_code == 422
    assert client.put("/api/v1/ai/policy", json={"prices": {"openai": {"gpt-4o-mini": [1]}}}, headers=CSRF).status_code == 422


# ---- the project's AI block -----------------------------------------------------------------------------

def test_project_ai_block_defaults_then_saved_with_the_effective_table(client, base, slug):
    r = client.get(f"/api/v1/projects/{slug}/ai")
    d = r.json()["data"]
    assert r.status_code == 200 and d["settings"]["mode"] == "none" and d["notice"] is None
    assert len(d["effective"]) == 10 and all(row["reason"] for row in d["effective"]) and d["budget"]["state"] == "ok"
    cloud_key(client, base)
    r = client.put(f"/api/v1/projects/{slug}/ai", json={"mode": "cloud", "consent": {"send_text": True},
                                                        "budget": {"monthly_usd": 5}, "assignments": {"triage": "off"}}, headers=CSRF)
    d = r.json()["data"]
    assert r.status_code == 200 and d["settings"]["mode"] == "cloud" and d["settings"]["budget"]["monthly_usd"] == 5
    assert d["settings"]["budget"]["alert_at_pct"] == 80 and d["settings"]["max_chunks"] == 40
    eff = {row["agent"]: row for row in d["effective"]}
    assert eff["req_writer"]["provider"] == "openai" and eff["req_writer"]["model"] == "gpt-4o-mini" and eff["req_writer"]["tier"] == "strong"
    assert eff["triage"]["reason"] and eff["documents"]["reason"] and "image" in eff["documents"]["reason"]
    p, _ = open_project(slug)
    raw = yaml.safe_load(p.config_path.read_text(encoding="utf-8"))
    assert raw["ai"]["mode"] == "cloud" and raw["ai"]["assignments"] == {"triage": "off"} and "llm" not in raw


@pytest.mark.parametrize("body,word", [
    ({"mode": "turbo"}, "mode"),
    ({"mode": "local", "assignments": {"triage": "huge"}}, "triage"),
    ({"mode": "local", "assignments": {"nobody": "cheap"}}, "nobody"),
    ({"mode": "local", "budget": {"monthly_usd": 0}}, "monthly_usd"),
    ({"mode": "local", "budget": {"alert_at_pct": 101}}, "alert_at_pct"),
    ({"mode": "local", "max_chunks": 0}, "max_chunks"),
])
def test_a_bad_ai_block_is_refused_with_422(client, slug, body, word):
    r = client.put(f"/api/v1/projects/{slug}/ai", json=body, headers=CSRF)
    assert r.status_code == 422 and word in r.json()["error"]["message"], r.text


def test_unknown_project_is_404(client):
    assert client.get("/api/v1/projects/nope/ai").status_code == 404
    assert client.get("/api/v1/projects/nope/ai/usage").status_code == 404


# ---- usage -----------------------------------------------------------------------------------------------

def test_usage_meter_per_agent_per_run_and_the_cap_state(client, slug):
    p, s = open_project(slug)
    client.put(f"/api/v1/projects/{slug}/ai", json={"mode": "cloud", "consent": {"send_text": True},
                                                    "budget": {"monthly_usd": 1}}, headers=CSRF)
    U.record(s, {"provider": "anthropic", "model": "claude-sonnet-5-5", "scope": "cloud", "tier": "strong", "input_tokens": 100_000,
                 "output_tokens": 50_000, "ms": 900}, agent="req_writer", pipeline="P-1")
    r = client.get(f"/api/v1/projects/{slug}/ai/usage")
    d = r.json()["data"]
    assert r.status_code == 200 and d["month"] == U.month_key() and d["total_usd"] == pytest.approx(0.7) and d["calls"] == 1
    assert d["agents"][0]["agent"] == "req_writer" and d["runs"][0]["pipeline"] == "P-1" and d["prices_dated"] == U.PRICES_DATED
    assert d["budget"]["state"] == "ok" and d["budget"]["pct"] == 70
    assert client.get(f"/api/v1/projects/{slug}/ai/usage?month=2026-01").json()["data"]["total_usd"] == 0
    assert client.get(f"/api/v1/projects/{slug}/ai/usage?month=2026-13").status_code == 422
    assert client.get(f"/api/v1/projects/{slug}/ai/usage?month=garbage").status_code == 422


# ---- review fixes (fresh-context reviews, 3 Nov 2026) ------------------------------------------------------

def test_a_patch_with_nulls_keeps_the_stored_values_and_routing_still_works(client, base):
    k = cloud_key(client, base)
    r = client.patch(f"/api/v1/ai/keys/{k['id']}", json={"priority": None, "status": None, "label": None, "timeout_s": None},
                     headers=CSRF)
    d = r.json()["data"]
    assert r.status_code == 200 and d["priority"] == 10 and d["status"] == "active" and d["label"] == "OpenAI"
    assert client.post(f"/api/v1/ai/keys/{k['id']}/test", headers=CSRF).json()["data"]["ok"]      # ordered() still sorts


def test_a_patch_to_a_link_local_address_is_refused(client, base):
    k = cloud_key(client, base)
    r = client.patch(f"/api/v1/ai/keys/{k['id']}", json={"base_url": "http://169.254.169.254/v1"}, headers=CSRF)
    assert r.status_code == 422 and "address" in r.json()["error"]["message"].lower()
    assert client.get("/api/v1/ai/keys").json()["data"][0]["base_url"] == base + "/openai/v1"


@pytest.mark.parametrize("provider", ["azure_openai", "openai_compatible"])
def test_providers_without_a_fixed_address_need_a_base_url(client, provider):
    r = client.post("/api/v1/ai/keys", json={"provider": provider, "label": "x", "key": "sk-x"}, headers=CSRF)
    assert r.status_code == 422 and "base_url" in r.json()["error"]["message"]


@pytest.mark.parametrize("raw", ['{"prices": {"gemini": {"x": [NaN, 1]}}}', '{"prices": {"gemini": {"x": [1, Infinity]}}}',
                                 '{"cooldown_s": {"timeout": NaN}}'])
def test_nan_and_infinity_never_enter_the_policy(client, raw):
    r = client.put("/api/v1/ai/policy", content=raw, headers={**CSRF, "Content-Type": "application/json"})
    assert r.status_code == 422
    pol = client.get("/api/v1/ai/policy").json()["data"]
    assert pol["prices"] == {} and pol["cooldown_s"]["timeout"] == 60


def test_the_old_dashboards_key_form_uses_the_same_address_guard(tmp_path, monkeypatch, base):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    c = TestClient(create_app(settings, legacy=True), follow_redirects=False)
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    r = c.post("/p/demo/ai/key", data={"provider": "openai", "label": "x", "key": "sk-x", "base_url": "http://169.254.169.254/v1"})
    assert r.status_code == 400 and c.get("/api/v1/ai/keys").json()["data"] == []
    r = c.post("/p/demo/ai/key", data={"provider": "openai", "label": "ok", "key": "sk-ok", "base_url": base + "/openai/v1"})
    assert r.status_code == 303 and len(c.get("/api/v1/ai/keys").json()["data"]) == 1


def test_the_old_dashboard_toggle_remembers_the_last_mode_and_the_api_keeps_it(tmp_path, monkeypatch, base):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    c = TestClient(create_app(settings, legacy=True), follow_redirects=False)
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    slug = c.post("/api/v1/projects", json={"name": "Toggle", "url": "https://t.example"}, headers=CSRF).json()["data"]["slug"]
    c.put(f"/api/v1/projects/{slug}/ai", json={"mode": "hybrid", "consent": {"send_text": True}}, headers=CSRF)
    assert c.post(f"/p/{slug}/ai/project", data={}).status_code == 303                       # off
    p, _ = open_project(slug)
    raw = yaml.safe_load(p.config_path.read_text(encoding="utf-8"))["ai"]
    assert raw["mode"] == "none" and raw["last_mode"] == "hybrid"
    c.put(f"/api/v1/projects/{slug}/ai", json={"mode": "none"}, headers=CSRF)                 # the API keeps the memory
    assert yaml.safe_load(open_project(slug)[0].config_path.read_text(encoding="utf-8"))["ai"]["last_mode"] == "hybrid"
    c.post(f"/p/{slug}/ai/project", data={"enabled": "1"})                                   # on again: back to hybrid
    assert yaml.safe_load(open_project(slug)[0].config_path.read_text(encoding="utf-8"))["ai"]["mode"] == "hybrid"
    assert "last_mode" not in c.get(f"/api/v1/projects/{slug}/ai").json()["data"]["settings"]
