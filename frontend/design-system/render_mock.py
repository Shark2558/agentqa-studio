"""Render the design mock to reference PNGs and fail on layout defects — the repeatable half of the "render it and
look at it" step (M0.4, extended for themes, accents, the phone drawer and reduced motion in M1.2-UI).

    python frontend/design-system/render_mock.py            (needs the backend venv: Playwright + Chromium)

Writes docs/design/m1-2ui-<screen>-<theme>-<accent>-<desktop|phone>.png and m1-2ui-drawer-phone.png, and asserts:
  - scrollWidth == innerWidth for both screens at 320 / 375 / 768 / 1024 / 1440 px (no horizontal overflow);
  - every visible input, select and button sits inside its nearest card / section (the M0.4 fields crossed theirs);
  - under 760 px the menu button opens the drawer with the nav, Escape closes it and focus returns;
  - picking an accent changes the primary button's colour; picking Dark changes the page background;
  - under prefers-reduced-motion the running card's pulse ring and the frame's scan line do not animate.
Exit 1 on any problem. The m0-4-*.png renders are kept as the record of the look this replaces.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
MOCK = (ROOT / "frontend" / "design-system" / "mock" / "index.html").as_uri()
OUT = ROOT / "docs" / "design"
PREFIX = "m1-2ui"
BREAKPOINTS = (320, 375, 768, 1024, 1440)
RENDERS = ((1440, 900, "desktop"), (375, 812, "phone"))
SCREENS = ("dash", "live")
THEMES = ("light", "dark")
ACCENTS = ("blue", "teal")
SETTLE_MS = 250
TOLERANCE = 0.5
FIELDS = "input:not([type=radio]), select, textarea, .btn"
CONTAINERS = ".card, .panel, .topbar, .topnav, .side, .drawer, .next"

_INSIDE_JS = """({fields, containers, tol}) => {
  const out = [];
  for (const el of document.querySelectorAll(fields)) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.closest('[hidden]')) continue;
    const box = el.parentElement.closest(containers);
    if (!box) continue;
    const b = box.getBoundingClientRect();
    if (r.left < b.left - tol || r.right > b.right + tol)
      out.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''} crosses its ${box.className.split(' ')[0]} by ${Math.max(b.left - r.left, r.right - b.right).toFixed(1)}px`);
  }
  return out;
}"""


def _open_page(browser, width: int, height: int = 900, **context):
    ctx = browser.new_context(viewport={"width": width, "height": height}, **context)
    page = ctx.new_page()
    page.goto(MOCK)
    page.wait_for_load_state("networkidle")
    return page


def _pick(page, theme: str, accent: str, screen: str) -> None:
    """Choose through the real Appearance menu (whichever copy is visible), then close it."""
    page.locator(".appear-btn:visible").first.click()
    page.locator(f'[data-theme-pick="{theme}"]:visible').first.check(force=True)
    page.locator(f'[data-accent-pick="{accent}"]:visible').first.check(force=True)
    page.keyboard.press("Escape")
    page.click(f'[data-screen="{screen}"]')
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(SETTLE_MS)


def check_overflow(browser) -> list[str]:
    problems = []
    for width in BREAKPOINTS:
        page = _open_page(browser, width)
        for screen in SCREENS:
            _pick(page, "light", "blue", screen)
            content = page.evaluate("document.documentElement.scrollWidth")
            if content > width:
                problems.append(f"{screen} overflows at {width}px: content is {content}px wide")
            inside = page.evaluate(_INSIDE_JS, {"fields": FIELDS, "containers": CONTAINERS, "tol": TOLERANCE})
            problems += [f"{screen} at {width}px: {p}" for p in inside]
        page.context.close()
    return problems


def check_drawer(browser) -> list[str]:
    page = _open_page(browser, 375, 812)
    problems = []
    if not page.locator(".menu-btn").is_visible() or page.locator(".side").is_visible():
        problems.append("phone: the menu button is not shown or the sidebar is")
    page.click(".menu-btn")
    page.wait_for_timeout(SETTLE_MS)
    if not page.locator("#drawer[open]").count() or not page.locator("#drawer a", has_text="Live View").is_visible():
        problems.append("phone: the drawer did not open with the Live View link")
    page.screenshot(path=str(OUT / f"{PREFIX}-drawer-phone.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(SETTLE_MS)
    if page.locator("#drawer[open]").count():
        problems.append("phone: Escape did not close the drawer")
    if page.evaluate("document.activeElement && document.activeElement.className") != "icon-btn menu-btn":
        problems.append("phone: focus did not return to the menu button after the drawer closed")
    page.context.close()
    return problems


_PANEL_JS = """({tol}) => {
  const side = document.querySelector('.side').getBoundingClientRect();
  return [...document.querySelectorAll('.side .panel, .side .panel label > span')].map(el => el.getBoundingClientRect())
    .filter(r => r.left < side.left - tol || r.right > side.right + tol || r.top < -tol || r.bottom > innerHeight + tol)
    .map(r => `a panel part at ${r.left.toFixed(0)}..${r.right.toFixed(0)} leaves the sidebar ${side.left.toFixed(0)}..${side.right.toFixed(0)}`);
}"""


def check_switches(browser) -> list[str]:
    page = _open_page(browser, 1440)
    problems = []
    page.locator(".side .appear-btn").click()                       # the open panel must fit inside the (scrolling) sidebar
    page.wait_for_timeout(SETTLE_MS)
    problems += page.evaluate(_PANEL_JS, {"tol": TOLERANCE})
    page.keyboard.press("Escape")
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    btn = page.evaluate("getComputedStyle(document.querySelector('.btn.primary')).backgroundColor")
    _pick(page, "light", "teal", "dash")
    if page.evaluate("getComputedStyle(document.querySelector('.btn.primary')).backgroundColor") == btn:
        problems.append("picking the Teal accent did not change the primary button")
    _pick(page, "dark", "teal", "dash")
    if page.evaluate("getComputedStyle(document.body).backgroundColor") == bg:
        problems.append("picking Dark did not change the page background")
    page.context.close()
    return problems


def check_reduced_motion(browser) -> list[str]:
    page = _open_page(browser, 1440, reduced_motion="reduce")
    _pick(page, "light", "blue", "live")
    problems = []
    for sel, what in ((".agent.running", "running card pulse ring"), (".frame.running", "browser frame scan line")):
        name = page.evaluate(f"getComputedStyle(document.querySelector('#screen-live {sel}'), '::after').animationName")
        if name != "none":
            problems.append(f"reduced motion: the {what} still animates ({name})")
    page.context.close()
    return problems


def render(browser) -> None:
    for width, height, tag in RENDERS:
        page = _open_page(browser, width, height)
        for theme in THEMES:
            for accent in ACCENTS:
                for screen in SCREENS:
                    _pick(page, theme, accent, screen)
                    page.screenshot(path=str(OUT / f"{PREFIX}-{screen}-{theme}-{accent}-{tag}.png"), full_page=(tag == "phone"))
        page.context.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        problems = check_overflow(browser) + check_drawer(browser) + check_switches(browser) + check_reduced_motion(browser)
        render(browser)
        browser.close()
    for png in sorted(OUT.glob(f"{PREFIX}-*.png")):
        print("wrote", png.relative_to(ROOT))
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))
        return 1
    print(f"\nno overflow at {', '.join(map(str, BREAKPOINTS))} px; fields inside their cards; drawer, theme, accent and reduced motion OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
