"""Run the demo as two portals over one back end: Citizen Portal and Department Portal.

    python -m demo.portal.serve [--port 8800] [--dept-port 8810] [--host 127.0.0.1]

The default host is loopback, so a laptop never exposes the demo to its network. Inside a container pass
``--host 0.0.0.0`` so Docker can publish the ports.
"""
from __future__ import annotations

import argparse
import asyncio
import os

LOOPBACK = "127.0.0.1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--dept-port", type=int, default=8810)
    ap.add_argument("--host", default=LOOPBACK, help="interface to listen on (0.0.0.0 inside a container)")
    return ap.parse_args(argv)


def build_servers(host: str, port: int, dept_port: int) -> list:
    """One uvicorn server per portal, both listening on `host`.

    The portals link to each other through DEMO_CITIZEN_URL / DEMO_DEPT_URL; those stay loopback by default because the
    agents under test reach the portals from the same machine (or the same container network namespace)."""
    os.environ.setdefault("DEMO_CITIZEN_URL", f"http://{LOOPBACK}:{port}")
    os.environ.setdefault("DEMO_DEPT_URL", f"http://{LOOPBACK}:{dept_port}")
    import uvicorn
    from demo.portal.app import citizen_portal, department_portal
    return [uvicorn.Server(uvicorn.Config(citizen_portal, host=host, port=port, log_level="warning")),
            uvicorn.Server(uvicorn.Config(department_portal, host=host, port=dept_port, log_level="warning"))]


def main() -> None:
    a = parse_args()
    servers = build_servers(a.host, a.port, a.dept_port)
    print(f"Citizen Portal    http://{a.host}:{a.port}\nDepartment Portal http://{a.host}:{a.dept_port}", flush=True)

    async def run() -> None:
        await asyncio.gather(*(s.serve() for s in servers))
    asyncio.run(run())


if __name__ == "__main__":
    main()
