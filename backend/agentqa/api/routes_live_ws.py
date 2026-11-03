"""The Live View over a WebSocket (M1.3, PRD FR-LIVE-7); Server-Sent Events (`routes_live.py`) stay as the fallback.

The HTTP guards in `api/__init__.py` never run for a WebSocket, so this route makes every check itself, after the
handshake (a browser can only read a close code once the socket is open), and refuses with a close code, never data:
4401 not signed in · 4403 the page is on another origin (a page on another local port, such as the demo portal under
test, is same-site, so the SameSite=Lax cookie *is* sent with its handshake) · 4400 a cursor longer than any this
server writes · 4404 no such project or run · 4429 too many requests or open streams. The feed is the same one the SSE
stream uses. The browser never needs to send anything; its messages are read and dropped, one over 1 KB closes the
socket (1009), and a fault in the feed closes it with 1011 and is logged."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from agentqa.api import auth
from agentqa.api.errors import ApiError
from agentqa.api.live_feed import Lease, live_feed
from agentqa.api.routes_live import MAX_CURSOR_CHARS, open_run

log = logging.getLogger("agentqa.api.live")
router = APIRouter(prefix="/projects/{slug}/live")
MAX_CLIENT_MESSAGE = 1024
MAX_LOGGED_ORIGIN = 120
NORMAL, TOO_BIG, FAULT = 1000, 1009, 1011
BAD_REQUEST, SIGNED_OUT, OTHER_SITE, NOT_FOUND, TOO_MANY = 4400, 4401, 4403, 4404, 4429


def same_origin(ws: WebSocket) -> bool:
    """The page that opened the socket is on this very host and port (an absent or opaque Origin is refused)."""
    origin = ws.headers.get("origin", "")
    return bool(origin) and auth.origin_matches_host(origin, ws.headers.get("host", ""))


def refusal(ws: WebSocket, cursor: str) -> int | None:
    """The close code for a connection that may not watch, checked cheapest first; None when it may."""
    if not ws.app.state.rate_limiter.allow(auth.client_key(ws)):
        return TOO_MANY
    if auth.session_user(ws) is None:
        return SIGNED_OUT
    if not same_origin(ws):
        return OTHER_SITE
    if len(cursor) > MAX_CURSOR_CHARS:
        return BAD_REQUEST
    return None


async def _refuse(ws: WebSocket, code: int) -> None:
    """Close with `code`, and leave a line in the log saying who was refused and from which page (no cookie)."""
    log.warning("live socket refused (%s) for %s from origin %r", code, auth.client_key(ws),
                ws.headers.get("origin", "")[:MAX_LOGGED_ORIGIN])
    await ws.close(code)


@router.websocket("/{session}/ws")
async def live_socket(ws: WebSocket, slug: str, session: str, cursor: str = "") -> None:
    await ws.accept()
    code = refusal(ws, cursor)
    if code is not None:
        await _refuse(ws, code)
        return
    try:
        p, d = await asyncio.to_thread(open_run, slug, session)
    except ApiError:
        await _refuse(ws, NOT_FOUND)
        return
    lease = ws.app.state.stream_slots.lease(auth.client_key(ws))
    if lease is None:
        await _refuse(ws, TOO_MANY)
        return
    await _serve(ws, live_feed(p, d, session, cursor, auth.signed_in_check(ws)), lease)


async def _serve(ws: WebSocket, feed: AsyncIterator[dict], lease: Lease) -> None:
    """Send the feed while dropping whatever the browser sends; whichever ends first ends the other. The slot is
    released in the outermost `finally`, so even a second cancellation during clean-up cannot leak it."""
    try:
        code = await _pump(ws, feed)
    finally:
        lease.release()
    if code is not None and ws.application_state == WebSocketState.CONNECTED:
        try:
            await ws.close(code)
        except (WebSocketDisconnect, RuntimeError, OSError):  # the browser left in the moment before the close
            pass


async def _pump(ws: WebSocket, feed: AsyncIterator[dict]) -> int | None:
    """The close code to end with, or None when the browser has already gone."""
    sender, listener = asyncio.create_task(_send(ws, feed)), asyncio.create_task(_drop_messages(ws))
    try:
        done, _ = await asyncio.wait({sender, listener}, return_when=asyncio.FIRST_COMPLETED)
        return next(iter(done)).result()
    except (WebSocketDisconnect, OSError):                    # the browser went away mid-send
        return None
    except Exception:  # noqa: BLE001 - a fault in the feed must not look like the browser leaving
        log.exception("live socket feed failed")
        return FAULT
    finally:
        for task in (sender, listener):
            task.cancel()
        await asyncio.gather(sender, listener, return_exceptions=True)
        await feed.aclose()


async def _send(ws: WebSocket, feed: AsyncIterator[dict]) -> int:
    async for item in feed:
        await ws.send_text(await asyncio.to_thread(json.dumps, item))
    return NORMAL


async def _drop_messages(ws: WebSocket) -> int | None:
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return None
        if len(message.get("text") or message.get("bytes") or "") > MAX_CLIENT_MESSAGE:
            return TOO_BIG
