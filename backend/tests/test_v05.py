"""v0.5: test data vault, tester-style login, ask-the-tester, Gemini client, Functional Test Analyst, Excel export."""
from __future__ import annotations

import io
import json
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.fernet import Fernet

from conftest import ROOT, free_port

from agentqa.config import Project
from agentqa.store import Store


@pytest.fixture(autouse=True)
def vault_key(monkeypatch):
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())


@pytest.fixture
def v05(tmp_path):
    """The v0.5 demo project with the app map, journeys and login steps a real run produced."""
    root = tmp_path / "demo"
    (root / "srs").mkdir(parents=True)
    shutil.copy(ROOT / "demo" / "project.yaml", root / "project.yaml")
    p = Project(root)
    s = Store(p.db_path)
    data = json.loads((ROOT / "tests" / "fixtures" / "demo_v05.json").read_text(encoding="utf-8").replace("{base}", p.base_url))
    for row in data["screens"]:
        s.insert("screens", row)
    for row in data["journeys"]:
        s.insert("journeys", row)
    for row in data["requirements"]:
        s.insert("requirements", row)
    for role, steps in data["login_steps"].items():
        p.vault.set_login_steps(role, steps)
    for role, screens in data["login_screens"].items():
        p.vault.set_login_screens(role, screens)
    return p, s


# ---- vault -----------------------------------------------------------------------------------

def test_vault_keeps_secrets_encrypted_and_keeps_them_when_the_box_is_left_empty(tmp_path):
    from agentqa.vault import Vault
    v = Vault(tmp_path)
    v.set_account("clerk", {"username": "clerk1", "password": "S3cret!pw", "otp_fixed": "424242", "method": "password"})
    raw = (tmp_path / "vault.json").read_text(encoding="utf-8")
    assert "S3cret" not in raw and "clerk1" not in raw and "424242" not in raw
    v2 = Vault(tmp_path)
    assert v2.account("clerk")["password"] == "S3cret!pw"
    v2.set_account("clerk", {"password": "", "otp_fixed": "", "notes": "front office"})   # empty boxes keep the secrets
    a = Vault(tmp_path).account("clerk")
    assert a["password"] == "S3cret!pw" and a["otp_fixed"] == "424242" and a["notes"] == "front office"
    summary = Vault(tmp_path).summary()["clerk"]
    assert "password" not in summary and "otp_fixed" not in summary and summary["has_password"] and summary["has_fixed_otp"]
    v2.set_login_steps("clerk", [{"goto": "/"}])
    v2.set_login_screens("clerk", {"otp": {"clicks": ["Resend OTP"]}})
    v2.remove_account("clerk")
    v3 = Vault(tmp_path)
    assert not v3.account("clerk") and not v3.login_steps("clerk") and not v3.login_screens("clerk")


def test_project_account_overlays_the_vault_on_project_yaml(v05):
    p, _ = v05
    p.vault.set_account("citizen", {"mobile": "9123456780", "otp_source": "ask"})
    acc = Project(p.root).account("citizen")
    assert acc["mobile"] == "9123456780" and acc["otp_source"] == "ask" and acc["login_option"] == "Citizen Login"


# ---- login: reading the screen like a tester -------------------------------------------------

@pytest.mark.parametrize("inp, kind", [
    ({"type": "password", "name": "pwd"}, "password"),
    ({"type": "text", "maxlength": 1, "label": "OTP digit 1"}, "otpbox"),
    ({"type": "tel", "name": "mobile_no", "label": "Mobile Number"}, "mobile"),
    ({"type": "text", "name": "otp", "label": "One-time password"}, "otp"),
    ({"type": "text", "name": "captcha_text", "label": "Enter the text shown"}, "captcha"),
    ({"type": "text", "name": "loginId", "label": "User ID"}, "username"),
    ({"type": "email", "name": "mail"}, "email"),
    ({"type": "text", "name": "q", "label": "Search services"}, "other"),
])
def test_login_flow_classifies_boxes_like_a_tester(inp, kind):
    from agentqa.login_flow import _kind
    assert _kind(inp) == kind


