from pathlib import Path

from agentqa.agents import importer

ROOT = Path(__file__).resolve().parent.parent


def test_sample_sheet_is_read_with_multi_row_cases():
    cases = importer.read_cases(ROOT / "demo" / "manual_tests.xlsx")
    assert [c["id"] for c in cases][:3] == ["TC_01", "TC_02", "TC_03"]
    assert all(c["steps"] for c in cases)
    assert len(cases) >= 8


def test_cases_convert_against_the_real_app_map(explored):
    p, s = explored
    out = importer.import_file(p, s, ROOT / "demo" / "manual_tests.xlsx")
    assert out["cases"] >= 8
    assert out["ready"] >= 7, "most sample cases convert fully"
    rows = {r["id"]: r for r in s.all("SELECT * FROM manual_cases")}
    first = rows["TC_01"]["converted"]
    actions = [st["action"] for st in first["steps"]]
    assert first["role"] == "citizen" and "goto" in actions and rows["TC_01"]["coverage"] == 1.0
    review = [r for r in rows.values() if r["status"] == "review"]
    assert review and all(any(not st["ok"] and st.get("why") for st in r["converted"]["steps"]) for r in review), \
        "every step that needs a person says why"


def test_login_steps_become_sessions_not_typed_passwords(explored):
    p, s = explored
    ctx = importer.Context(p, s)
    st = importer.convert_step("Login as Clerk", ctx, {"role": None, "path": None}, {})
    assert st == {**st, "action": "session", "role": "clerk", "ok": True}
