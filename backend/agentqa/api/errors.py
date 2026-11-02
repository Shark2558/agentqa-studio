"""One response envelope for the whole API: {"ok": true, "data": …} or {"ok": false, "error": {"code", "message"}}."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

HTTP_CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict",
              422: "validation", 429: "rate_limited", 503: "unavailable"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers


def ok(data, status: int = 200) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data}, status_code=status)


def fail(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code, "message": message}}, status_code=status, headers=headers)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return fail(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        return fail(exc.status_code, HTTP_CODES.get(exc.status_code, "error"), str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return fail(422, "validation", f"{where}: {first.get('msg', 'invalid')}" if where else "invalid request")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):      # never leak a traceback or a path
        return fail(500, "internal", "Something went wrong on the server; the log has the details")
