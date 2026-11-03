"""Watch a run arrive in the real React app, then check that every way of looking at it ends at the same picture
(M1.3 Phase B; `make live-check`, needs `make web-build` first). Like check_app.py it runs a throwaway server with a
throwaway owner, so the owner's own sign-in is never read.

    python frontend/design-system/check_live.py

Steps: create the demo project; start a new command-line session with a run marker (this process's pid, so it reads
as running); open its Live View; append the recorded fixture run (backend/tests/fixtures/recordings/
cli-fixture-pipeline) in 40 timed chunks; end the run and wait for "finished". Then it asserts:
  (a) the final picture (cards, pipeline and gates, tiles, findings, AI totals) matches live-expected-summary.json;
  (b) the transport was WebSocket;   (c) a reload shows the same picture;
  (d) Replay from the start at Instant ends at the same picture;
  (e) with WebSocket refused before it opens (as a proxy without WebSocket would), the page falls back to SSE
      (data-transport="sse") and shows the same picture. Playwright's route_web_socket opens the page's socket
      before a handler could refuse it, so the refusal is an init script that replaces WebSocket.
Exit 1 on any problem.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_app as app  # noqa: E402  (the throwaway server and owner)

FIXTURE = app.BACKEND / "tests" / "fixtures" / "recordings" / "cli-fixture-pipeline"
SUMMARY = app.ROOT / "frontend" / "src" / "test-fixtures" / "live-expected-summary.json"
SESSION = "cli-20261104-000000-check"
CHUNKS = 40
CHUNK_S = 0.15
WAIT_MS = 60_000
TILE_WORDS = {"passed": "passed", "defect": "failed", "not-run": "not run", "visual": "visual change", "blocked": "blocked"}
REFUSE_WS = """window.WebSocket = class extends EventTarget {
  constructor() { super(); setTimeout(() => this.onclose && this.onclose({ code: 1006 }), 0); }
  close() {}
};"""
_PICTURE_JS = """() => {
  const text = (sel) => [...document.querySelectorAll(sel)].map((el) => el.innerText.replace(/\\s+/g, ' ').trim());
  const meta = document.querySelector('.run-meta')?.textContent ?? '';   // innerText drops the space a flex row swallows
  return {
    cards: text('.agents .agent'), pipeline: text('#h-pipeline, .timeline-steps > li'),
    tiles: [...document.querySelectorAll('.tiles .tile')].map((el) => el.getAttribute('aria-label')),
    tests: text('#h-tests, .tiles ~ .legend .pill'), findings: text('.findings li'),
    ai: meta.slice(meta.indexOf('AI so far'), meta.lastIndexOf(' · ')),
  };
}"""
_AT_END_JS = """(total) => {
  const status = document.querySelector('.player .pos')?.textContent ?? '';
  return status.startsWith(`${total} / ${total}`) && (document.querySelector('.run-meta')?.textContent ?? '').endsWith('finished');
}"""


def fixture_lines() -> list[tuple[str, str, float]]:
    """Every recorded event as (file name, line, time), in the order the run wrote them."""
    rows = []
    for f in sorted(FIXTURE.glob("events-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append((f.name, line, float(json.loads(line)["t"])))
    return sorted(rows, key=lambda r: r[2])


def append(folder: Path, rows: list[tuple[str, str, float]]) -> None:
    for name in {r[0] for r in rows}:
        with (folder / name).open("a", encoding="utf-8") as out:
            out.write("".join(f"{line}\n" for n, line, _ in rows if n == name))


def expected_problems(pic: dict) -> list[str]:
    want = json.loads(SUMMARY.read_text(encoding="utf-8"))
    problems = []
    done = [c for c in pic["cards"] if " Done" in f" {c}"]
    if len(done) != len(want["cards"]):
        problems.append(f"{len(done)} cards say Done, the recording has {len(want['cards'])}: {pic['cards']}")
    for status, n in want["tiles"].items():
        got = sum(1 for label in pic["tiles"] if label and label.endswith(f" {TILE_WORDS.get(status, status)}"))
        if got != n:
            problems.append(f"{got} tiles say {TILE_WORDS.get(status, status)}, the recording has {n}")
    if f"${want['ai']['cost']:.4f}" not in pic["ai"]:
        problems.append(f"the AI total is not ${want['ai']['cost']:.4f}: {pic['ai']!r}")
    gates = " ".join(pic["pipeline"])
    for words in (f"{want['gates']['questions']} for you", want["gates"]["plan"], f"{want['gates']['defects']} to confirm"):
        if words not in gates:
            problems.append(f"the pipeline does not say {words!r}")
    return problems


def at_end(page, total: int, label: str) -> dict:
    page.wait_for_function(_AT_END_JS, arg=total, timeout=WAIT_MS)
    page.wait_for_timeout(app.SETTLE_MS)
    print(f"  {label}: at {total} / {total}")
    return page.evaluate(_PICTURE_JS)


def watch_live(browser, base: str, slug: str, folder: Path, rows: list) -> tuple[dict, str | None, dict, dict]:
    """The run arrives while the page is open; then reload, then Replay from the start at Instant."""
    from agentqa.orchestrator.live import mark_ended, mark_running
    mark_running(folder)
    shutil.copytree(FIXTURE / "shots", folder / "shots")
    step = -(-len(rows) // CHUNKS)
    append(folder, rows[:step])
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    app.sign_in(context, base)
    page = context.new_page()
    page.goto(f"{base}/app/projects/{slug}/live?session={SESSION}")
    page.get_by_role("heading", name="Agents").wait_for()
    for i in range(step, len(rows), step):
        time.sleep(CHUNK_S)
        append(folder, rows[i:i + step])
    mark_ended(folder, os.getpid())
    live = at_end(page, len(rows), "watched live")
    transport = page.get_attribute("[data-transport]", "data-transport")
    page.reload()
    reloaded = at_end(page, len(rows), "after a reload")
    page.get_by_role("button", name="Replay from the start").click()
    page.get_by_label("Speed").select_option("0")
    replayed = at_end(page, len(rows), "replayed at Instant")
    context.close()
    return live, transport, reloaded, replayed


def watch_sse(browser, base: str, slug: str, total: int) -> tuple[dict, str | None]:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_init_script(REFUSE_WS)
    app.sign_in(context, base)
    page = context.new_page()
    page.goto(f"{base}/app/projects/{slug}/live?session={SESSION}")
    pic = at_end(page, total, "over SSE")
    transport = page.get_attribute("[data-transport]", "data-transport")
    context.close()
    return pic, transport


def compare(pictures: dict[str, dict]) -> list[str]:
    (first, base_pic), *rest = pictures.items()
    problems = []
    for label, pic in rest:
        for part, value in pic.items():
            if value != base_pic[part]:
                problems.append(f"{label}: the {part} differ from {first}: {value!r} vs {base_pic[part]!r}")
    return problems


def main() -> int:
    if not (app.ROOT / "frontend" / "dist" / "index.html").is_file():
        print("frontend/dist is missing: run `make web-build` first")
        return 1
    rows = fixture_lines()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:      # Windows may still hold the test db for a moment
        projects = Path(tmp) / "projects"
        proc, base = app.start_server(projects)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                with browser.new_context() as context:
                    slug = app.sign_in(context, base)
                folder = projects / slug / ".agentqa" / "live" / SESSION
                live, ws, reloaded, replayed = watch_live(browser, base, slug, folder, rows)
                sse, fallback = watch_sse(browser, base, slug, len(rows))
                browser.close()
        finally:
            proc.kill()
            proc.wait(timeout=10)
    problems = expected_problems(live)
    problems += [] if ws == "websocket" else [f"the live run used {ws!r}, not websocket"]
    problems += [] if fallback == "sse" else [f"with WebSocket refused the page used {fallback!r}, not sse"]
    problems += compare({"watched live": live, "after a reload": reloaded, "replayed at Instant": replayed, "over SSE": sse})
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))
        return 1
    print(f"\nLive View passes: {len(rows)} events watched live over WebSocket, the expected final picture, and the same "
          "picture after a reload, after Replay from the start at Instant, and over the SSE fallback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
