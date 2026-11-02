"""Shared fixtures for AgentQA's own tests. They need no browser and no running portal."""
from __future__ import annotations

import json
import shutil
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentqa.config import Project  # noqa: E402
from agentqa.store import Store  # noqa: E402


@pytest.fixture
def demo(tmp_path):
    """A fresh copy of the demo project: (Project, Store)."""
    root = tmp_path / "demo"
    (root / "srs").mkdir(parents=True)
    shutil.copy(ROOT / "demo" / "project.yaml", root / "project.yaml")
    for f in (ROOT / "demo" / "srs").glob("*.docx"):
        shutil.copy(f, root / "srs" / f.name)
    p = Project(root)
    return p, Store(p.db_path)


@pytest.fixture
def explored(demo):
    """The demo project with the app map a real Explorer run produced (tests/fixtures/demo_screens.json)."""
    p, s = demo
    for row in json.loads((ROOT / "tests" / "fixtures" / "demo_screens.json").read_text(encoding="utf-8")):
        text = json.dumps(row).replace("{base}", p.base_url)
        s.insert("screens", json.loads(text))
    return p, s


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
