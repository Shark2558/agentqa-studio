from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from agentqa.api.auth import current_user
from agentqa.api.errors import ApiError, ok
from agentqa.api.routes_projects import open_or_404
from agentqa.orchestrator import NotFound, live

router = APIRouter(prefix="/projects/{slug}/live", dependencies=[Depends(current_user)])
POLL_S = 0.5
IDLE_LIMIT_S = 3600           # a stream never outlives a run by more than this
SHOT_CACHE = "max-age=86400"


def _session_dir(slug: str, session: str):
    p, s = open_or_404(slug)
    try:
        return p, s, live.session_dir(p, session)
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc


def _is_running(p, s, session: str) -> bool:
    return any(x["id"] == session and x["running"] for x in live.sessions(p, s))


@router.get("/sessions")
def list_sessions(slug: str):
    p, s = open_or_404(slug)
    return ok(live.sessions(p, s))


@router.get("/{session}/events")
def get_events(slug: str, session: str, cursor: str = ""):
    p, s, d = _session_dir(slug, session)
    events, token = live.read_events(d, cursor)
    return ok({"events": events, "cursor": token, "running": _is_running(p, s, session)})


@router.get("/{session}/stream")
async def stream_events(slug: str, session: str, cursor: str = ""):
    """Server-Sent Events: `live` batches of new events, then `end` once the run is over and nothing new remains."""
    p, s, d = _session_dir(slug, session)

    def batch(events, token):
        return {"event": "live", "data": json.dumps({"events": events, "cursor": token})}

    async def generate():
        token, waited = cursor, 0.0
        while True:
            events, token = await asyncio.to_thread(live.read_events, d, token)
            if events:
                waited = 0.0
                yield batch(events, token)
            elif not _is_running(p, s, session) or waited > IDLE_LIMIT_S:     # SQLite: same thread as the store
                events, token = await asyncio.to_thread(live.read_events, d, token)   # the run's last words, if any
                if events:
                    yield batch(events, token)
                yield {"event": "end", "data": json.dumps({"cursor": token})}
                return
            else:
                waited += POLL_S
                await asyncio.sleep(POLL_S)

    return EventSourceResponse(generate())


@router.get("/{session}/shots/{name}")
def get_shot(slug: str, session: str, name: str):
    _, _, d = _session_dir(slug, session)
    try:
        f = live.shot_path(d, name)
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": SHOT_CACHE})