def test_login_flow_picks_the_configured_login_option():
    from agentqa.login_flow import _choice
    snap = {"clicks": [{"text": t, "submit": False, "inForm": False} for t in
                       ("Home", "Help", "Citizen Login", "Department Login", "Cancel")]}
    assert _choice(snap, {"login_option": "Department Login"}, "clerk", ["Clerk"], set())["text"] == "Department Login"
    assert _choice(snap, {}, "citizen", ["Citizen", "Applicant"], set())["text"] == "Citizen Login"


# ---- ask the tester --------------------------------------------------------------------------

def test_assist_waits_for_an_answer_from_the_dashboard(tmp_path):
    from agentqa import assist
    proj = type("P", (), {"cfg": {"assist": {"timeout_s": 10, "terminal": False}}, "db_path": tmp_path / "a.db",
                          "state": tmp_path})()
    out = {}
    t = threading.Thread(target=lambda: out.update(ans=assist.ask(proj, "otp", "Enter the OTP for citizen", role="citizen")))
    t.start()
    store = Store(tmp_path / "a.db")
    for _ in range(150):                    # up to 15 s: a loaded CI machine is slow to start the thread
        rows = assist.pending(store)
        if rows:
            break
        time.sleep(0.1)
    assert rows and rows[0]["kind"] == "otp"
    assert assist.answer(store, rows[0]["id"], {"text": "482913"})
    assert not assist.answer(store, rows[0]["id"], {"text": "again"})       # answered once only
    t.join(15)
    assert out["ans"]["text"] == "482913" and out["ans"]["via"] == "dashboard"


# ---- Gemini (against a local stand-in for the Google API) ------------------------------------

def test_gemini_client_picks_flash_masks_personal_data_and_parses_json():
    from agentqa.llm import GeminiLLM
    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen["key"] = self.headers.get("x-goog-api-key")
            body = {"models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]} for n in
                               ("gemini-2.0-flash-lite", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-preview-tts",
                                "text-embedding-004")]}
            self._send(body)

        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send({"candidates": [{"content": {"parts": [{"text": '```json\n{"cases": [{"title": "x"}]}\n```'}]}}]})

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    port = free_port()
    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        g = GeminiLLM({"enabled": True, "gemini_url": f"http://127.0.0.1:{port}/v1beta", "gemini_model": "auto"}, "test-key")
        assert g.available() and g.model == "gemini-2.5-flash"
        out = g.chat_json("You test portals.", "Citizen 9123456780 with qa@example.com and Aadhaar 1234 5678 9012")
        assert out == {"cases": [{"title": "x"}]}
        sent = json.dumps(seen["body"])
        assert "9123456780" not in sent and "qa@example.com" not in sent and "1234 5678 9012" not in sent
        assert seen["key"] == "test-key" and seen["path"].endswith("gemini-2.5-flash:generateContent")
    finally:
        srv.shutdown()


# ---- Functional Test Analyst -----------------------------------------------------------------

