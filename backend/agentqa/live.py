"""Live event stream: what each agent is doing, step by step.

Self-contained (standard library only) so it can be copied next to the
generated tests. Every process appends JSON lines to its own file inside the
session folder given by AGENTQA_LIVE_DIR; browser agents also save a JPEG of
the viewport and the box of the element they act on. The dashboard's Live
View reads these files, so any run can be watched live or replayed later.

Secrets are never written: password fields are masked before emitting.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()


class Live:
    def __init__(self, folder: str | Path | None, worker: str = "main"):
        self.dir = Path(folder) if folder else None
        self.worker = worker
        self.seq = 0
        self.shots = 0
        self.enabled = self.dir is not None
        self.screenshots = os.environ.get("AGENTQA_LIVE_SHOTS", "1") != "0"
        self.quality = int(os.environ.get("AGENTQA_LIVE_QUALITY", "50"))
        self.max_shots = int(os.environ.get("AGENTQA_LIVE_MAX_SHOTS", "4000"))
        self.headed = os.environ.get("AGENTQA_HEADED", "0") == "1"
        if self.enabled:
            (self.dir / "shots").mkdir(parents=True, exist_ok=True)
            self.file = self.dir / f"events-{worker}.jsonl"

    # ------------------------------------------------------------------
    def emit(self, agent: str, kind: str, title: str, **fields) -> dict | None:
        if not self.enabled:
            return None
        with _LOCK:
            self.seq += 1
            event = {"t": round(time.time(), 3), "seq": self.seq, "w": self.worker, "agent": agent,
                     "kind": kind, "title": str(title)[:300]}
            for k, v in fields.items():
                if v is not None:
                    event[k] = v
            try:
                with self.file.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            except OSError:
                pass
        return event

    def shot(self, page, agent: str, kind: str, title: str, locator=None, **fields) -> dict | None:
        """Emit an event with a viewport screenshot and the target element's box."""
        if not self.enabled:
            return None
        box = None
        if locator is not None:
            try:
                b = locator.bounding_box(timeout=1500)
                if b:
                    box = {k: round(v) for k, v in b.items()}
                    if self.headed:
                        locator.evaluate("e => { const o = e.style.outline; e.style.outline = '3px solid #ff5a1f';"
                                         " setTimeout(() => e.style.outline = o, 900); }")
            except Exception:  # noqa: BLE001
                box = None
        name = None
        if self.screenshots and self.shots < self.max_shots:
            try:
                self.shots += 1
                name = f"{self.worker}-{self.seq + 1:05d}.jpg"
                page.screenshot(path=str(self.dir / "shots" / name), type="jpeg", quality=self.quality,
                                timeout=5000, animations="disabled")
            except Exception:  # noqa: BLE001
                name = None
        try:
            vp = page.viewport_size or {"width": 1280, "height": 800}
            url = page.url
        except Exception:  # noqa: BLE001
            vp, url = {"width": 1280, "height": 800}, None
        return self.emit(agent, kind, title, shot=name, box=box, vw=vp["width"], vh=vp["height"], url=url, **fields)


_LIVE: Live | None = None


def get(worker: str | None = None) -> Live:
    global _LIVE
    if _LIVE is None:
        folder = os.environ.get("AGENTQA_LIVE_DIR")
        w = worker or os.environ.get("PYTEST_XDIST_WORKER") or os.environ.get("AGENTQA_LIVE_WORKER") or "main"
        _LIVE = Live(folder, w)
    return _LIVE


def emit(agent: str, kind: str, title: str, **fields):
    return get().emit(agent, kind, title, **fields)


def shot(page, agent: str, kind: str, title: str, locator=None, **fields):
    return get().shot(page, agent, kind, title, locator=locator, **fields)


def mask(value: str, field_type: str | None = None, name: str | None = None) -> str:
    sensitive = (field_type or "").lower() == "password" or any(
        k in (name or "").lower() for k in ("password", "passwd", "pwd", "otp", "pin_code_secret", "token"))
    if sensitive:
        return "•" * 8
    v = str(value)
    return v if len(v) <= 60 else f"{v[:57]}... ({len(v)} chars)"
