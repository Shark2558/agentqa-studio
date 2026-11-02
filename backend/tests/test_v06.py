"""v0.6: documents in many formats, the source ledger, standardised requirements, execution scopes and resume."""
from __future__ import annotations

import json
import shutil

import pytest

from conftest import ROOT


# ---- Requirement 2: documents and the source ledger -----------------------------------------------

def test_documents_reads_each_supported_format(tmp_path):
    from openpyxl import Workbook
    from agentqa import documents
    (tmp_path / "a.csv").write_text("ID;Requirement\nCSV-1;The portal shall show the fee before payment.\n", encoding="utf-8")
    (tmp_path / "b.html").write_text("<h1>Fees</h1><p>The fee shall be shown in rupees.</p><table><tr><td>x</td></tr></table>",
                                     encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"rules": [{"id": "J-1", "text": "Tokens shall expire after one hour."}]}),
                                     encoding="utf-8")
    (tmp_path / "d.md").write_text("# Login\n\nLG-1: Users shall log in with a password.\n", encoding="utf-8")
    wb = Workbook()
    wb.active.append(["Req ID", "Requirement"])
    wb.active.append(["X-1", "The scheme name shall be unique."])
    wb.save(tmp_path / "e.xlsx")
    (tmp_path / "f.xyz").write_text("?", encoding="utf-8")
    seen = {}
    for f in sorted(tmp_path.iterdir()):
        blocks, info = documents.read(f)
        seen[f.suffix] = (info["status"], " ".join(json.dumps(b) for b in blocks))
    assert seen[".csv"][0] == "read" and "CSV-1" in seen[".csv"][1]
    assert seen[".html"][0] == "read" and "rupees" in seen[".html"][1]
    assert seen[".json"][0] == "read" and "expire after one hour" in seen[".json"][1]
    assert seen[".md"][0] == "read" and "LG-1" in seen[".md"][1]
    assert seen[".xlsx"][0] == "read" and "unique" in seen[".xlsx"][1]
    assert seen[".xyz"][0] == "unread"                       # never silently dropped: reported as not read


