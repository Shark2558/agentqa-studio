"""The demo portals can be told which interface to listen on. Inside a container they must bind 0.0.0.0 for Docker to
publish them; on a laptop the default stays 127.0.0.1 so nothing is exposed to the network by accident."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import free_port

ROOT = Path(__file__).resolve().parent.parent


def test_serve_builds_both_portals_on_the_requested_host():
    # Arrange
    from demo.portal import serve
    citizen_port, dept_port = free_port(), free_port()

    # Act
    servers = serve.build_servers(host="0.0.0.0", port=citizen_port, dept_port=dept_port)

    # Assert
    assert [s.config.host for s in servers] == ["0.0.0.0", "0.0.0.0"]
    assert [s.config.port for s in servers] == [citizen_port, dept_port]


def test_serve_defaults_to_loopback():
    from demo.portal import serve
    assert serve.parse_args([]).host == "127.0.0.1"


def test_demo_portal_command_accepts_a_host():
    out = subprocess.run([sys.executable, "-m", "agentqa", "demo-portal", "--help"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and "--host" in out.stdout
