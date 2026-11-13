"""The screen a waiting question shows a person: a live screenshot kept current while the agent waits, and the buttons
and boxes on it (moved out of `assist.py` in M1.4 Phase C; what it does is unchanged, except that a question's last
screenshot is deleted when the question ends)."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from agentqa.store import Store
from agentqa.util import warn

CLICKABLES_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && r.bottom > 0 && r.top < innerHeight; };
  const out = [];
  for (const e of document.querySelectorAll('a[href], button, [role=button], [role=tab], [role=menuitem], [role=link], input[type=submit], input[type=button], [onclick]')) {
    if (!vis(e)) continue;
    const t = (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 60) continue;
    const r = e.getBoundingClientRect();
    out.push({text: t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)});
    if (out.length >= 40) break;
  }
  return out;
}"""


FIELDS_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && r.bottom > 0 && r.top < innerHeight; };
  const out = [];
  for (const e of document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea')) {
    if (!vis(e) || e.disabled) continue;
    let l = (e.labels && e.labels.length ? e.labels[0].innerText : '') || e.getAttribute('aria-label') || e.placeholder || e.name || e.type;
    const r = e.getBoundingClientRect();
    out.push({label: (l || '').trim().replace(/\s+/g, ' ').slice(0, 40), type: e.type || e.tagName.toLowerCase(),
              x: Math.round(r.x + Math.min(r.width / 2, 60)), y: Math.round(r.y + r.height / 2), filled: !!e.value});
    if (out.length >= 20) break;
  }
  return out;
}"""


def settle(page) -> None:
    """Let the page finish what it is doing before it is shown to a person."""
    try:
        page.wait_for_load_state("load", timeout=5000)
        page.wait_for_load_state("networkidle", timeout=1500)
    except Exception:  # noqa: BLE001
        pass
    try:
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass


def _unlink(f: Path) -> None:
    try:
        f.unlink(missing_ok=True)
    except OSError as exc:                  # a download may hold it open on Windows: the sweep deletes it later
        warn(f"could not delete the help-box screenshot {f.name} ({exc.__class__.__name__})")


class Shooter:
    """Keeps the screenshot of a question current: a new file (and version) whenever the screen changes."""

    def __init__(self, page, folder: Path, aid: int, store: Store, detail: dict, every_s: float = 1.5):
        self.page, self.folder, self.aid, self.store, self.detail, self.every = page, folder, aid, store, detail, every_s
        self.last_at, self.last_hash, self.v = 0.0, None, 0

    def refresh(self, force: bool = False) -> bool:
        if not force and time.time() - self.last_at < self.every:
            return False
        self.last_at = time.time()
        try:
            data = self.page.screenshot(type="jpeg", quality=70, timeout=5000)
        except Exception:  # noqa: BLE001
            return False
        h = hashlib.sha1(data, usedforsecurity=False).hexdigest()    # only "did the picture change", not a secret
        url = ""
        try:
            url = self.page.url
        except Exception:  # noqa: BLE001
            pass
        if h == self.last_hash and url == self.detail.get("url") and not force:
            return False
        self.last_hash, self.v = h, self.v + 1
        name = f"{self.aid}-{self.v}.jpg"
        (self.folder / name).write_bytes(data)
        old = self.detail.get("shot")
        self.detail.update(shot=name, shot_v=self.v, url=url)
        self._describe()
        self.store.update("assist", "id", self.aid, {"detail": self.detail})
        if old and old != name:
            _unlink(self.folder / old)
        return True

    def _describe(self) -> None:
        """The viewport, and the buttons (and during a take-over the boxes) on the screen now."""
        try:
            vp = self.page.viewport_size or {"width": 1280, "height": 800}
            self.detail["vw"], self.detail["vh"] = vp["width"], vp["height"]
            if not self.detail.get("options"):
                self.detail["clickables"] = self.page.evaluate(CLICKABLES_JS)
            if self.detail.get("mode") == "takeover":
                self.detail["fields"] = self.page.evaluate(FIELDS_JS)
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        """The question has ended: its last screenshot goes too."""
        name = self.detail.get("shot")
        if name:
            _unlink(self.folder / Path(str(name)).name)
