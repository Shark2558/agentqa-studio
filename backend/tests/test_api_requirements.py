"""M1.4 (FR-ONB-4): requirement dispositions with who and why, paged, and the traceability matrix (RTM) download.
"covered" and "gap" are computed by AgentQA and are never a person's claim."""
from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from conftest import CSRF, GATES_WHO


def _list(g, **params) -> dict:
    r = g.client.get(f"{g.base}/requirements", params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _set(g, rid: str, body: dict):
    return g.client.patch(f"{g.base}/requirements/{rid}", json=body, headers=CSRF)


def test_the_list_pages_in_order_with_each_disposition_note(gates):
    data = _list(gates)
    assert data["total"] == 35 and len(data["requirements"]) == 35 and data["documents"]
    assert [r["seq"] for r in data["requirements"]] == sorted(r["seq"] for r in data["requirements"])
    assert all("disposition_note" in r for r in data["requirements"])
    page = _list(gates, limit=10, offset=30)
    assert len(page["requirements"]) == 5 and page["total"] == 35
    assert gates.client.get(f"{gates.base}/requirements", params={"limit": 201}).status_code == 422


def test_a_disposition_is_set_with_a_reason_and_logged(gates):
    r = _set(gates, "FR-01", {"disposition": "manual", "why": "checked by hand each release"})
    assert r.status_code == 200
    assert r.json()["data"]["disposition"] == "manual"
    assert r.json()["data"]["disposition_note"] == "checked by hand each release"
    with gates.db() as s:
        row = s.one("SELECT * FROM change_log ORDER BY id DESC LIMIT 1")
    assert row["object_id"] == "FR-01" and row["by"] == GATES_WHO and row["justification"] == "checked by hand each release"


@pytest.mark.parametrize("body", [{"disposition": "covered", "why": "x"}, {"disposition": "gap", "why": "x"},
                                  {"disposition": "manual"}, {"disposition": "manual", "why": "  "},
                                  {"disposition": "manual", "why": "x" * 501}, {"disposition": "manual", "why": "x", "by": "me"}])
def test_only_the_four_dispositions_with_a_reason_are_accepted(gates, body):
    assert _set(gates, "FR-01", body).status_code == 422


def test_an_unknown_requirement_is_404(gates):
    assert _set(gates, "FR-99", {"disposition": "manual", "why": "x"}).status_code == 404
    assert _set(gates, "FR 01", {"disposition": "manual", "why": "x"}).status_code in (404, 422)


def test_the_rtm_downloads_as_text_only_cells_and_is_logged(gates):
    with gates.db() as s:
        s.exec("UPDATE requirements SET text=? WHERE id='FR-02'", ["=HYPERLINK(\"http://evil.example\")"])
    r = gates.client.get(f"{gates.base}/requirements/rtm.xlsx")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ws = load_workbook(io.BytesIO(r.content))["Traceability"]
    cells = [c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and "HYPERLINK" in c.value]
    assert cells and all(c.data_type == "s" and c.value.startswith("'=") for c in cells)
    with gates.db() as s:
        row = s.one("SELECT * FROM change_log ORDER BY id DESC LIMIT 1")
    assert row["change"] == "downloaded the traceability matrix (Excel)" and row["by"] == GATES_WHO


def test_a_viewer_reads_and_downloads_but_cannot_set_a_disposition(gates):
    viewer = gates.as_role("viewer")
    assert viewer.get(f"{gates.base}/requirements").status_code == 200
    assert viewer.get(f"{gates.base}/requirements/rtm.xlsx").status_code == 200
    r = viewer.patch(f"{gates.base}/requirements/FR-01", json={"disposition": "manual", "why": "x"}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"


def test_a_requirement_id_from_a_document_table_can_be_given_a_disposition(gates):
    """Ids come from SRS cells as written (srs_analyst: upper-cased, spaces to dashes): slashes and brackets happen."""
    with gates.db() as s:
        for n, rid in enumerate(("BR/01", "REQ-1 (a)", "UC#3"), start=90):
            s.insert("requirements", {"id": rid, "seq": n, "section": "x", "text": "t", "kind": "functional"})
    for rid in ("BR%2F01", "REQ-1%20(a)", "UC%233"):
        r = _set(gates, rid, {"disposition": "manual", "why": "checked by hand"})
        assert r.status_code == 200, (rid, r.text)
    assert _set(gates, "FR-01%01", {"disposition": "manual", "why": "x"}).status_code == 422     # a control character


def test_a_matrix_that_cannot_be_written_is_not_served_stale_or_logged(gates, monkeypatch):
    stale = gates.project.reports_dir / "rtm.xlsx"
    stale.write_bytes(b"an older matrix")

    def locked(self, *args, **kwargs):
        raise PermissionError("rtm.xlsx is open in Excel")
    monkeypatch.setattr("openpyxl.Workbook.save", locked)
    r = gates.client.get(f"{gates.base}/requirements/rtm.xlsx")
    assert r.status_code == 503 and r.json()["error"]["code"] == "unavailable"
    with gates.db() as s:
        assert s.scalar("SELECT COUNT(*) FROM change_log WHERE object='export'") == 0
