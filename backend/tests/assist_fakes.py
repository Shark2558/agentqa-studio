"""A stand-in for a Playwright page, enough for `agentqa.assist`'s take-over loop: it records what the person's
commands did and answers the few scripts the loop evaluates. No browser is started."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
TICK_S = 0.02                       # every wait in the loop is shortened to this


class FakeKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []

    def type(self, text: str, delay: float = 0) -> None:
        self.typed.append(text)

    def press(self, key: str) -> None:
        self.pressed.append(key)


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[float, float]] = []
        self.wheel_dy: list[float] = []

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))

    def wheel(self, dx: float, dy: float) -> None:
        self.wheel_dy.append(dy)


class FakeContext:
    def expose_binding(self, name: str, fn: Callable) -> None:
        self.binding = fn

    def add_init_script(self, script: str) -> None:
        pass


class FakePage:
    """`focus` is what has the keyboard: None (nothing), "text", "password" or "otp" (autocomplete one-time-code)."""

    def __init__(self, url: str = "http://127.0.0.1:8800/login", focus: str | None = "text"):
        self.url, self.focus = url, focus
        self.viewport_size = {"width": 1280, "height": 800}
        self.keyboard, self.mouse, self.context = FakeKeyboard(), FakeMouse(), FakeContext()
        self.visited: list[str] = []
        self.shots = 0
        self.dead = False               # True: the browser was closed under the agent

    def evaluate(self, script: str, *args):
        if "activeElement" in script and "blur" not in script:
            if self.focus is None:
                return False
            return {"box": True, "password": self.focus == "password",
                    "autocomplete": "one-time-code" if self.focus == "otp" else ""}
        if "querySelectorAll" in script:
            return []
        return None

    def screenshot(self, **_kw) -> bytes:
        self.shots += 1
        return JPEG + str(self.shots).encode()

    def wait_for_load_state(self, *_a, **_kw) -> None:
        pass

    def wait_for_timeout(self, _ms: float) -> None:
        if self.dead:
            raise RuntimeError("Target page, context or browser has been closed")
        time.sleep(TICK_S)

    def go_back(self, **_kw) -> None:
        self.visited.append("back")

    def goto(self, url: str, **_kw) -> None:
        self.visited.append(url)
        self.url = url


def wait_until(check: Callable[[], object], timeout: float = 10.0):
    """`check()`'s first truthy value, or AssertionError after `timeout` seconds."""
    end = time.time() + timeout
    while time.time() < end:
        value = check()
        if value:
            return value
        time.sleep(TICK_S)
    raise AssertionError("timed out waiting")


def in_thread(fn: Callable[[], object]) -> tuple[threading.Thread, dict]:
    """Run `fn` (an agent waiting for a person) in a thread; `out["result"]` holds what it returned."""
    out: dict = {}
    thread = threading.Thread(target=lambda: out.update(result=fn()), daemon=True)
    thread.start()
    return thread, out


def file_bytes(db_path: Path) -> bytes:
    """The database file and its write-ahead log, as a copy synced to the cloud would hold them."""
    data = b""
    for f in (db_path, db_path.with_name(db_path.name + "-wal")):
        if f.is_file():
            data += f.read_bytes()
    return data
