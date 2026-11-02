"""Two-way tracker sync against the bundled mock Jira and Azure DevOps (no network)."""
import threading
import time

import httpx
import pytest
import uvicorn

from agentqa.integrations import trackers
from tests.conftest import free_port


@pytest.fixture(scope="module")
def mock_url():
    from demo import mock_trackers
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(mock_trackers.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def _defect(s, did, status="confirmed"):
    s.insert("defects", {"id": did, "seq": int(did[-3:]), "run_id": "run-1", "case_ids": ["TC-0001"], "signature": f"sig:{did}",
                         "title": f"Defect {did}", "severity": "High", "priority": "P1", "role": "citizen",
                         "url": "http://portal/x", "steps": "Open x", "expected": "works", "actual": "fails",
                         "evidence": [], "rule_ids": [], "req_ids": ["FR-01"], "status": status, "created_at": "now"})


@pytest.mark.parametrize("system", ["jira", "ado"])
def test_full_loop_create_fix_verify_reopen_reject(demo, mock_url, system):
    p, s = demo
    spec = ({"jira": {"enabled": True, "base_url": f"{mock_url}/jira", "project_key": "T", "email": "qa@x", "token": "t"}}
            if system == "jira" else
            {"azure_devops": {"enabled": True, "org_url": f"{mock_url}/ado/org", "project": "Demo", "token": "t"}})
    p.cfg["trackers"] = {**p.cfg["trackers"], **spec}
    for did in ("DEF-001", "DEF-002", "DEF-003"):
        _defect(s, did)
    _defect(s, "DEF-004", status="draft")                 # drafts are never sent
    assert all(r["ok"] for r in trackers.test_connection(p.cfg))

    out = trackers.sync(p, s)
    assert out["created"] == 3 and out["errors"] == 0
    keys = {d["id"]: d["external_key"] for d in s.all("SELECT * FROM defects WHERE external_key IS NOT NULL")}
    assert set(keys) == {"DEF-001", "DEF-002", "DEF-003"}

    # the developer fixes two and closes one as Won't Fix
    httpx.post(f"{mock_url}/ui/{system}/{keys['DEF-001']}/fix")
    httpx.post(f"{mock_url}/ui/{system}/{keys['DEF-002']}/fix")
    httpx.post(f"{mock_url}/ui/{system}/{keys['DEF-003']}/wontfix")
    out = trackers.sync(p, s)
    assert out["fixed"] == 2 and out["rejected"] == 1

    # the next AgentQA run: DEF-001 passes now, DEF-002 still fails
    s.update("defects", "id", "DEF-001", {"status": "resolved"})
    s.update("defects", "id", "DEF-002", {"status": "reopened"})
    out = trackers.sync(p, s)
    assert out["verified"] == 1 and out["reopened"] == 1 and out["errors"] == 0
    state = httpx.get(f"{mock_url}/api/state").json()[system]
    closed = state[keys["DEF-001"]]
    assert (closed.get("status") or closed["fields"]["System.State"]) in ("Done", "Closed")
    reopened = state[keys["DEF-002"]]
    assert (reopened.get("status") or reopened["fields"]["System.State"]) in ("To Do", "Active")
    assert s.one("SELECT status FROM defects WHERE id='DEF-003'")["status"] == "rejected"

    assert trackers.sync(p, s)["verified"] == 0, "a second sync repeats nothing"
