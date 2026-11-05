"""Measure the real React app the way render_mock.py measures the mock — against a throwaway server with a throwaway
owner, so the owner's own sign-in is never read (M1.2-UI; `make ui-check`, needs `make web-build` first).

    python frontend/design-system/check_app.py [--shots]

Starts `python -m agentqa ui` on a free port with generated AGENTQA_OWNER_* / AGENTQA_SECRET_KEY environment
variables (a real variable beats backend/.env), an AGENTQA_HOME and AGENTQA_VAULT_KEY of its own in the temporary
folder and no *_API_KEY variable (so the owner's real key store is never read), signs in, creates the demo project through the API, then visits
Sign in, Projects, the project page, Requirements, the six gate pages (Questions, Test plan, Defects, Change log, Visual
review, Heals; the demo project holds the gates fixture, M1.4, plus two changed screens, three fixes and a question
waiting in the help box, whose dock and dialog are measured on the project page), the wizard, Live View (no run yet), the Live picker and Live View on
the recorded fixture run (a second project holding it as a finished session, M1.3) at
320 / 375 / 768 / 1024 / 1200 / 1440 px in light (and 375 / 1440 in dark) and asserts:
  (a) no horizontal overflow and no overlap in the top bar;   (b) every field and button sits inside its card / form / section;
  (c) under 760 px: the menu button shows, the sidebar does not, the drawer opens with Live View and Sign out, its
      links and buttons are 44 px targets, Escape closes it and focus returns to the button;
  (d) nav links, icon buttons, the Appearance button, theme choices and stepper buttons are at least 44 x 44;
  (e) IBM Plex Sans is loaded (document.fonts), the Appearance button exists, and opening it in the sidebar shows a
      panel whose every control sits inside the sidebar and the viewport;   (f) data-accent="teal" recolours the primary button;
  (g) on the recorded run, Live View's middle column exists and is at least 360 px wide whenever it shares its row.
With --shots, writes docs/design/m1-2ui-app-<page>-<theme>-<width>.png for 375 and 1440. Exit 1 on any problem.
"""
from __future__ import annotations

import base64
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OUT = ROOT / "docs" / "design"
FIXTURE = BACKEND / "tests" / "fixtures" / "recordings" / "cli-fixture-pipeline"
LIVE_RUN = "cli-20261103-133600-pipeline"     # shaped like a real command-line run, so it gets a real label
PREFIX = "m1-2ui-app"
WIDTHS = (320, 375, 768, 1024, 1200, 1440)
SHOT_WIDTHS = (375, 1440)
DARK_WIDTHS = (375, 1440)
PHONE_MAX = 759
EMAIL = "ui-check@example.com"
PASSWORD = secrets.token_urlsafe(16)
SECRET = secrets.token_urlsafe(48)          # the throwaway server's session key: check_gates.py mints a Viewer pass with it
CSRF = {"X-Requested-With": "AgentQA"}
STARTUP_S = 60
AI_FIRST_CALL_MS = 180_000    # importing the AI gateway takes about 25 s on a busy machine, longer than a request's usual 30 s
PAUSE_S = 0.4                 # stays well under the API's 240 requests per minute
SETTLE_MS = 400               # longer than any transition in tokens.css
TOLERANCE = 0.5
FIELDS = "input:not([type=radio],[type=checkbox]), select, textarea, .btn"
CONTAINERS = ".card, .panel, .topbar, .topnav, .side, .drawer, form, section, .assist-panel, .needs-dock"
TARGETS = ".nav a, .icon-btn, .appear-btn, .modes label > span, .swatches > label > span, .steps .step-link, .timeline-steps .step, .tabs [role=tab]"
DRAWER_TARGETS = ".drawer a, .drawer button"
MIN_TARGET = 44
MIN_FOCUS = 360               # "what it is doing" must stay readable whenever it shares its row (M1.3 Phase C: 186 px at 1149)

_INSIDE_JS = """({fields, containers, tol}) => {
  const out = [];
  for (const el of document.querySelectorAll(fields)) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.closest('[hidden]')) continue;
    const box = el.parentElement.closest(containers);
    if (!box) continue;
    const b = box.getBoundingClientRect();
    if (r.left < b.left - tol || r.right > b.right + tol)
      out.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''} crosses its ${box.className.split(' ')[0] || box.tagName.toLowerCase()} by ${Math.max(b.left - r.left, r.right - b.right).toFixed(1)}px`);
  }
  return out;
}"""
_TARGET_JS = """({sel, min}) => [...document.querySelectorAll(sel)].filter(el => el.getBoundingClientRect().width > 0)
  .map(el => ({name: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30), w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height}))
  .filter(t => t.w < min || t.h < min).map(t => `${t.name}: ${t.w.toFixed(0)}x${t.h.toFixed(0)}`)"""
