"""Run the demo as two portals over one back end: Citizen Portal and Department Portal.

    python -m demo.portal.serve [--port 8800] [--dept-port 8810]
"""
from __future__ import annotations

import argparse
import asyncio
import os


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--dept-port", type=int, default=8810)
    a = ap.parse_args()
    os.environ.setdefault("DEMO_CITIZEN_URL", f"http://127.0.0.1:{a.port}")
    os.environ.setdefault("DEMO_DEPT_URL", f"http://127.0.0.1:{a.dept_port}")
    import uvicorn
    from demo.portal.app import citizen_portal, department_portal
    servers = [uvicorn.Server(uvicorn.Config(citizen_portal, host="127.0.0.1", port=a.port, log_level="warning")),
               uvicorn.Server(uvicorn.Config(department_portal, host="127.0.0.1", port=a.dept_port, log_level="warning"))]
    print(f"Citizen Portal    http://127.0.0.1:{a.port}\nDepartment Portal http://127.0.0.1:{a.dept_port}", flush=True)

    async def run():
        await asyncio.gather(*(s.serve() for s in servers))
    asyncio.run(run())


if __name__ == "__main__":
    main()