def test_analyst_drafts_login_navigation_form_and_search_cases_like_a_tester(v05):
    from agentqa.agents import analyst
    p, s = v05
    cases = analyst.draft(p, s, [])
    keys = {c["key"] for c in cases}
    titles = " | ".join(c["title"] for c in cases)
    for k in ("func:login:citizen:valid", "func:login:citizen:otp:wrong", "func:login:citizen:otp:resend",
              "func:login:clerk:wrong-password", "func:login:clerk:password-masked", "func:login:officer:otp:wrong",
              "func:logout:clerk", "func:login:officer:valid"):
        assert k in keys, k
    assert any(k.startswith("func:login:citizen:mobile:9_digits") for k in keys)
    assert "'Login' shows a pop-up with Citizen Login, Department Login" in titles
    assert "'Services ▾ > My Applications' opens My Applications" in titles
    assert "Search shows special characters as plain text" in titles
    by_key = {c["key"]: c for c in cases}
    resend = by_key["func:login:citizen:otp:resend"]
    assert "FR-19" in resend["req_ids"] and resend["params"]["fresh_login"] and resend["params"]["page_role"] == "anonymous"
    assert "FR-18" in next(c for c in cases if c["key"].startswith("func:login:citizen:mobile:9_digits"))["req_ids"]
    # test data stays in the vault: steps carry tokens, never the password or the mobile number itself
    blob = json.dumps(cases)
    assert "Clerk@123" not in blob and "9847012345" not in blob and "{password:wrong}" in blob
    # every case reads like a manual test case
    for c in cases:
        prm = c["params"]
        assert prm["steps_text"] and prm["expected"] and prm["module"] and c["priority"] in ("P1", "P2", "P3")


def test_analyst_skips_cases_the_srs_rules_already_cover(v05):
    from agentqa.agents import analyst
    p, s = v05
    existing = [{"key": "form_valid:/apply:0:citizen"}, {"key": "field_reject:/apply:applicant_name:required"}]
    keys = {c["key"] for c in analyst.draft(p, s, existing)}
    assert "func:form:/apply:0:valid" not in keys and "func:form:/apply:applicant_name:blank" not in keys
    assert "func:form:/apply:pincode:blank" in keys


def test_casegen_keeps_unknown_steps_as_intent_and_traces_every_case(v05, monkeypatch):
    """The Test Case Generation agent: steps on the app map stay recorded steps, others become intent steps."""
    from agentqa.agents import casegen, requirements
    p, s = v05
    p.cfg["llm"]["enabled"] = True
    requirements.standardise(p, s, use_llm=False)
    want = s.one("SELECT id FROM requirements ORDER BY seq")["id"]

    class Fake:
        def available(self):
            return True

        def chat_json(self, system, user, max_tokens=0):
            assert "[[AQ-TASK:casegen]]" in system and "PAYLOAD:" in user
            return {"cases": [
                {"req_id": want, "title": "Download the approved certificate", "role": "citizen", "test_type": "Positive",
                 "priority": "High", "steps": [{"action": "goto", "path": "/my-applications"},
                                               {"action": "click", "target": "Download PDF"}],     # no such button
                 "expected": "A PDF downloads"},
                {"req_id": "NOT-ASKED", "title": "made up", "steps": [{"action": "intent", "text": "x"}], "expected": "y"}]}
    monkeypatch.setattr("agentqa.llm.get_llm", lambda project, task="": Fake())
    cases = casegen.generate(p, s, [])
    model = [c for c in cases if c["params"]["generated_by"] == "model"]
    assert len(model) == 1 and model[0]["req_ids"] == [want]                  # the case for an unasked ID is dropped
    acts = [x["action"] for x in model[0]["params"]["steps"]]
    assert acts == ["goto", "intent", "verify"]                                # unknown button kept as intent, check added
    assert model[0]["priority"] == "P1" and model[0]["params"]["test_type"] == "Positive"
    rest = [c for c in cases if c["params"]["generated_by"] == "rules"]
    assert all(c["params"]["steps"][-1]["action"] == "verify" and c["req_ids"] for c in rest)
    skipped = s.get_meta("casegen_skipped") or []
    covered = {r for c in cases for r in c["req_ids"]} | {x["req_id"] for x in skipped}
    assert covered == {r["id"] for r in s.all("SELECT id FROM requirements")}  # every requirement: a case or a reason