_OVERLAP_JS = """() => {
  const items = [...document.querySelectorAll('.topnav > *')].map(el => el.getBoundingClientRect()).filter(r => r.width > 0);
  const out = [];
  for (let i = 1; i < items.length; i++) if (items[i].left < items[i - 1].right - 0.5) out.push(`top bar item ${i} overlaps the one before it by ${(items[i - 1].right - items[i].left).toFixed(0)}px`);
  return out;
}"""
_FOCUS_JS = """({min}) => {
  const focus = document.querySelector('.g-live > .card.focus'), grid = document.querySelector('.g-live');
  if (!focus || !grid) return [];
  const w = focus.getBoundingClientRect().width, row = grid.getBoundingClientRect().width;
  return w < min && w < row - 1 ? [`the Live View's middle column is ${w.toFixed(0)}px wide beside other columns (at least ${min})`] : [];
}"""
_PANEL_JS = """({tol}) => {
  const side = document.querySelector('.side').getBoundingClientRect();
  const out = [];
  for (const el of document.querySelectorAll('.side .panel, .side .panel label > span')) {
    const r = el.getBoundingClientRect();
    if (r.left < side.left - tol || r.right > side.right + tol || r.left < -tol || r.right > innerWidth + tol || r.top < -tol || r.bottom > innerHeight + tol)
      out.push(`${el.className || el.tagName.toLowerCase()} leaves the sidebar or the viewport (${r.left.toFixed(0)}..${r.right.toFixed(0)}, ${r.top.toFixed(0)}..${r.bottom.toFixed(0)})`);
  }
  return out;
}"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


OWN_VARIABLES = {"AGENTQA_HOME", "AGENTQA_VAULT_KEY", "AGENTQA_OWNER_EMAIL", "AGENTQA_OWNER_PASSWORD_HASH", "AGENTQA_SECRET_KEY"}


def server_env(home: Path, source: dict[str, str] | None = None) -> dict[str, str]:
    """The throwaway server's environment: the machine's, without any *_API_KEY and without the owner's own AgentQA
    variables, plus a home of its own and a vault key made for this server. So the AI page reads an empty key store in
    the temporary folder, never the owner's real one in %APPDATA%\\AgentQA, and `--shots` cannot write a masked real key
    into a tracked docs/design picture."""
    sys.path.insert(0, str(BACKEND))
    from agentqa.api.auth import hash_password
    kept = {k: v for k, v in (os.environ if source is None else source).items()
            if not k.upper().endswith("_API_KEY") and k.upper() not in OWN_VARIABLES}
    return {**kept, "AGENTQA_OWNER_EMAIL": EMAIL, "AGENTQA_OWNER_PASSWORD_HASH": hash_password(PASSWORD), "AGENTQA_SECRET_KEY": SECRET,
            "AGENTQA_HOME": str(home), "AGENTQA_VAULT_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}


def start_server(projects: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    home = projects.parent / "agentqa-home"
    home.mkdir(parents=True, exist_ok=True)
    env = server_env(home)
    proc = subprocess.Popen([sys.executable, "-m", "agentqa", "ui", "--port", str(port), "--projects-dir", str(projects)],
                            cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(STARTUP_S * 4):
        try:
            with urllib.request.urlopen(f"{base}/api/v1/health", timeout=1):
                return proc, base
        except OSError:
            time.sleep(0.25)
    proc.kill()
    raise SystemExit("the test server did not start")


def sign_in(context, base: str) -> str:
    """Sign in through the real form, create the demo project through the API, return its slug."""
    page = context.new_page()
    page.goto(f"{base}/app/sign-in")
    page.get_by_label("Email").fill(EMAIL)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("heading", name="Projects", exact=True).wait_for()
    keys = context.request.get(f"{base}/api/v1/ai/keys", timeout=AI_FIRST_CALL_MS).json()["data"]    # the first call loads the AI gateway
    if keys:                                      # never run (or write a picture) with the owner's real keys in reach
        raise SystemExit(f"the throwaway server can see {len(keys)} AI key(s): it must start with an empty key store")
    r = context.request.post(f"{base}/api/v1/projects/demo", headers=CSRF)
    slug = r.json()["data"]["slug"]
    page.close()
    return slug


def seed_live_run(context, base: str, projects: Path) -> str:
    """A second project holding the recorded fixture run as a finished command-line session (its marker says it
    ended), so the demo project keeps its "No run yet" Live View; returns that project's slug."""
    from agentqa.orchestrator.live import mark_ended, mark_running
    r = context.request.post(f"{base}/api/v1/projects", headers=CSRF, data={"name": "Recorded run", "url": "http://127.0.0.1:8800"})
    slug = r.json()["data"]["slug"]
    folder = projects / slug / ".agentqa" / "live" / LIVE_RUN
    shutil.copytree(FIXTURE, folder)
    mark_running(folder)
    mark_ended(folder, os.getpid())
    return slug


