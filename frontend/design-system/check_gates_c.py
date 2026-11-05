"""M1.4 Phase C in a real browser: the part of `make gates-check` that runs after the three gates, as the owner, on the
same throwaway server (check_gates.py calls `run`).

  1. Help box: a question put in the store while the project page is open shows the dock within 3 s and the tab's
     title changes; the owner opens it (the page behind it is closed to the keyboard); a drag from the answer box
     released on the backdrop keeps the dialog and the text; Minimise opens the page again and the focus goes back to
     the button that opened it; the answer is a choice, after which the focus is on the page's heading.
  1b. Dock clearance: on a phone the end of the page scrolls clear of the dock, by the dock's own height (--dock-h).
  2. Take-over: what is typed is hidden until a box is chosen; a click in the middle of the screenshot queues a click in
     the middle of the agent's 1280 x 800 browser, and one near its far corner lands where the same share of the
     picture's own box does; typing into its password box queues a secret command. This script, acting as the agent,
     runs the queued commands with the engine's own loop on a stand-in page (tests/assist_fakes.py): the typed text is
     then gone from the row and from the database file. Continue hands the browser back (focus on the heading).
  3. Pause and Resume while a run goes (a job row for this script's own, living process).
  4. Visual review: one changed screen kept as its new baseline with a reason, the other reported as a defect.
  5. Heals: the locator fix approved, the workflow fix rejected with a reason.
Then the change log holds each of these with the owner's email and role."""
from __future__ import annotations

import os
import re
import sys
from contextlib import closing
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, expect

import check_app as app

WHO = f"{app.EMAIL} (owner)"
MARKER = "Zq7-typed-secret-41"           # text nothing else in the store contains
WAIT_MS = 15_000
DOCK_MS = 3_000
STEP_MS = 300
TOLERANCE_PX = 2          # a click in the middle: the pointer lands on whole pixels, each worth 1.6 px of the agent's screen
EXACT_PX = 1              # a click anywhere else is checked against the picture's own box and where the pointer really landed
DRAFT = "half an answer, typed before the drag"
PHONE = {"width": 375, "height": 667}
SCREEN = (1280, 800)      # the agent's browser, as the seeded question says
CORNER = 0.97
WHY = {"visual": "the new header is intended", "heal": "the old field comes back next release"}
# The gap between the last thing on the page and the top of the dock, and the dock's height as the page was told.
CLEARANCE_JS = """() => {
  const dock = document.querySelector('.needs-dock').getBoundingClientRect();
  const last = document.querySelector('main').lastElementChild.getBoundingClientRect();
  return { gap: dock.top - last.bottom, dock: dock.height, var: parseFloat(document.documentElement.style.getPropertyValue('--dock-h')) || 0 };
}"""
# Remembers where the next click really landed (the pointer's whole pixel), before anything handles it.
WATCH_CLICK_JS = """() => { window.__click = null;
  document.addEventListener('click', (e) => { window.__click = [e.clientX, e.clientY]; }, { capture: true, once: true }); }"""


class Problem(Exception):
    pass


def _store(projects: Path, slug: str):
    from agentqa.config import Project
    from agentqa.store import Store
    project = Project(projects / slug)
    return project, closing(Store(project.db_path))


def write_ok(page, path: str, action) -> None:
    with page.expect_response(lambda r: path in r.url and r.request.method == "POST", timeout=WAIT_MS) as info:
        action()
    if info.value.status >= 300:
        raise Problem(f"{path} answered {info.value.status}: {info.value.text()[:200]}")
    page.wait_for_timeout(STEP_MS)


def _row(projects: Path, slug: str, sql: str, params: list) -> dict:
    _, db = _store(projects, slug)
    with db as s:
        return s.one(sql, params) or {}


def page_is_closed(page, closed: bool) -> None:
    """The page behind a dialog is closed to the keyboard (`inert`) while it is open, and open again once it is gone."""
    inert = page.evaluate("document.getElementById('root').inert")
    if inert != closed:
        raise Problem(f"the page is {'closed' if inert else 'open'} to the keyboard while the dialog is {'gone' if not closed else 'open'}")


