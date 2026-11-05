"""M1.4 Phase B in a real browser: the three gates, the downloads and the change log, against a throwaway server and
owner, so the owner's own sign-in is never read (`make gates-check`, needs `make web-build`; Playwright in the venv).

    python -I frontend/design-system/check_gates.py

The demo project holds the gates fixture (the owner's real No-AI demo), put back at the plan gate: every case
proposed, the ready imported cases ready, the plan not approved. As the owner, in the built app at 1440 px:
  1. Questions: answer two (one with a value), reopen one with a reason;
  2. Test plan: reject three cases with a reason, approve one whole type, approve the ready imported cases, approve
     the plan;
  3. Defects: confirm 17, reject 2 with a reason;
  4. Requirements: mark one "tested by hand" with a reason;
  5. Downloads: the test-case Excel and the traceability matrix open, the Jira CSV has its header and no drafts or
     rejected defects, the Zoho CSV starts with a byte-order mark;
  6. Change log: every action above is recorded with the owner's email and role, each with its reason, and the page
     shows them;
then Phase C (check_gates_c.py: the help box, take-over with the typed text wiped, Pause and Resume, visual review,
heals, and their change-log rows), then as a Viewer (a pass minted with the throwaway server's secret): the gate pages,
Visual review and Heals included, show no controls, the downloads are there, and a write answers 403 read_only. Exit 1
on any problem.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_app as app  # noqa: E402  (the throwaway server and owner)
import check_gates_c as phase_c  # noqa: E402  (help box, take-over, pause, visual review, heals)

WHO = f"{app.EMAIL} (owner)"
WAIT_MS = 15_000
STEP_MS = 300                 # a breath between actions: the app's refetches stay well under 240 requests a minute
CONFIRM, REJECT = 17, 2
BOM = b"\xef\xbb\xbf"
WHY = {"reopen": "picked the wrong option first", "cases": "duplicates for the check", "defects": "works as designed in this demo",
       "manual": "needs a real SMS to a real phone"}
WHY_BOX = re.compile("Why")


class Problem(Exception):
    pass


def seed(projects: Path, slug: str) -> None:
    """The gates fixture, put back where a gated run stops: cases proposed, imported cases ready, plan not approved."""
    app.seed_gates(projects, slug)
    from agentqa.config import Project
    from agentqa.store import Store
    with closing(Store(Project(projects / slug).db_path)) as store:
        store.exec("UPDATE cases SET status='proposed'")
        store.exec("UPDATE manual_cases SET status='ready' WHERE status='approved'")
        store.exec("UPDATE plan SET approved=0, approved_at=NULL WHERE id=1")


def write_ok(page, path: str, action) -> None:
    """Run `action` and wait for the write it starts (POST or PATCH to `path`) to succeed."""
    with page.expect_response(lambda r: path in r.url and r.request.method in ("POST", "PATCH"), timeout=WAIT_MS) as info:
        action()
    if info.value.status >= 300:
        raise Problem(f"{path} answered {info.value.status}: {info.value.text()[:200]}")
    page.wait_for_timeout(STEP_MS)


def give_reason(page, why: str, confirm: str, path: str) -> None:
    page.get_by_role("textbox", name=WHY_BOX).fill(why)
    write_ok(page, path, lambda: page.get_by_role("button", name=confirm, exact=True).click())


def questions(page, base: str, slug: str) -> None:
    page.goto(f"{base}/app/projects/{slug}/questions")
    cards = page.locator("article.q-card")
    expect(cards).to_have_count(15, timeout=WAIT_MS)
    named = cards.filter(has=page.get_by_role("radio", name="Exists under another name: enter it")).first
    named.get_by_role("radio", name="Exists under another name: enter it").check()
    named.get_by_role("textbox", name=re.compile("Your value")).fill("Comments")
    write_ok(page, "/answer", lambda: named.get_by_role("button", name="Save answer").click())
    expect(cards).to_have_count(14, timeout=WAIT_MS)
    plain = cards.first
    plain.get_by_role("radio").first.check()                 # option 0 never asks for a value (VALUE_OPTIONS)
    write_ok(page, "/answer", lambda: plain.get_by_role("button", name="Save answer").click())
    expect(cards).to_have_count(13, timeout=WAIT_MS)
    page.get_by_role("button", name="Answered (2)").click()
    expect(cards).to_have_count(2, timeout=WAIT_MS)
    cards.first.get_by_role("button", name=re.compile(r"^Reopen question")).click()
    give_reason(page, WHY["reopen"], "Reopen the question", "/reopen")
    expect(cards).to_have_count(1, timeout=WAIT_MS)


def plan(page, base: str, slug: str) -> None:
    page.goto(f"{base}/app/projects/{slug}/plan")
    for cid in ("TC-0001", "TC-0002", "TC-0003"):
        page.get_by_role("checkbox", name=f"Select {cid}").check()
    page.get_by_role("button", name="Reject", exact=True).click()
    give_reason(page, WHY["cases"], "Reject 3 cases", "/plan/cases")
    write_ok(page, "/plan/types/a11y_basic", lambda: page.get_by_role("button", name="Approve every a11y_basic case").click())
    write_ok(page, "/plan/imported", lambda: page.get_by_role("button", name=re.compile(r"^Approve the \d+ ready imported cases$")).click())
    write_ok(page, "/plan/approve", lambda: page.get_by_role("button", name="Approve the test plan").click())
    approval = page.get_by_role("region", name="Approval")
    expect(approval).to_contain_text("Approved on", timeout=WAIT_MS)
    expect(approval.get_by_role("button", name="Generate and run")).to_be_visible()


def defects(page, base: str, slug: str) -> None:
    ids = [d["id"] for d in page.request.get(f"{base}/api/v1/projects/{slug}/defects?limit=200").json()["data"]["items"]]
    if len(ids) != CONFIRM + REJECT:
        raise Problem(f"expected {CONFIRM + REJECT} defects in the fixture, found {len(ids)}")
    page.goto(f"{base}/app/projects/{slug}/defects")
    for did in ids[:CONFIRM]:
        page.get_by_role("checkbox", name=f"Select {did}").check()
    write_ok(page, "/defects/decisions", lambda: page.get_by_role("button", name="Confirm", exact=True).click())
    for did in ids[CONFIRM:]:
        page.get_by_role("checkbox", name=f"Select {did}").check()
    page.get_by_role("button", name="Reject", exact=True).click()
    give_reason(page, WHY["defects"], f"Reject {REJECT} defects", "/defects/decisions")


def requirements(page, base: str, slug: str) -> None:
    page.goto(f"{base}/app/projects/{slug}/requirements")
    page.get_by_role("combobox", name="New disposition for FR-01").select_option("manual")
    page.get_by_role("button", name="Set the disposition of FR-01").click()
    give_reason(page, WHY["manual"], "Set FR-01 to “Tested by hand”", "/requirements/FR-01")


def download(page, link: str) -> bytes:
    with page.expect_download(timeout=WAIT_MS) as info:
        page.get_by_role("link", name=link).click()
    page.wait_for_timeout(STEP_MS)
    return Path(info.value.path()).read_bytes()


def workbook_rows(data: bytes) -> int:
    from openpyxl import load_workbook
    return sum(ws.max_row for ws in load_workbook(io.BytesIO(data), read_only=True).worksheets)


def downloads(page, base: str, slug: str) -> None:
    page.goto(f"{base}/app/projects/{slug}/plan")
    if workbook_rows(download(page, "Download the test cases (Excel)")) < 2:
        raise Problem("the test-case workbook is empty")
    page.goto(f"{base}/app/projects/{slug}/requirements")
    if workbook_rows(download(page, "Download the traceability matrix (Excel)")) < 2:
        raise Problem("the traceability matrix is empty")
    page.goto(f"{base}/app/projects/{slug}/defects")
    jira = list(csv.reader(io.StringIO(download(page, "Defects for Jira (CSV)").decode("utf-8-sig"))))
    if jira[0][:2] != ["Defect ID", "Summary"] or len(jira) - 1 != CONFIRM:
        raise Problem(f"Jira CSV: header {jira[0][:2]}, {len(jira) - 1} defects (expected the {CONFIRM} confirmed only)")
    zoho = download(page, "Defects for Zoho (CSV)")
    if not zoho.startswith(BOM) or not zoho[len(BOM):].decode("utf-8").startswith("Title,"):
        raise Problem("the Zoho CSV does not start with a byte-order mark and its Title column")


def change_log(page, base: str, slug: str) -> list[str]:
    rows = [r for r in page.request.get(f"{base}/api/v1/projects/{slug}/changes?limit=200").json()["data"]["items"] if r["by"] == WHO]
    def count(obj: str, why: str = "", starts: str = "") -> int:
        return sum(1 for r in rows if r["object"] == obj and (not why or r["why"] == why) and r["change"].startswith(starts))
    expected = {
        "two answers": count("question", starts="answered '") == 2, "a reopen with its reason": count("question", WHY["reopen"]) == 1,
        "three cases rejected with the reason": count("case", WHY["cases"]) == 1, "a whole type approved": count("case", starts="approved") >= 1,
        "the imported cases approved": count("imported case") == 1, "the plan approved": count("plan", starts="approved the plan") == 1,
        f"{CONFIRM} confirmations": sum(1 for r in rows if r["object"] == "defect" and not r["why"]) == CONFIRM,
        f"{REJECT} rejections with the reason": count("defect", WHY["defects"]) == REJECT,
        "the disposition with its reason": count("requirement", WHY["manual"]) == 1, "four downloads": count("export") == 4,
    }
    problems = [f"change log: no {name} by {WHO}" for name, ok in expected.items() if not ok]
    page.goto(f"{base}/app/projects/{slug}/changes")
    for text in (WHO, *WHY.values()):
        try:
            expect(page.get_by_text(text, exact=True).first).to_be_visible(timeout=WAIT_MS)
        except AssertionError:
            problems.append(f"change log page: “{text}” is not shown")
    return problems


def viewer(browser, base: str, slug: str) -> list[str]:
    from agentqa.api.auth import COOKIE, Sessions, User
    token = Sessions(SimpleNamespace(secret_key=app.SECRET, session_hours=1, cookie_secure=False)).issue(User("viewer@example.com", "viewer"))
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies([{"name": COOKIE, "value": token, "url": base}])
    page, problems = context.new_page(), []
    for name, link in (("questions", None), ("plan", "Download the test cases (Excel)"), ("defects", "Defects for Jira (CSV)"),
                       ("requirements", "Download the traceability matrix (Excel)"), ("visual", None), ("heals", None)):
        page.goto(f"{base}/app/projects/{slug}/{name}")
        page.wait_for_load_state("networkidle")
        controls = page.locator("main input[type=radio], main input[type=checkbox]:not(.check input), main select, main textarea").count()
        # the filter chips "Approved", "Rejected", "Confirmed" are views, not decisions
        decisions = page.get_by_role("button", name=re.compile(
            r"^(Save answer|Apply my answers|Approve(?!d)|Reject(?!ed)|Confirm(?!ed)|Generate and run|Back to|Report as|Pause and|Paused:|Take over|Open$)")).count()
        if controls or decisions:
            problems.append(f"Viewer on {name}: {controls} fields and {decisions} decision buttons")
        if link and not page.get_by_role("link", name=link).is_visible():
            problems.append(f"Viewer on {name}: no “{link}”")
        page.wait_for_timeout(STEP_MS)
    r = context.request.post(f"{base}/api/v1/projects/{slug}/defects/decisions", headers=app.CSRF,
                             data={"ids": ["DEF-001"], "decision": "confirmed", "why": ""})
    if r.status != 403 or r.json()["error"]["code"] != "read_only":
        problems.append(f"a Viewer's write answered {r.status}, not 403 read_only")
    context.close()
    return problems


def run(browser, base: str, projects: Path) -> list[str]:
    context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    slug = app.sign_in(context, base)
    seed(projects, slug)
    page, problems = context.new_page(), []
    for step in (questions, plan, defects, requirements, downloads):
        try:
            step(page, base, slug)
        except (Problem, PlaywrightError, AssertionError) as e:
            problems.append(f"{step.__name__}: {' | '.join(str(e).splitlines()[:4])}")       # the locator is on line 2-4
    problems += change_log(page, base, slug)
    problems += phase_c.run(page, base, projects, slug)
    context.close()
    return problems + viewer(browser, base, slug)


def main() -> int:
    if not (app.ROOT / "frontend" / "dist" / "index.html").is_file():
        print("frontend/dist is missing: run `make web-build` first")
        return 1
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:      # Windows may still hold the test db for a moment
        projects = Path(tmp) / "projects"
        proc, base = app.start_server(projects)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                problems = run(browser, base, projects)
                browser.close()
        finally:
            proc.kill()
            proc.wait()
    for problem in problems:
        print(f"  PROBLEM  {problem}")
    if problems:
        print(f"\n{len(problems)} problem(s)")
        return 1
    print("\nthe three gates, the downloads, the help box, take-over, pause, visual review, heals and the change log work in the "
          "built app as the owner, and a Viewer gets no controls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