def seed_gates(projects: Path, slug: str) -> None:
    """The demo project's store filled with the gates fixture (the owner's real No-AI demo at the plan gate, M1.4):
    15 questions, 206 cases, 19 defects with evidence, 35 requirements, so the gate pages are measured full."""
    sys.path.insert(0, str(BACKEND / "tests"))
    from contextlib import closing
    from agentqa.config import Project
    from agentqa.store import Store
    from gates_fixture import load
    project = Project(projects / slug)
    with closing(Store(project.db_path)) as store:
        load(project, store)


REVIEW_RUN = "run-20261105-100000"


def _jpeg(path: Path, size: tuple[int, int] = (1280, 800)) -> None:
    """A screen-sized picture standing in for an agent's screenshot (a JPEG, as the help box's shooter writes)."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, (245, 247, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 72), fill=(30, 64, 175))
    draw.rectangle((540, 330, 740, 390), outline=(30, 64, 175), width=3)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=70)


def seed_review(projects: Path, slug: str, with_assist: bool = False) -> dict:
    """Phase C on top of the gates fixture: two changed screens (their pictures copied from the fixture's baselines), a
    locator fix, a workflow fix and a fix to make by hand; with `with_assist`, a question waiting in the help box with
    its screenshot. Returns the keys and ids made."""
    from contextlib import closing
    from agentqa.config import Project
    from agentqa.store import Store
    project = Project(projects / slug)
    made: dict = {"visual": [], "heals": []}
    with closing(Store(project.db_path)) as store:
        for v in store.all("SELECT key, baseline FROM visual WHERE baseline IS NOT NULL ORDER BY key"):
            base = Path(v["baseline"])
            if not base.is_file() or len(made["visual"]) == 2:
                continue
            run = project.root / "runs" / REVIEW_RUN / "visual"
            run.mkdir(parents=True, exist_ok=True)
            current, diff = run / f"{v['key']}-current.png", run / f"{v['key']}-diff.png"
            shutil.copy(base, current)
            shutil.copy(base, diff)
            store.update("visual", "key", v["key"], {"status": "changed", "diff_ratio": 0.08, "current": str(current), "diff": str(diff),
                                                     "run_id": REVIEW_RUN})
            made["visual"].append(v["key"])
        heal = {"run_id": REVIEW_RUN, "status": "proposed", "created_at": "2026-11-05T10:00:00"}
        made["heals"].append(store.insert("heals", {**heal, "case_id": "TC-0001", "kind": "locator",
                                                    "old": {"field": "mobile", "label": "Mobile", "path": "/apply"},
                                                    "new": {"field": "mobile_no", "label": "Mobile number"},
                                                    "reason": "On /apply, field 'mobile' is gone; 'mobile_no' matches 92%."}))
        made["heals"].append(store.insert("heals", {**heal, "case_id": "TC-0002", "kind": "workflow",
                                                    "old": {"workflow": "WF-01", "step": 2, "key": "click", "value": "text=Verify {app_id}"},
                                                    "new": {"value": "text=Mark verified {app_id}", "offered": "Mark verified"},
                                                    "reason": "Workflow WF-01, step 2: the control 'Verify' is gone."}))
        store.insert("heals", {**heal, "case_id": "TC-0003", "kind": "manual", "old": {"message": "Timeout 30000ms exceeded"}, "new": None,
                               "reason": "Not a missing-locator problem; review this test manually."})
        if with_assist:
            made["assist"] = add_assist(project, store, "navigate")
    return made


def add_assist(project, store, kind: str, **detail) -> int:
    """A question waiting in the help box, with a screenshot on disk under the name the shooter would give it."""
    from agentqa.store import now
    aid = store.insert("assist", {"at": now(), "kind": kind, "role": "citizen", "agent": "explorer", "status": "pending",
                                  "question": "Which button logs me in as a citizen?" if kind != "takeover" else "Log in as citizen for me",
                                  "detail": {}, "answer": None, "answered_at": None})
    _jpeg(project.state / "assist" / f"{aid}-1.jpg")
    base = {"options": ["Citizen Login", "Department Login"] if kind == "navigate" else [], "hint": "", "secret": False,
            "url": "http://127.0.0.1:8800/", "vw": 1280, "vh": 800, "shot": f"{aid}-1.jpg", "shot_v": 1,
            "clickables": [{"text": "Citizen Login", "x": 640, "y": 360}, {"text": "Help", "x": 1200, "y": 36}]}
    store.update("assist", "id", aid, {"detail": {**base, **detail}})
    return aid


def pages_for(slug: str, run_slug: str) -> list[tuple[str, str]]:
    return [("projects", "/app/"), ("project", f"/app/projects/{slug}"), ("requirements", f"/app/projects/{slug}/requirements"),
            ("questions", f"/app/projects/{slug}/questions"), ("plan", f"/app/projects/{slug}/plan"),
            ("defects", f"/app/projects/{slug}/defects"), ("changes", f"/app/projects/{slug}/changes"),
            ("visual", f"/app/projects/{slug}/visual"), ("heals", f"/app/projects/{slug}/heals"),
            ("wizard", "/app/projects/new"), ("live", f"/app/projects/{slug}/live"), ("live-picker", "/app/live"),
            ("live-run", f"/app/projects/{run_slug}/live?session={LIVE_RUN}"), ("ai", f"/app/projects/{slug}/ai")]


def measure(page, label: str, width: int) -> list[str]:
    problems = []
    if page.evaluate("document.documentElement.scrollWidth") > width:
        problems.append(f"{label}: horizontal overflow at {width}px")
    problems += [f"{label} at {width}px: {p}" for p in page.evaluate(_INSIDE_JS, {"fields": FIELDS, "containers": CONTAINERS, "tol": TOLERANCE})]
    problems += [f"{label} at {width}px: target too small: {t}" for t in page.evaluate(_TARGET_JS, {"sel": TARGETS, "min": MIN_TARGET})]
    problems += [f"{label} at {width}px: {p}" for p in page.evaluate(_OVERLAP_JS)]
    problems += [f"{label} at {width}px: {p}" for p in page.evaluate(_FOCUS_JS, {"min": MIN_FOCUS})]
    return problems


def check_drawer(page, label: str) -> list[str]:
    problems = []
    menu = page.get_by_role("button", name="Menu")
    if not menu.is_visible() or page.locator(".side").is_visible():
        return [f"{label}: on a phone the menu button must show and the sidebar must not"]
    menu.click()
    page.wait_for_timeout(SETTLE_MS)
    drawer = page.get_by_role("dialog", name="Menu")
    if not drawer.is_visible() or not drawer.get_by_role("link", name="Live View").is_visible():
        problems.append(f"{label}: the drawer did not open with Live View")
    if not drawer.get_by_role("button", name="Sign out").is_visible():
        problems.append(f"{label}: the drawer has no Sign out")
    problems += [f"{label}: drawer target too small: {t}" for t in page.evaluate(_TARGET_JS, {"sel": DRAWER_TARGETS, "min": MIN_TARGET})]
    page.keyboard.press("Escape")
    page.wait_for_timeout(SETTLE_MS)
    if drawer.is_visible():
        problems.append(f"{label}: Escape did not close the drawer")
    if page.evaluate("document.activeElement && document.activeElement.getAttribute('aria-label')") != "Menu":
        problems.append(f"{label}: focus did not return to the menu button")
    return problems


def check_help_box(page, label: str, width: int) -> list[str]:
    """The waiting question's dock is on the page and in the viewport; its dialog opens on Open, fits the width with its
    fields inside it, and Escape only minimises it (the question stays waiting)."""
    dock = page.get_by_role("complementary", name="AgentQA needs you")
    if not dock.is_visible():
        return [f"{label} at {width}px: the help box's dock is not shown while a question waits"]
    box = dock.bounding_box() or {"x": -1, "width": 0}
    problems = [] if box["x"] >= -TOLERANCE and box["x"] + box["width"] <= width + TOLERANCE else [f"{label} at {width}px: the dock leaves the viewport"]
    if page.title() != "(!) AgentQA needs you":
        problems.append(f"{label} at {width}px: the tab's title is “{page.title()}”")
    dock.get_by_role("button", name="Open").click()
    page.wait_for_timeout(SETTLE_MS)
    dialog = page.get_by_role("dialog")
    if not dialog.is_visible():
        return problems + [f"{label} at {width}px: Open did not open the question"]
    problems += measure(page, f"{label} (help box)", width)
    page.keyboard.press("Escape")
    page.wait_for_timeout(SETTLE_MS)
    if dialog.count() or not dock.is_visible():
        problems.append(f"{label} at {width}px: Escape did not minimise the question back to the dock")
    return problems


def check_desktop_extras(page, label: str) -> list[str]:
    """Font really loaded, the Appearance panel fits its sidebar, the accent recolours the primary button."""
    problems = []
    if not page.evaluate("document.fonts.check('14px \"IBM Plex Sans\"')"):
        problems.append(f"{label}: IBM Plex Sans is not loaded")
    appearance = page.locator(".side .appear-btn")
    if not appearance.is_visible():
        return problems + [f"{label}: no Appearance button in the sidebar"]
    appearance.click()
    page.wait_for_timeout(SETTLE_MS)
    problems += [f"{label}: {p}" for p in page.evaluate(_PANEL_JS, {"tol": TOLERANCE})]
    problems += [f"{label}: Appearance target too small: {t}" for t in page.evaluate(_TARGET_JS, {"sel": ".side .panel label > span", "min": MIN_TARGET})]
    page.keyboard.press("Escape")
    before = page.evaluate("getComputedStyle(document.querySelector('.btn.primary')).backgroundColor")
    page.evaluate("document.documentElement.setAttribute('data-accent', 'teal')")
    page.wait_for_timeout(SETTLE_MS)                       # the button's 150 ms colour transition must finish first
    after = page.evaluate("getComputedStyle(document.querySelector('.btn.primary')).backgroundColor")
    page.evaluate("document.documentElement.removeAttribute('data-accent')")
    if before == after:
        problems.append(f"{label}: data-accent=teal did not change the primary button")
    return problems


def run_pages(browser, base: str, slugs: tuple[str, str], theme: str, widths: tuple[int, ...], shots: bool) -> list[str]:
    problems = []
    for width in widths:
        context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=theme)
        page = context.new_page()
        signed_in = False
        for name, path in [("sign-in", "/app/sign-in")] + pages_for(*slugs):
            if name != "sign-in" and not signed_in:
                sign_in(context, base)
                signed_in = True
            page.goto(base + path)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(200)
            label = f"{name} ({theme})"
            problems += measure(page, label, width)
            if name == "live-run" and page.locator(".g-live > .card.focus").count() != 1:      # the width check needs it
                problems.append(f"{label} at {width}px: no Live View middle column to measure")
            if name == "projects" and width <= PHONE_MAX:
                problems += check_drawer(page, label)
            if name == "project":
                problems += check_help_box(page, label, width)
            if name == "projects" and width == 1440:
                problems += check_desktop_extras(page, label)
            if shots and width in SHOT_WIDTHS:
                page.screenshot(path=str(OUT / f"{PREFIX}-{name}-{theme}-{width}.png"), full_page=(width < 760))
            time.sleep(PAUSE_S)
        context.close()
    return problems


def main(argv: list[str]) -> int:
    shots = "--shots" in argv
    index = ROOT / "frontend" / "dist" / "index.html"
    if not index.is_file():
        print("frontend/dist is missing: run `make web-build` first")
        return 1
    if 'src="/app/theme-boot.js"' not in index.read_text(encoding="utf-8"):
        print("dist/index.html does not load /app/theme-boot.js: the saved theme would flash on reload")
        return 1
    if shots:
        OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:      # Windows may still hold the test db for a moment
        proc, base = start_server(Path(tmp) / "projects")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                with browser.new_context() as context:
                    slugs = (sign_in(context, base), seed_live_run(context, base, Path(tmp) / "projects"))
                seed_gates(Path(tmp) / "projects", slugs[0])
                seed_review(Path(tmp) / "projects", slugs[0], with_assist=True)
                problems = run_pages(browser, base, slugs, "light", WIDTHS, shots) + run_pages(browser, base, slugs, "dark", DARK_WIDTHS, shots)
                browser.close()
        finally:
            proc.kill()
            proc.wait(timeout=10)
    if shots:
        for png in sorted(OUT.glob(f"{PREFIX}-*.png")):
            print("wrote", png.relative_to(ROOT))
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))
        return 1
    print(f"\nthe app passes at {', '.join(map(str, WIDTHS))} px in light and dark: no overflow or overlap, fields inside their cards, "
          "drawer (with Sign out), 44 px targets, loaded font, Appearance panel in place, accent OK, Live View's middle "
          "column readable")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
