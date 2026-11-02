"""Render the design mock to reference PNGs and fail on horizontal overflow — the repeatable half of the M0.4
"render it and look at it" step.

    python frontend/design-system/render_mock.py            (needs the backend venv: Playwright + Chromium)

Writes docs/design/m0-4-<screen>-<theme>-<desktop|phone>.png, docs/design/m0-4-font-<plex|jakarta>.png, and asserts
`scrollWidth == innerWidth` for both screens at 320 / 375 / 768 / 1024 / 1440 px. Exit 1 on any overflow, or when
the font switch does not change the computed font (the switch was once inert and nobody noticed).
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
MOCK = (ROOT / "frontend" / "design-system" / "mock" / "index.html").as_uri()
OUT = ROOT / "docs" / "design"
BREAKPOINTS = (320, 375, 768, 1024, 1440)
RENDERS = ((1440, 900, "desktop"), (375, 812, "phone"))
SCREENS = ("dash", "live")
THEMES = ("light", "dark")
FONTS = {"plex": "IBM Plex Sans", "jakarta": "Plus Jakarta Sans"}
SETTLE_MS = 150


def _show(page, screen: str, theme: str) -> None:
    page.click(f'[data-theme-pick="{theme}"]')
    page.click(f'[data-screen="{screen}"]')
    page.wait_for_timeout(SETTLE_MS)


def check_overflow(browser) -> list[str]:
    problems = []
    for width in BREAKPOINTS:
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(MOCK)
        page.wait_for_load_state("networkidle")
        for screen in SCREENS:
            _show(page, screen, "light")
            content = page.evaluate("document.documentElement.scrollWidth")
            if content > width:
                problems.append(f"{screen} overflows at {width}px: content is {content}px wide")
        page.close()
    return problems


def check_font_switch(browser) -> list[str]:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(MOCK)
    page.wait_for_load_state("networkidle")
    problems = []
    for key, family in FONTS.items():
        page.click(f'[data-font-pick="{key}"]')
        page.wait_for_timeout(SETTLE_MS)
        computed = page.evaluate("getComputedStyle(document.querySelector('h1')).fontFamily")
        if family not in computed:
            problems.append(f"font switch '{key}' did not apply: h1 uses {computed}")
        page.screenshot(path=str(OUT / f"m0-4-font-{key}.png"), clip={"x": 0, "y": 0, "width": 1440, "height": 560})
    page.close()
    return problems


def render(browser) -> None:
    for width, height, tag in RENDERS:
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(MOCK)
        page.wait_for_load_state("networkidle")
        for theme in THEMES:
            for screen in SCREENS:
                _show(page, screen, theme)
                page.screenshot(path=str(OUT / f"m0-4-{screen}-{theme}-{tag}.png"), full_page=(tag == "phone"))
        page.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        problems = check_overflow(browser) + check_font_switch(browser)
        render(browser)
        browser.close()
    for png in sorted(OUT.glob("m0-4-*.png")):
        print("wrote", png.relative_to(ROOT))
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))
        return 1
    print(f"\nno overflow at {', '.join(map(str, BREAKPOINTS))} px; font switch works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
