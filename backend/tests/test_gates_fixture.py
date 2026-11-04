"""The gates fixture (M1.4): a real No-AI demo store stopped at the plan gate, then continued, trimmed by
tools/make_gates_fixture.py. Demo data only: no demo password or OTP, no absolute path, a few small images."""
from __future__ import annotations

import json
import sys

import pytest

from conftest import ROOT
from gates_fixture import FIXTURE, load, rows

sys.path.insert(0, str(ROOT / "tools"))
import make_gates_fixture  # noqa: E402
import make_live_fixture  # noqa: E402

MAX_IMAGE_BYTES = 80_000


def test_the_fixture_holds_every_gate_table():
    tables = rows()["tables"]
    for name in ("questions", "plan", "cases", "manual_cases", "defects", "requirements", "visual", "documents"):
        assert tables[name], name
    assert any(q["status"] == "open" for q in tables["questions"])
    assert len(tables["defects"]) == 19


def test_the_fixture_has_no_demo_password_and_no_absolute_path():
    blob = (FIXTURE / "rows.json").read_text(encoding="utf-8")
    secrets = make_gates_fixture.demo_secrets()
    assert secrets and not any(secret in blob for secret in secrets)
    assert make_gates_fixture.problems(rows(), secrets) == []


def test_the_check_finds_a_planted_absolute_path_but_not_a_regex():
    assert make_gates_fixture.problems({"a": [r"saved to C:\Users\x\run.png"]}, set()) == ["an absolute path"]
    assert make_gates_fixture.problems({"a": r"\bno\b[^.]{0,60}\b(match)\b"}, set()) == []
    assert make_live_fixture.ABSOLUTE.search(r"\\share\x\y")


def test_the_tool_refuses_a_one_time_code_the_run_received(demo, tmp_path):
    from agentqa.inbox import InboxStore
    p, s = demo
    load(p, s)
    InboxStore(p.state / "inbox.db").add("sms", "9895000001", "Your OTP is 482913. Valid for 5 minutes.")
    assert make_gates_fixture.delivered_codes(p) == {"482913"}
    s.exec("UPDATE results SET message=? WHERE case_id='TC-0001'", ["typed 482913 into the OTP box"])
    s.close()
    out = tmp_path / "out"
    assert make_gates_fixture.main([str(p.root), "--out", str(out), "--frontend", str(tmp_path / "f.json")]) == 1
    assert not out.exists()


def test_the_fixture_has_at_most_six_small_images_and_each_is_used():
    images = sorted((FIXTURE / "images").iterdir())
    assert 0 < len(images) <= make_gates_fixture.MAX_IMAGES
    assert all(f.suffix == ".png" and f.stat().st_size <= MAX_IMAGE_BYTES for f in images)
    assert sorted(rows()["files"].values()) == sorted(f"images/{f.name}" for f in images)


def test_loading_puts_the_rows_in_the_store_and_the_images_at_their_paths(demo):
    p, s = demo
    counts = load(p, s)
    assert counts["defects"] == 19 == s.scalar("SELECT COUNT(*) FROM defects")
    shots = [e for d in s.all("SELECT evidence FROM defects") for e in d["evidence"] or [] if e["kind"] == "screenshot"]
    assert all(e["path"].startswith(str(p.root)) for e in shots)              # absolute, as the engine stores them
    kept = [e for e in shots if (p.root / e["path"][len(str(p.root)) + 1:]).is_file()]
    assert kept


def test_the_tool_round_trips_the_fixture(demo, tmp_path):
    p, s = demo
    load(p, s)
    s.close()
    out, front = tmp_path / "out", tmp_path / "front.json"
    assert make_gates_fixture.main([str(p.root), "--out", str(out), "--frontend", str(front)]) == 0
    again = json.loads((out / "rows.json").read_text(encoding="utf-8"))["tables"]
    assert {k: len(v) for k, v in again.items()} == {k: len(v) for k, v in rows()["tables"].items()}
    assert json.loads(front.read_text(encoding="utf-8"))["questions"]["items"]


@pytest.mark.parametrize("where", ["steps", "actual"])
def test_the_tool_refuses_a_store_holding_a_demo_password(demo, tmp_path, where):
    p, s = demo
    load(p, s)
    secret = sorted(make_gates_fixture.demo_secrets())[0]
    s.exec(f"UPDATE defects SET {where}=? WHERE id='DEF-001'", [f"typed {secret} into the box"])
    s.close()
    out = tmp_path / "out"
    assert make_gates_fixture.main([str(p.root), "--out", str(out), "--frontend", str(tmp_path / "f.json")]) == 1
    assert not out.exists()


def test_the_tool_never_replaces_a_folder_that_is_not_a_fixture(demo, tmp_path):
    p, s = demo
    load(p, s)
    s.close()
    keep = tmp_path / "keep"
    keep.mkdir()
    (keep / "notes.txt").write_text("mine", encoding="utf-8")
    assert make_gates_fixture.main([str(p.root), "--out", str(keep), "--frontend", str(tmp_path / "f.json")]) == 2
    assert (keep / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_the_check_refuses_a_real_email_but_not_example_addresses_or_file_names():
    found = make_gates_fixture.problems({"by": "akash.someone@gmail.com (owner)"}, set())
    assert found == ["an email address that is not an example one"]
    assert make_gates_fixture.problems({"a": ["qa.tester@example.com", "x@dept.example", "admin@department-current.png",
                                              "y@portal.test"]}, set()) == []
    assert make_gates_fixture.problems({"a": "/tmp/run/x.png"}, set()) == ["an absolute path"]


def test_the_project_folder_is_cut_only_at_a_folder_boundary(tmp_path):
    rel = make_gates_fixture.Relative(tmp_path / "demo")
    assert rel.text(str(tmp_path / "demo" / "runs" / "x.png")).replace("\\", "/") == "runs/x.png"
    assert rel.text(str(tmp_path / "demo2" / "x.png")) == str(tmp_path / "demo2" / "x.png")


def test_two_images_with_one_name_in_two_runs_stay_apart():
    a, b = make_gates_fixture.image_name("runs/r1/evidence/TC-1.png"), make_gates_fixture.image_name("runs/r2/evidence/TC-1.png")
    assert a != b and a.endswith("TC-1.png") and b.endswith("TC-1.png")


def test_the_web_app_file_must_be_a_json_file(demo, tmp_path):
    p, s = demo
    load(p, s)
    s.close()
    out = tmp_path / "out"
    assert make_gates_fixture.main([str(p.root), "--out", str(out), "--frontend", str(tmp_path / "x.py")]) == 2
    assert not out.exists()


def test_a_failed_write_keeps_the_fixture_that_was_there(demo, tmp_path, monkeypatch):
    p, s = demo
    load(p, s)
    s.close()
    out = tmp_path / "out"
    assert make_gates_fixture.main([str(p.root), "--out", str(out), "--frontend", str(tmp_path / "f.json")]) == 0
    before = (out / "rows.json").read_bytes()

    def broken(src, dest):
        raise OSError("disk full")
    monkeypatch.setattr(make_gates_fixture, "shrink", broken)
    with pytest.raises(OSError):
        make_gates_fixture.main([str(p.root), "--out", str(out), "--frontend", str(tmp_path / "f.json")])
    assert (out / "rows.json").read_bytes() == before and len(list((out / "images").iterdir())) == 6
    assert not list(tmp_path.glob("out.*"))