def test_scanned_image_is_read_with_ocr_or_reported_unread(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    from agentqa import documents
    img = Image.new("RGB", (1400, 160), "white")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((20, 50), "AN-1: The receipt shall show the payment date.", fill="black", font=font)
    img.save(tmp_path / "scan.png")
    blocks, info = documents.read(tmp_path / "scan.png")
    if documents._tesseract():
        assert info["status"] == "read" and "receipt" in json.dumps(blocks).lower()
    else:
        assert info["status"] == "unread" and info["detail"]


def test_srs_ledger_keeps_requirement_like_text_and_coverage_is_never_overclaimed(demo):
    from agentqa.agents import requirements, srs_analyst
    p, s = demo
    (p.srs_dir / "faq.html").write_text("<h2>Grievances</h2><p>Grievances are answered by the department within 7 days.</p>",
                                        encoding="utf-8")
    srs_analyst.analyze(p, s, use_llm=False)
    docs = {d["name"]: d["status"] for d in s.all("SELECT name, status FROM documents")}
    assert docs["faq.html"] == "read" and all(v == "read" for v in docs.values())
    missed = s.all("SELECT * FROM segments WHERE disposition='possibly missed'")
    assert any("7 days" in m["text"] for m in missed)
    requirements.standardise(p, s, use_llm=False)
    cov = requirements.coverage(p, s)
    assert cov["complete"] is False and cov["possibly_missed"] >= 1
    r = s.one("SELECT * FROM requirements ORDER BY seq")
    st = r["std"]
    assert st["title"] and st["main_flow"] and st["source"] and st["use_case"]["actor"]


def test_disposition_override_is_kept_and_logged(demo):
    from agentqa.agents import requirements, srs_analyst
    p, s = demo
    srs_analyst.analyze(p, s, use_llm=False)
    requirements.standardise(p, s, use_llm=False)
    rid = s.one("SELECT id FROM requirements ORDER BY seq")["id"]
    requirements.set_disposition(s, rid, "out_of_scope", "handled by another vendor")
    requirements.check(p, s)
    assert s.one("SELECT disposition FROM requirements WHERE id=?", [rid])["disposition"] == "out_of_scope"
    log = s.one("SELECT * FROM change_log WHERE object_id=?", [rid])
    assert log and log["justification"] == "handled by another vendor"


# ---- Requirement 7: execution statuses, scopes and resume ----------------------------------------

def test_execution_counts_blocked_and_not_run_apart_from_passed(v06):
    from agentqa import execution
    p, s = v06
    cases = s.all("SELECT id FROM cases WHERE status='approved' ORDER BY seq")[:4]
    s.insert("runs", {"id": "run-x", "started_at": "2999-01-01T00:00:00", "status": "done"})
    for c, (cat, msg) in zip(cases, [("pass", ""), ("defect", "DEFECT: wrong"), ("blocked", "BLOCKED: login failed"),
                                     ("not-run", "NOT RUN: needs an AI model")]):
        s.insert("results", {"run_id": "run-x", "case_id": c["id"], "outcome": "x", "category": cat, "message": msg})
    sm = execution.summary(p, s)
    st = {r["id"]: r["status"] for r in sm["rows"]}
    assert [st[c["id"]] for c in cases] == ["Passed", "Failed", "Blocked", "Not Run"]
    assert sm["kpi"]["passed"] == 1 and sm["kpi"]["blocked"] == 1 and sm["kpi"]["executed"] == 3
    assert execution.select(p, s, "failed") == [cases[1]["id"], cases[2]["id"]]
    assert execution.select(p, s, "selected", ids=[cases[0]["id"], "TC-9999"]) == [cases[0]["id"]]
    with pytest.raises(ValueError):
        execution.select(p, s, "everything")


def test_resume_starts_at_the_first_stage_the_last_pipeline_did_not_finish(demo):
    from agentqa.cli import resume_point
    _, s = demo
    assert resume_point(s) is None
    for st, status in [("analyze", "done"), ("explore", "done"), ("reconcile", "done"), ("write", "done"), ("design", "done"),
                       ("generate", "waiting for plan approval")]:
        s.insert("stage_runs", {"pipeline": "pl-1", "stage": st, "status": status, "started_at": "t"})
    pid, start, done = resume_point(s)
    assert pid == "pl-1" and start == "generate" and done == ["analyze", "explore", "reconcile", "write", "design"]


@pytest.fixture(autouse=True)
def vault_key(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())


@pytest.fixture
def v06(tmp_path):
    """The demo project with a recorded app map and logins, designed and approved."""
    from agentqa.agents import designer
    from agentqa.config import Project
    from agentqa.store import Store
    root = tmp_path / "demo"
    (root / "srs").mkdir(parents=True)
    shutil.copy(ROOT / "demo" / "project.yaml", root / "project.yaml")
    p = Project(root)
    s = Store(p.db_path)
    data = json.loads((ROOT / "tests" / "fixtures" / "demo_v05.json").read_text(encoding="utf-8").replace("{base}", p.base_url))
    for table in ("screens", "journeys", "requirements"):
        for row in data[table]:
            s.insert(table, row)
    for role, steps in data["login_steps"].items():
        p.vault.set_login_steps(role, steps)
    designer.design(p, s)
    designer.approve(s)
    return p, s


def test_generated_tests_hold_tokens_never_passwords(v06, tmp_path):
    from agentqa.agents import generator
    p, s = v06
    generator.generate(p, s)
    text = "".join(f.read_text(encoding="utf-8") for f in p.tests_dir.glob("*.py"))
    assert "{password" in text or "{mobile" in text
    for spec in p.roles().values():
        pw = (spec or {}).get("password")
        if pw:
            assert pw not in text
    shutil.rmtree(p.tests_dir, ignore_errors=True)


# ---- v0.7: Requirement Writer, take-over recording, English first --------------------------------

@pytest.fixture
def writer_ai(tmp_path, monkeypatch):
    from conftest import free_port
    from demo import mock_ai
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "home"))
    port = free_port()
    srv = mock_ai.serve(port)
    from agentqa.ai import gateway

    def use(key):
        gw = gateway()
        for k in gw.store.keys():
            gw.store.delete_key(k["id"])
        gw.store.set_policy({"order": ["openai"], "timeout_s": 5})
        gw.store.upsert_key({"provider": "openai", "label": "stand-in", "key": key, "priority": 1,
                             "base_url": f"http://127.0.0.1:{port}/openai/v1", "model": "gpt-4o-mini"})
    yield use
    srv.shutdown()


