"""/api/v1/projects/{slug}/live: recorded runs, the board, events, the Server-Sent Events stream and screenshots.

The WebSocket transport is `routes_live_ws.py`: a WebSocket route cannot use this router's sign-in dependency."""
from __future__ import annotations

import asyncio
import json
from contextlib import aclosing
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask

from agentqa.api import auth
from agentqa.api.auth import current_user
from agentqa.api.errors import ApiError, ok
from agentqa.api.live_feed import live_feed
from agentqa.api.routes_projects import open_or_404
from agentqa.config import Project
from agentqa.orchestrator import NotFound, board, live, projects

router = APIRouter(prefix="/projects/{slug}/live", dependencies=[Depends(current_user)])
SHOT_CACHE = "max-age=86400"
MAX_CURSOR_CHARS = 4096       # 64 files' offsets fit easily; anything longer is not a cursor this server wrote
Cursor = Query(default="", max_length=MAX_CURSOR_CHARS)
TOO_MANY_STREAMS = "Too many live views are open from this computer; close one and try again"


def open_run(slug: str, session: str) -> tuple[Project, Path]:
    """The project and the run's folder, without opening the project store (a screenshot or a socket needs only
    folders; `live.is_running` reads the one row it needs itself)."""
    try:
        p = projects.find_project(slug)
        return p, live.session_dir(p, session)
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc


@router.get("/sessions")
def list_sessions(slug: str):
    p, s = open_or_404(slug)
    try:
        return ok(live.sessions(p, s, count_shots=False))
    finally:
        s.close()


@router.get("/board")
def get_board(slug: str):
    try:
        p = projects.find_project(slug)
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    return ok(board.board(list(p.roles())))


@router.get("/{session}/events")
def get_events(slug: str, session: str, cursor: str = Cursor):
    p, d = open_run(slug, session)
    events, token = live.read_events(d, cursor)
    return ok({"events": events, "cursor": token, "running": live.is_running(p, session)})


@router.get("/{session}/stream")
async def stream_events(request: Request, slug: str, session: str, cursor: str = Cursor):
    """Server-Sent Events: `live` batches of new events, then one `end` {cursor, reason}."""
    p, d = await asyncio.to_thread(open_run, slug, session)
    lease = request.app.state.stream_slots.lease(auth.client_key(request))
    if lease is None:
        raise ApiError(429, "too_many_streams", TOO_MANY_STREAMS, headers={"Retry-After": "10"})
    still_signed_in = auth.signed_in_check(request)

    async def generate():
        try:
            async with aclosing(live_feed(p, d, session, cursor, still_signed_in)) as feed:
                async for item in feed:
                    body = {k: v for k, v in item.items() if k != "type"}
                    yield {"event": item["type"], "data": await asyncio.to_thread(json.dumps, body)}
        finally:
            lease.release()

    # the background task runs even when the browser leaves before the first event; the lease is released once
    return EventSourceResponse(generate(), background=BackgroundTask(lease.release))


@router.get("/{session}/shots/{name}")
def get_shot(slug: str, session: str, name: str):
    _, d = open_run(slug, session)
    try:
        f = live.shot_path(d, name)
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": SHOT_CACHE})