def test_contracts_reject_unchecked_passes_and_untraced_defects():
    from agentqa import contracts as C
    assert C._errors(C.Result, {"case_id": "TC-0001", "status": "Passed", "evidence": []})
    assert not C._errors(C.Result, {"case_id": "TC-0001", "status": "Blocked", "evidence": []})
    assert C._errors(C.Defect, {"id": "DEF-1", "url": "http://x/a", "created_at": "2026-10-30T10:00", "title": "abc",
                                "actual": "broken"})
    assert C.status_name("not-run", "NOT RUN: needs a model") == "Not Run"
    assert C.status_name("test-issue", "LocatorMissing") == "Blocked" and C.status_name("pass") == "Passed"
    case = {"id": "TC-0002", "type": "access_denied", "title": "Clerk cannot open /admin", "priority": "P1",
            "role": "clerk", "req_ids": ["FR-08"], "params": {}}
    view = C.case_view(case)
    assert view["test_type"] == "Access control (RBAC)" and view["priority"] == "Critical" and not C._errors(C.TestCase, view)


# ---- runtime values and the Excel workbook ---------------------------------------------------

def test_runtime_turns_account_values_into_wrong_values(tmp_path):
    for f in ("agentqa_runtime.py",):
        shutil.copy(ROOT / "agentqa" / "runtime" / f, tmp_path / f)
    shutil.copy(ROOT / "agentqa" / "live.py", tmp_path / "agentqa_live.py")
    (tmp_path / "agentqa_settings.json").write_text(json.dumps({"base_url": "http://x", "login_url": "/login",
                                                                "oracles": {}}), encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        import agentqa_runtime as rt
        assert rt._transform("9847012345", "drop_last") == "984701234"
        assert rt._transform("9847012345", "letters") == "98470abcde"
        assert rt._transform("9847012345", "bad_start") == "5847012345"
        assert rt._transform("9847012345", "last4") == "2345"
        assert rt._transform("Clerk@123", "swapcase") == "cLERK@123"
        assert rt._transform("Clerk@123", "wrong") != "Clerk@123"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("agentqa_runtime", None)
        sys.modules.pop("agentqa_live", None)


def test_excel_workbook_has_one_row_per_case_with_the_actual_result(v05):
    from openpyxl import load_workbook
    from agentqa import case_export
    from agentqa.agents import designer
    p, s = v05
    designer.design(p, s)
    case = s.one("SELECT * FROM cases WHERE key LIKE 'func:login:citizen:mobile:9_digits%'")
    s.insert("runs", {"id": "run-1", "started_at": "2999-01-01T00:00:00", "status": "done"})
    s.insert("results", {"run_id": "run-1", "case_id": case["id"], "outcome": "failed", "category": "defect",
                         "message": "AssertionError: DEFECT: step 6 ('Check the OTP screen does not open'): moved on to the OTP screen"})
    wb = load_workbook(io.BytesIO(case_export.workbook(p, s)))
    ws = wb["Test cases"]
    head = [c.value for c in ws[4]]
    # v0.8: the team's standard template first, in its order, then the extra columns that make it comprehensive
    assert head[:11] == ["Test Case Id", "User Access", "Module", "Test Case Name", "Test Case Description",
                         "Pre-Condition", "Actions", "Test Data", "Expected Result", "Test Result", "Remarks"]
    assert head[11:] == ["Requirement ID", "Scenario", "Test Type", "Priority", "Defect ID", "Evidence"]
    row = dict(zip(head, next(r for r in ws.iter_rows(min_row=5, values_only=True) if r[0] == case["id"])))
    assert row["Module"] == "Login" and row["Test Result"] == "Failed" and "moved on to the OTP" in row["Remarks"]
    assert row["Test Type"] == "Authentication" and row["Priority"] in ("Critical", "High", "Medium", "Low")
    assert row["User Access"] == case["role"]
    assert "1. Open /" in row["Actions"]
    assert wb["Summary"]["A1"].value == "Module"
    # every prepared case is in the workbook, not only the functional ones
    assert ws.max_row - 4 == s.scalar("SELECT COUNT(*) FROM cases")