def test_requirement_writer_rewrites_every_requirement_and_flags_what_the_model_adds(v06, writer_ai):
    from agentqa.agents import req_writer
    p, s = v06
    out = req_writer.write(p, s, use_llm=False)                 # no model: the rules write it, and say so
    assert out["by_rules"] == out["requirements"] > 0
    w = s.one("SELECT std FROM requirements ORDER BY seq")["std"]["written"]
    assert w["statement"] and w["steps"] and w["by"].startswith("rules")
    p.cfg.setdefault("llm", {})["enabled"] = True
    writer_ai("sk-writer-good-0000000001")
    out = req_writer.write(p, s)
    assert out["by_model"] == out["requirements"] and out["flagged"] == 0
    w = s.one("SELECT std FROM requirements ORDER BY seq")["std"]["written"]
    assert w["by"].startswith("model") and w["user_story"].startswith("As a") and any(x["actor"] == "System" for x in w["steps"])
    writer_ai("sk-writer-liar-0000000002")                     # a model that adds "within 30 seconds"
    out = req_writer.write(p, s)
    assert out["flagged"] == out["requirements"]
    w = s.one("SELECT std FROM requirements ORDER BY seq")["std"]["written"]
    assert any("added 30" in f for f in w["flags"])
    from agentqa.agents import designer
    designer.design(p, s)                                       # re-designing keeps the writer's wording
    assert s.one("SELECT std FROM requirements ORDER BY seq")["std"]["written"]["flags"]


def test_recorded_actions_become_login_steps_and_typed_details_are_kept(v06):
    from agentqa import login_flow
    p, _ = v06
    ev = [{"kind": "click", "el": {"tag": "button", "text": "\U0001F464", "x": 400, "y": 20}},
          {"kind": "click", "el": {"tag": "button", "text": "Citizen Login"}},
          {"kind": "click", "el": {"tag": "input", "type": "text", "name": "rn"}},
          {"kind": "input", "el": {"tag": "input", "type": "text", "name": "rn", "label": "Registered number"}, "value": "9847012345"},
          {"kind": "click", "el": {"tag": "button", "text": "Get OTP"}},
          *[{"kind": "input", "el": {"tag": "input", "type": "text", "maxlength": 1, "aria": f"OTP digit {i}"}, "value": str(i)}
            for i in range(1, 7)],
          {"kind": "click", "el": {"tag": "button", "text": "", "aria": "", "elid": "verify-btn", "x": 10, "y": 20}},
          {"kind": "input", "el": {"tag": "input", "type": "password", "name": "pw"}, "value": "N3w-Secret!"},
          {"kind": "key", "key": "Enter"}]
    steps, learned = login_flow.steps_from_events(p, "citizen", ev)
    assert steps[0] == {"click": "\U0001F464"} and steps[1] == {"click": "Citizen Login"}
    assert steps[2]["value"] == "{mobile}" and steps[3] == {"click": "Get OTP"}
    assert sum(1 for x in steps if "otp" in x) == 1                       # six OTP boxes are one OTP step
    assert any("click_el" in x and x["click_el"]["elid"] == "verify-btn" for x in steps)
    assert {"fill": {"kind": "password", "name": "pw", "label": ""}, "value": "{password}"} in steps
    assert learned == {"password": "N3w-Secret!"} and steps[-1] == {"press": "Enter"}
    assert "N3w-Secret!" not in json.dumps(steps)                           # the password itself never sits in a step
    login_flow.save_learned(p, "citizen", learned)
    assert p.vault.account("citizen")["password"] == "N3w-Secret!"


def test_language_detection_and_switch_links():
    from agentqa import language
    assert not language.is_english({"lang": "ml", "letters": 200, "ratio": 0.3})
    assert not language.is_english({"lang": "ml", "letters": 200, "ratio": 0.9})      # the page says Malayalam
    assert language.is_english({"lang": "en", "letters": 200, "ratio": 0.98})
    assert not language.is_english({"lang": "", "letters": 300, "ratio": 0.2})        # no lang attribute, Hindi text
    assert language.is_switch("മലയാളം") and language.is_switch("English") and language.is_switch("", "/set-lang?lang=hi")
    assert not language.is_switch("Apply for Certificate", "/apply")