def help_box(page, base: str, slug: str, projects: Path) -> None:
    page.goto(f"{base}/app/projects/{slug}")
    page.wait_for_load_state("networkidle")
    project, db = _store(projects, slug)
    with db as s:
        aid = app.add_assist(project, s, "navigate")
    dock = page.get_by_role("complementary", name="AgentQA needs you")
    expect(dock).to_be_visible(timeout=DOCK_MS)
    expect(page).to_have_title("(!) AgentQA needs you", timeout=DOCK_MS)
    opener = dock.get_by_role("button", name="Open")
    opener.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    page_is_closed(page, True)
    # A press in the answer box released on the backdrop is a drag, not a click on it: the dialog and the text stay.
    answer = dialog.get_by_role("textbox", name="Your answer")
    answer.fill(DRAFT)
    where = answer.bounding_box()
    page.mouse.move(where["x"] + 8, where["y"] + where["height"] / 2)
    page.mouse.down()
    page.mouse.move(3, 3, steps=5)
    page.mouse.up()
    expect(dialog).to_be_visible()
    expect(answer).to_have_value(DRAFT)
    # Minimising opens the page again first, then gives the focus back to the button that opened the dialog.
    dialog.get_by_role("button", name="Minimise").click()
    expect(dialog).to_be_hidden()
    page_is_closed(page, False)
    expect(opener).to_be_focused()
    opener.click()
    write_ok(page, f"/assist/{aid}/answer", lambda: dialog.get_by_role("button", name="Citizen Login", exact=True).click())
    expect(dock).to_be_hidden(timeout=WAIT_MS)
    page_is_closed(page, False)
    expect(page.locator("h1").first).to_be_focused(timeout=WAIT_MS)            # nothing left to open: the page's heading
    row = _row(projects, slug, "SELECT status, answer FROM assist WHERE id=?", [aid])
    if row.get("status") != "answered" or (row.get("answer") or {}).get("option") != 0:
        raise Problem(f"the answer was not stored as choice 1: {row}")


def dock_clearance(page, base: str, slug: str, projects: Path) -> None:
    """On a phone the dock is a bar across the bottom: the end of the page scrolls clear of it, by the dock's own height."""
    project, db = _store(projects, slug)
    with db as s:
        aid = app.add_assist(project, s, "navigate")
    page.set_viewport_size({"width": PHONE["width"], "height": PHONE["height"]})
    try:
        page.goto(f"{base}/app/projects/{slug}")
        expect(page.get_by_role("complementary", name="AgentQA needs you")).to_be_visible(timeout=WAIT_MS)
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(STEP_MS)
        measured = page.evaluate(CLEARANCE_JS)
        if measured["gap"] < 0:
            raise Problem(f"the end of the page is hidden under the dock by {-measured['gap']:.0f}px")
        if abs(measured["var"] - measured["dock"]) > 1:
            raise Problem(f"--dock-h is {measured['var']}px but the dock is {measured['dock']}px high")
    finally:
        page.set_viewport_size({"width": 1440, "height": 900})
        page.request.post(f"{base}/api/v1/projects/{slug}/assist/{aid}/answer", headers=app.CSRF, data={"skip": True})


def act_as_agent(projects: Path, slug: str, aid: int) -> tuple[list[dict], bytes]:
    """What the agent does at its next half second: run the queued commands with the engine's own loop."""
    sys.path.insert(0, str(app.BACKEND / "tests"))
    from agentqa import assist
    from assist_fakes import FakePage, file_bytes
    project, db = _store(projects, slug)
    with db as s:
        detail = s.one("SELECT detail FROM assist WHERE id=?", [aid])["detail"]
        assist._run_commands(s, FakePage(focus="password"), aid, detail, project, "explorer", "citizen")
        cmds = s.all("SELECT cmd, status FROM assist_cmds WHERE assist_id=? ORDER BY id", [aid])
    return cmds, file_bytes(project.db_path)


def _queued(projects: Path, slug: str, aid: int) -> list[dict]:
    _, db = _store(projects, slug)
    with db as s:
        return [r["cmd"] for r in s.all("SELECT cmd FROM assist_cmds WHERE assist_id=? ORDER BY id", [aid])]


