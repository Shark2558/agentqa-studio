"""The AgentQA Studio API (/api/v1): sign-in, projects, runs and the live event stream, in front of the engine.

`create_app()` builds the FastAPI app; `agentqa.api.server` is the module uvicorn serves (API + the new web app +
the old dashboard mounted at /, behind the same sign-in)."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse

from agentqa import __version__
from agentqa.api import auth as _auth
from agentqa.api.errors import ApiError, fail, install_handlers, ok
from agentqa.api.live_feed import StreamSlots
from agentqa.api.ratelimit import RateLimiter
from agentqa.api.schemas import LoginIn
from agentqa.api.settings import Settings

API_PREFIX = "/api/v1"
# Screenshots, evidence and visual-review pictures have their own rate bucket (a page may show many at once), and so
# does the help box's pending list, which every open page polls every 2 s (M1.4 Phase C).
SHOT_PATH = re.compile(rf"^{API_PREFIX}/projects/[^/]+/(?:live/[^/]+/shots/[^/]+|defects/[^/]+/evidence/\d+"
                       r"|visual/[^/]+/(?:baseline|current|diff)|assist(?:/\d+/shot)?)$")
OPEN_WRITES = frozenset({f"{API_PREFIX}/auth/login", f"{API_PREFIX}/auth/logout"})   # any role may sign in or out
APP_PREFIX = "/app"
SIGN_IN_PAGE = f"{APP_PREFIX}/sign-in"
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                    "Referrer-Policy": "strict-origin-when-cross-origin",
                    "Permissions-Policy": "camera=(), microphone=(), geolocation=()"}
# The React app: scripts, styles, fonts and images come from this origin; the old dashboard keeps its inline scripts.
APP_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
NO_STORE = "no-cache, no-store, must-revalidate"


def create_app(settings: Settings | None = None, legacy: bool = False, frontend_dist: Path | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    frontend_dist = frontend_dist or FRONTEND_DIST
    app = FastAPI(title="AgentQA Studio API", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=f"{API_PREFIX}/openapi.json")
    app.state.settings = settings
    app.state.sessions = _auth.Sessions(settings)
    app.state.login_limiter = _auth.LoginLimiter(settings.login_attempts, settings.login_window_s)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_min)
    app.state.shot_limiter = RateLimiter(settings.shot_rate_per_min)
    app.state.stream_slots = StreamSlots(settings.streams_per_client, settings.streams_total)
    install_handlers(app)
    _install_guards(app, legacy)

    @app.get(f"{API_PREFIX}/health")
    def health():
        return ok({"status": "ok", "version": __version__, "owner_configured": settings.owner_configured})

    @app.post(f"{API_PREFIX}/auth/login")
    def login(request: Request, body: LoginIn):
        user = _auth.authenticate(settings, app.state.login_limiter, _auth.client_key(request), body.email, body.password)
        response = ok({"email": user.email, "role": user.role})
        app.state.sessions.set_cookie(response, app.state.sessions.issue(user))
        return response

    @app.post(f"{API_PREFIX}/auth/logout")
    def logout():
        """Always clears the cookie: an expired or tampered session must still be able to sign out."""
        response: JSONResponse = ok({"signed_out": True})
        app.state.sessions.clear_cookie(response)
        return response

    @app.get(f"{API_PREFIX}/auth/me")
    def me(user: _auth.User = Depends(_auth.current_user)):
        return ok({"email": user.email, "role": user.role})

    @app.get(f"{API_PREFIX}/docs", include_in_schema=False)
    def docs(user: _auth.User = Depends(_auth.current_user)):
        return get_swagger_ui_html(openapi_url=f"{API_PREFIX}/openapi.json", title="AgentQA Studio API")

    from agentqa.api import (routes_ai, routes_assist, routes_defects, routes_gates, routes_live, routes_live_ws,
                             routes_plan, routes_projects, routes_questions, routes_review, routes_runs, routes_wizard)
    for router in (routes_projects.router, routes_runs.router, routes_live.router, routes_live_ws.router,
                   routes_wizard.router, routes_wizard.tools, routes_ai.router, routes_ai.projects,
                   routes_questions.router, routes_plan.router, routes_defects.router, routes_gates.router,
                   routes_review.router, routes_assist.router):
        app.include_router(router, prefix=API_PREFIX)

    _serve_frontend(app, frontend_dist)
    if legacy:
        _mount_dashboard(app)
    return app


def _install_guards(app: FastAPI, legacy: bool) -> None:
    """Every HTTP request passes here first (WebSockets do not: `routes_live_ws` checks for itself)."""

    @app.middleware("http")
    async def guards(request: Request, call_next):
        path = request.url.path
        if path.startswith(API_PREFIX):
            refused = _api_gate(app, request, path)
        elif legacy and not (path == APP_PREFIX or path.startswith(APP_PREFIX + "/")):
            refused = _legacy_gate(request)                      # the old dashboard needs the same sign-in
        else:
            refused = None
        return _secured(refused if refused is not None else await call_next(request))


def _api_gate(app: FastAPI, request: Request, path: str):
    """None when an API request may go on; otherwise the refusal: rate limit (screenshots have their own bucket),
    the CSRF header on writes, and the read-only rule for a role that may not write."""
    limiter = app.state.shot_limiter if SHOT_PATH.match(path) else app.state.rate_limiter
    if not limiter.allow(_auth.client_key(request)):
        return fail(429, "rate_limited", "Too many requests; slow down", {"Retry-After": "1"})
    try:
        _auth.csrf_check(request)
    except ApiError as exc:
        return fail(exc.status, exc.code, exc.message)
    read_only = None if path in OPEN_WRITES else _auth.read_only_refusal(request)
    return None if read_only is None else fail(read_only.status, read_only.code, read_only.message)


def _secured(response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


def _legacy_gate(request: Request):
    """None when the request may reach the old dashboard; otherwise the refusal (a redirect to the sign-in page for
    a page load, 401 for anything else, 403 for a state change by a read-only role or from another site). The person
    signed in is handed on as `request.state.agentqa_user`, so the old help box logs who and keeps the Viewer rule."""
    user = _auth.session_user(request)
    if user is None:
        if request.method in ("GET", "HEAD"):
            return RedirectResponse(SIGN_IN_PAGE, status_code=303)
        return fail(401, "unauthenticated", "Sign in first")
    request.state.agentqa_user = user
    read_only = _auth.read_only_refusal(request)
    if read_only is not None:
        return fail(read_only.status, read_only.code, read_only.message)
    if request.method not in _auth.SAFE_METHODS and not _same_origin(request):
        return fail(403, "csrf", "Cross-site request refused")
    return None


def _same_origin(request: Request) -> bool:
    """The old dashboard posts plain HTML forms, so its CSRF guard is the browser's Origin / Referer header, compared
    with the host *and port* (a page on another local port, such as the demo portal under test, is another site)."""
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        return True                                              # a non-browser client (TestClient, curl) sends neither
    return _auth.origin_matches_host(origin, request.headers.get("host", ""))


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """The built React app at /app: real files as themselves, every other /app/... path gets index.html (the app's
    own router takes it from there), nothing outside the build folder, and never the shell for a missing asset."""
    from fastapi.responses import FileResponse, PlainTextResponse

    def shell(index: Path):
        return FileResponse(index, headers={"Cache-Control": NO_STORE, "Content-Security-Policy": APP_CSP})

    @app.get(APP_PREFIX, include_in_schema=False)
    @app.get(APP_PREFIX + "/{path:path}", include_in_schema=False)
    def frontend(path: str = ""):
        index = dist / "index.html"
        if not index.is_file():
            return PlainTextResponse("The web app has not been built yet (make web-build).", status_code=503)
        candidate = (dist / path).resolve() if path else index
        if candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
            raise ApiError(404, "not_found", "No such file")
        return shell(index)


def _mount_dashboard(app: FastAPI) -> None:
    """The v0.8 dashboard at / (until M1.4 replaces it); mounted last so the API and /app win, gated by `guards`."""
    from agentqa.web.app import app as dashboard
    app.mount("/", dashboard)
