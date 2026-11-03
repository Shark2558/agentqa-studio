"""M1.3: the Live View fixture is a trimmed real recording committed to git, so it is checked every run: no demo
password, no unmasked secret, no absolute path from the owner's machine, every screenshot it names present, and the
frontend copy in step with it. The tool that writes it refuses a password and only ever replaces a fixture."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "recordings" / "cli-fixture-pipeline"
FRONTEND = ROOT.parent / "frontend" / "src" / "test-fixtures" / "live-demo.json"
ABSOLUTE = re.compile(r"(?<![\w/])[A-Za-z]:[\\/]|(?<![\w/])\\\\[^\\\s]+\\|(?<![\w.:/-])/(?:Users|home)/")
SECRET_KEY = re.compile(r"password|passwd|pwd|otp|token|secret", re.I)
MASK = "•" * 8

sys.path.insert(0, str(ROOT / "tools"))
import make_live_fixture as tool  # noqa: E402


def events() -> list[dict]:
    return [json.loads(line) for f in sorted(FIXTURE.glob("events-*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def passwords() -> set[str]:
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (str, int)) and str(k).lower() in ("password", "passwd", "pwd"):
                    found.add(str(v))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(yaml.safe_load((ROOT / "demo" / "project.yaml").read_text(encoding="utf-8")))
    return found


def unmasked(node, where: str = "") -> list[str]:
    if isinstance(node, dict):
        out = []
        for k, v in node.items():
            if SECRET_KEY.search(str(k)) and isinstance(v, str) and v and v != MASK:
                out.append(f"{where}.{k}")
            out += unmasked(v, f"{where}.{k}")
        return out
    if isinstance(node, list):
        return [x for i, v in enumerate(node) for x in unmasked(v, f"{where}[{i}]")]
    return []


def test_the_committed_fixture_carries_no_password_secret_or_local_path():
    pws = passwords()
    assert len(pws) >= 3                                      # the scan is only as good as this list
    for e in events():
        blob = json.dumps(e, ensure_ascii=False)
        assert not any(pw in blob for pw in pws), f"{e['w']}:{e['seq']} contains a demo password"
        assert not ABSOLUTE.search(blob), f"{e['w']}:{e['seq']} contains an absolute path"
        assert not unmasked(e), f"{e['w']}:{e['seq']} has an unmasked secret field"


def test_every_screenshot_the_fixture_names_is_there_and_nothing_else():
    named = {e["shot"] for e in events() if e.get("shot")}
    present = {f.name for f in (FIXTURE / "shots").iterdir()}
    assert named == present and len(present) == 12


def test_the_frontend_copy_matches_the_recording():
    copy = json.loads(FRONTEND.read_text(encoding="utf-8"))
    assert copy["session"] == FIXTURE.name
    assert sorted((e["w"], e["seq"]) for e in copy["events"]) == sorted((e["w"], e["seq"]) for e in events())
    assert all("phase" in e for e in copy["events"])
    assert not ABSOLUTE.search(FRONTEND.read_text(encoding="utf-8"))


# ---- the tool ---------------------------------------------------------------------------------------------------

def fake_recording(folder: Path, extra: list[dict] = ()) -> Path:
    """A tiny recording with the two stages the tool hangs its AI lines on, plus `extra` events."""
    folder.mkdir(parents=True)
    rows = [{"agent": "srs", "kind": "stage_start", "stage": "analyze"},
            {"agent": "srs", "kind": "stage_end", "stage": "analyze"},
            {"agent": "writer", "kind": "stage_start", "stage": "write"},
            {"agent": "writer", "kind": "stage_end", "stage": "write"},
            {"agent": "reporter", "kind": "stage_end", "stage": "report",
             "result": {"report": "G:\\My Drive\\Somewhere\\backend\\projects\\demo\\reports\\report.html",
                        "rtm": "/home/someone/agentqa/projects/demo/reports/rtm.csv"}}, *extra]
    lines = [json.dumps({"t": 1000.0 + i, "seq": i + 1, "w": "main", "title": f"step {i}", **r}) for i, r in enumerate(rows)]
    (folder / "events-main.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_the_tool_strips_absolute_paths_to_the_part_inside_the_project(tmp_path):
    src = fake_recording(tmp_path / "rec")
    out = tmp_path / "out" / "fx"
    assert tool.main([str(src), "--out", str(out), "--frontend", str(tmp_path / "fe.json")]) == 0
    text = (out / "events-main.jsonl").read_text(encoding="utf-8")
    assert not ABSOLUTE.search(text) and "reports/report.html" in text and "reports/rtm.csv" in text


def test_the_tool_refuses_to_write_anything_when_a_demo_password_appears(tmp_path):
    pw = sorted(passwords())[0]
    src = fake_recording(tmp_path / "rec", [{"agent": "explorer", "kind": "action", "title": f"typed {pw}"}])
    out = tmp_path / "out" / "fx"
    assert tool.main([str(src), "--out", str(out), "--frontend", str(tmp_path / "fe.json")]) == 1
    assert not out.exists() and not (tmp_path / "fe.json").exists()


@pytest.mark.parametrize("where", ["source", "inside-source", "a-real-folder"])
def test_the_tool_only_ever_replaces_a_folder_that_looks_like_a_fixture(tmp_path, where):
    src = fake_recording(tmp_path / "rec")
    if where == "source":
        out = src
    elif where == "inside-source":
        out = src / "nested"
    else:
        out = tmp_path / "precious"
        out.mkdir()
        (out / "notes.txt").write_text("keep me", encoding="utf-8")
    assert tool.main([str(src), "--out", str(out), "--frontend", str(tmp_path / "fe.json")]) == 2
    assert (src / "events-main.jsonl").exists()
    if where == "a-real-folder":
        assert (out / "notes.txt").read_text(encoding="utf-8") == "keep me"