def click_near_the_corner(page, dialog, projects: Path, slug: str, aid: int) -> None:
    """A click near the picture's far corner, where a click measured on the frame around it would be off by most: it must
    land where the same share of the picture's own box lands in the agent's browser (to the pixel, where the pointer really was)."""
    shot = dialog.get_by_role("button", name=re.compile("^Click on the screen"))
    picture, frame = shot.locator("img").bounding_box(), shot.bounding_box()
    page.evaluate(WATCH_CLICK_JS)
    at = {"x": picture["x"] - frame["x"] + picture["width"] * CORNER, "y": picture["y"] - frame["y"] + picture["height"] * CORNER}
    write_ok(page, "/commands", lambda: shot.click(position=at))
    landed = page.evaluate("window.__click")
    queued = _queued(projects, slug, aid)[-1]
    want = [min(round((landed[0] - picture["x"]) / picture["width"] * SCREEN[0]), SCREEN[0] - 1),
            min(round((landed[1] - picture["y"]) / picture["height"] * SCREEN[1]), SCREEN[1] - 1)]
    if abs(queued["x"] - want[0]) > EXACT_PX or abs(queued["y"] - want[1]) > EXACT_PX:
        raise Problem(f"a click at {CORNER:.0%} of the picture was queued at ({queued['x']}, {queued['y']}), not ({want[0]}, {want[1]})")


def take_over(page, base: str, slug: str, projects: Path) -> None:
    project, db = _store(projects, slug)
    with db as s:
        aid = app.add_assist(project, s, "takeover", mode="takeover", log=[],
                             fields=[{"label": "Password", "type": "password", "x": 640, "y": 360, "filled": False}])
    page.goto(f"{base}/app/projects/{slug}")
    page.get_by_role("complementary", name="AgentQA needs you").get_by_role("button", name="Take over").click()
    dialog = page.get_by_role("dialog", name=re.compile("You have the explorer's browser"))
    typing = dialog.get_by_label("Type into the selected box")
    expect(typing).to_have_attribute("type", "password")                 # no box chosen yet: what is typed stays hidden
    shot = dialog.get_by_role("button", name=re.compile("^Click on the screen"))
    box = shot.bounding_box()
    write_ok(page, "/commands", lambda: shot.click(position={"x": box["width"] / 2, "y": box["height"] / 2}))
    click = _queued(projects, slug, aid)[0]
    if abs(click["x"] - 640) > TOLERANCE_PX or abs(click["y"] - 400) > TOLERANCE_PX:
        raise Problem(f"a click in the middle of the screenshot was queued at ({click['x']}, {click['y']}), not about (640, 400)")
    expect(dialog.get_by_role("status", name="Take-over news")).to_contain_text("Sent: click at")
    click_near_the_corner(page, dialog, projects, slug, aid)
    write_ok(page, "/commands", lambda: dialog.get_by_role("button", name="Box on the screen: Password").click())
    typing.fill(MARKER)
    write_ok(page, "/commands", lambda: dialog.get_by_role("button", name="Type it").click())
    typed = _queued(projects, slug, aid)[-1]
    if typed != {"kind": "type", "text": MARKER, "secret": True, "replace": False}:
        raise Problem(f"typing into the password box queued {typed}")
    cmds, data = act_as_agent(projects, slug, aid)
    if cmds[-1]["cmd"] != {"kind": "type", "chars": len(MARKER), "secret": True, "replace": False} or MARKER.encode() in data:
        raise Problem(f"after the agent typed it, the text is still readable: {cmds[-1]}")
    write_ok(page, f"/assist/{aid}/answer", lambda: dialog.get_by_role("button", name="Continue: I'm done").click())
    if _row(projects, slug, "SELECT status FROM assist WHERE id=?", [aid]).get("status") != "answered":
        raise Problem("Continue did not hand the browser back")
    expect(page.locator("h1").first).to_be_focused(timeout=WAIT_MS)      # the dialog is gone: the focus is on the page's heading


