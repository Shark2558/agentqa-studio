"""Measure the real React app the way render_mock.py measures the mock — against a throwaway server with a throwaway
owner, so the owner's own sign-in is never read (M1.2-UI; `make ui-check`, needs `make web-build` first).

    python frontend/design-system/check_app.py

Starts `python -m agentqa ui` on a free port with generated AGENTQA_OWNER_* / AGENTQA_SECRET_KEY environment
variables (a real variable beats backend/.env), signs in, creates the demo project through the API, then visits
Sign in, Projects, the project page, Requirements, the wizard, Live View (no run yet) and the Live picker at
320 / 375 / 768 / 1024 / 1440 px in light (and 375 / 1440 in dark) and asserts:
  (a) no horizontal overflow;             (b) every field and button sits inside its card / form / section;
  (c) under 760 px: the menu button shows, the sidebar does not, the drawer opens with Live View, Escape closes it
      and focus returns to the button;    (d) nav links and icon buttons are at least 44 x 44;
  (e) the computed font is IBM Plex Sans; (f) data-accent="teal" changes the primary button's colour.
Writes docs/design/m1-2ui-app-<page>-<theme>-<width>.png for 375 and 1440. Exit 1 on any problem.
"""
from __future__ import annotations

import os
import secrets
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
PREFIX = "m1-2ui-app"
WIDTHS = (320, 375, 768, 1024, 1440)
SHOT_WIDTHS = (375, 1440)
DARK_WIDTHS = (375, 1440)
PHONE_MAX = 759
EMAIL = "ui-check@example.com"
PASSWORD = secrets.token_urlsafe(16)
CSRF = {"X-Requested-With": "AgentQA"}
STARTUP_S = 60
PAUSE_S = 0.4                 # stays well under the API's 240 requests per minute
TOLERANCE = 0.5
FIELDS = "input:not([type=radio],[type=checkbox]), select, textarea, .btn"
CONTAINERS = ".card, .panel, .topbar, .topnav, .side, .drawer, .next, form, section"
TARGETS = ".nav a, .icon-btn"
MIN_TARGET = 44

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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(projects: Path) -> tuple[subprocess.Popen, str]:
    sys.path.insert(0, str(BACKEND))
    from agentqa.api.auth import hash_password
    port = free_port()
    env = {**os.environ, "AGENTQA_OWNER_EMAIL": EMAIL, "AGENTQA_OWNER_PASSWORD_HASH": hash_password(PASSWORD),
           "AGENTQA_SECRET_KEY": secrets.token_urlsafe(48)}
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
    r = context.request.post(f"{base}/api/v1/projects/demo", headers=CSRF)
    slug = r.json()["data"]["slug"]
    page.close()
    return slug


def pages_for(slug: str) -> list[tuple[str, str]]:
    return [("projects", "/app/"), ("project", f"/app/projects/{slug}"), ("requirements", f"/app/projects/{slug}/requirements"),
            ("wizard", "/app/projects/new"), ("live", f"/app/projects/{slug}/live"), ("live-picker", "/app/live")]


def measure(page, label: str, width: int) -> list[str]:
    problems = []
    if page.evaluate("document.documentElement.scrollWidth") > width:
        problems.append(f"{label}: horizontal overflow at {width}px")
    problems += [f"{label} at {width}px: {p}" for p in page.evaluate(_INSIDE_JS, {"fields": FIELDS, "containers": CONTAINERS, "tol": TOLERANCE})]
    problems += [f"{label} at {width}px: target too small: {t}" for t in page.evaluate(_TARGET_JS, {"sel": TARGETS, "min": MIN_TARGET})]
    return problems


def check_drawer(page, label: str) -> list[str]:
    problems = []
    menu = page.get_by_role("button", name="Menu")
    if not menu.is_visible() or page.locator(".side").is_visible():
        return [f"{label}: on a phone the menu button must show and the sidebar must not"]
    menu.click()
    drawer = page.get_by_role("dialog", name="Menu")
    if not drawer.is_visible() or not drawer.get_by_role("link", name="Live View").is_visible():
        problems.append(f"{label}: the drawer did not open with Live View")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    if drawer.is_visible():
        problems.append(f"{label}: Escape did not close the drawer")
    if page.evaluate("document.activeElement && document.activeElement.getAttribute('aria-label')") != "Menu":
        problems.append(f"{label}: focus did not return to the menu button")
    return problems


def check_font_and_accent(page, label: str) -> list[str]:
    problems = []
    if "IBM Plex Sans" not in page.evaluate("getComputedStyle(document.body).fontFamily"):
        problems.append(f"{label}: body is not IBM Plex Sans")
    before = page.evaluate("getComputedStyle(document.querySelector('.btn.primary')).backgroundColor")
    page.evaluate("document.documentElement.setAttribute('data-accent', 'teal')")
    page.wait_for_timeout(400)                       # the button's 150 ms colour transition must finish first
    after = page.evaluate("getComputedStyle(document.querySelector('.btn.primary')).backgroundColor")
    page.evaluate("document.documentElement.removeAttribute('data-accent')")
    if before == after:
        problems.append(f"{label}: data-accent=teal did not change the primary button")
    return problems


def run_pages(browser, base: str, slug: str, theme: str, widths: tuple[int, ...]) -> list[str]:
    problems = []
    for width in widths:
        context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=theme)
        page = context.new_page()
        signed_in = False
        for name, path in [("sign-in", "/app/sign-in")] + pages_for(slug):
            if name != "sign-in" and not signed_in:
                sign_in(context, base)
                signed_in = True
            page.goto(base + path)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(200)
            label = f"{name} ({theme})"
            problems += measure(page, label, width)
            if name == "projects" and width <= PHONE_MAX:
                problems += check_drawer(page, label)
            if name == "projects" and width == 1440:
                problems += check_font_and_accent(page, label)
            if width in SHOT_WIDTHS:
                page.screenshot(path=str(OUT / f"{PREFIX}-{name}-{theme}-{width}.png"), full_page=(width < 760))
            time.sleep(PAUSE_S)
        context.close()
    return problems


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        print("frontend/dist is missing: run `make web-build` first")
        return 1
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:      # Windows may still hold the test db for a moment
        proc, base = start_server(Path(tmp) / "projects")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                with browser.new_context() as context:
                    slug = sign_in(context, base)
                problems = run_pages(browser, base, slug, "light", WIDTHS) + run_pages(browser, base, slug, "dark", DARK_WIDTHS)
                browser.close()
        finally:
            proc.kill()
            proc.wait(timeout=10)
    for png in sorted(OUT.glob(f"{PREFIX}-*.png")):
        print("wrote", png.relative_to(ROOT))
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))
        return 1
    print(f"\nthe app passes at {', '.join(map(str, WIDTHS))} px in light and dark: no overflow, fields inside their cards, drawer, targets, font, accent OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