def pause_resume(page, base: str, slug: str, projects: Path) -> None:
    from agentqa.store import now
    project, db = _store(projects, slug)
    with db as s:
        job = s.insert("jobs", {"stage": "pipeline", "status": "running", "started_at": now(), "log_path": "", "pid": os.getpid()})
        aid = app.add_assist(project, s, "navigate")                     # the dock, with its Pause button, shows
    try:
        page.goto(f"{base}/app/projects/{slug}")
        dock = page.get_by_role("complementary", name="AgentQA needs you")
        write_ok(page, "/pause", lambda: dock.get_by_role("button", name="Pause and take over").click())
        resume = dock.get_by_role("button", name="Paused: resume all")
        expect(resume).to_be_visible(timeout=WAIT_MS)
        if not (project.state / "pause.flag").is_file():
            raise Problem("Pause wrote no pause flag")
        write_ok(page, "/resume", lambda: resume.click())
        if (project.state / "pause.flag").is_file():
            raise Problem("Resume left the pause flag")
    finally:
        with _store(projects, slug)[1] as s:
            s.update("jobs", "id", job, {"status": "done"})
        page.request.post(f"{base}/api/v1/projects/{slug}/assist/{aid}/answer", headers=app.CSRF, data={"skip": True})


def visual_review(page, base: str, slug: str) -> None:
    page.goto(f"{base}/app/projects/{slug}/visual")
    cards = page.locator("article.visual-card")
    expect(cards).to_have_count(2, timeout=WAIT_MS)
    cards.first.get_by_role("button", name=re.compile("^Approve as the new baseline")).click()
    cards.first.get_by_role("textbox", name=re.compile("Why")).fill(WHY["visual"])
    write_ok(page, "/visual/", lambda: cards.first.get_by_role("button", name="Keep the new look").click())
    expect(cards).to_have_count(1, timeout=WAIT_MS)
    cards.first.get_by_role("button", name=re.compile("^Report as a defect")).click()
    write_ok(page, "/visual/", lambda: cards.first.get_by_role("button", name="Report it").click())
    expect(cards).to_have_count(0, timeout=WAIT_MS)


def heals(page, base: str, slug: str, ids: list[int]) -> None:
    page.goto(f"{base}/app/projects/{slug}/heals")
    approve, reject = ids
    write_ok(page, f"/heals/{approve}", lambda: page.get_by_role("button", name=f"Approve the fix {approve}", exact=True).click())
    page.get_by_role("button", name=f"Reject fix {reject}").click()
    page.get_by_role("textbox", name=re.compile("Why")).fill(WHY["heal"])
    write_ok(page, f"/heals/{reject}", lambda: page.get_by_role("button", name="Reject the fix").click())


def change_log(page, base: str, slug: str) -> list[str]:
    rows = [r for r in page.request.get(f"{base}/api/v1/projects/{slug}/changes?limit=200").json()["data"]["items"] if r["by"] == WHO]
    def has(obj: str, starts: str, why: str = "") -> bool:
        return any(r["object"] == obj and r["change"].startswith(starts) and (not why or r["why"] == why) for r in rows)
    expected = {
        "the help box's answer": has("assist", "answered the explorer's navigate question: choice 1"),
        "the take-over": has("assist", "took over the explorer's browser as citizen"),
        "the hand-back": has("assist", "handed back the explorer's browser"),
        "the pause": has("run", "paused every agent"), "the resume": has("run", "resumed"),
        "the new baseline with its reason": has("visual", "approved as the new baseline", WHY["visual"]),
        "the visual defect": has("visual", "reported as DEF-"),
        "the approved fix": has("case", "approved locator fix"),
        "the rejected fix with its reason": has("case", "rejected workflow fix", WHY["heal"]),
    }
    return [f"change log: no {name} by {WHO}" for name, ok in expected.items() if not ok]


def run(page, base: str, projects: Path, slug: str) -> list[str]:
    made = app.seed_review(projects, slug)
    problems = []
    steps = [("help box", lambda: help_box(page, base, slug, projects)), ("dock clearance", lambda: dock_clearance(page, base, slug, projects)),
             ("take-over", lambda: take_over(page, base, slug, projects)),
             ("pause", lambda: pause_resume(page, base, slug, projects)), ("visual review", lambda: visual_review(page, base, slug)),
             ("heals", lambda: heals(page, base, slug, made["heals"][:2]))]
    for name, step in steps:
        try:
            step()
        except (Problem, PlaywrightError, AssertionError) as e:
            problems.append(f"{name}: {' | '.join(str(e).splitlines()[:4])}")
    return problems + change_log(page, base, slug)
