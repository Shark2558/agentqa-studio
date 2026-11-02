"""Sign-in for the API: one owner account (M0.5), signed HttpOnly session cookie, CSRF header, login lock-out.

The users table, roles and memberships (M2.1) replace `_owner_user` and keep every dependency below."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from agentqa.api.errors import ApiError
from agentqa.api.settings import Settings

log = logging.getLogger("agentqa.api.auth")
COOKIE = "agentqa_session"
CSRF_HEADER, CSRF_VALUE = "x-requested-with", "AgentQA"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_TRACKED_CLIENTS = 10_000
_hasher = PasswordHasher()
_DECOY_HASH = _hasher.hash(secrets.token_urlsafe(24))    # verified when the email is unknown, so timing tells nothing


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, ValueError):
        return False


@dataclass(frozen=True)
class User:
    email: str
    role: str


class LoginLimiter:
    """Failed sign-ins per client address; `attempts` failures inside `window_s` lock that address out.
    Bounded: beyond `max_clients` addresses the least recently seen one is forgotten."""

    def __init__(self, attempts: int, window_s: int, max_clients: int = MAX_TRACKED_CLIENTS):
        self.attempts, self.window_s, self.max_clients = attempts, window_s, max_clients
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        recent = [t for t in self._failures.pop(key, []) if t > time.time() - self.window_s]
        if recent:
            self._failures[key] = recent
        while len(self._failures) > self.max_clients:
            self._failures.pop(next(iter(self._failures)))
        return recent

    def locked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.attempts

    def retry_after_s(self, key: str) -> int:
        """Seconds until the oldest failure inside the window falls out of it (at least 1)."""
        with self._lock:
            recent = self._recent(key)
            return max(1, int(recent[0] + self.window_s - time.time()) + 1) if recent else 1

    def failed(self, key: str) -> None:
        with self._lock:
            self._failures[key] = self._recent(key) + [time.time()]

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class Sessions:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._serializer = URLSafeTimedSerializer(settings.secret_key, salt="agentqa-session")

    def issue(self, user: User) -> str:
        return self._serializer.dumps({"email": user.email, "role": user.role})

    def load(self, token: str | None) -> User | None:
        if not token:
            return None
        try:
            data = self._serializer.loads(token, max_age=self.settings.session_hours * 3600)
        except (BadSignature, SignatureExpired):
            return None
        return User(email=str(data.get("email", "")), role=str(data.get("role", "")))

    def set_cookie(self, response, token: str) -> None:
        response.set_cookie(COOKIE, token, max_age=self.settings.session_hours * 3600, httponly=True, samesite="lax",
                            secure=self.settings.cookie_secure, path="/")

    def clear_cookie(self, response) -> None:
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=self.settings.cookie_secure)


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def csrf_check(request: Request) -> None:
    """State-changing requests must carry the custom header a cross-site form cannot send."""
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise ApiError(403, "csrf", f"Missing or wrong {CSRF_HEADER.title()} header")


def authenticate(settings: Settings, limiter: LoginLimiter, key: str, email: str, password: str) -> User:
    """The owner, or an ApiError. A wrong email costs the same argon2 check as a wrong password, so the response
    time does not say which one it was; every outcome is logged without the password."""
    if not settings.owner_configured:
        raise ApiError(503, "owner_not_configured", "No owner account yet: run `python -m agentqa owner-set`")
    if limiter.locked(key):
        log.warning("sign-in refused (locked out) from %s", key)
        raise ApiError(429, "rate_limited", "Too many failed sign-ins; try again later",
                       headers={"Retry-After": str(limiter.retry_after_s(key))})
    email_ok = email.strip().lower() == settings.owner_email
    password_ok = verify_password(password, settings.owner_password_hash if email_ok else _DECOY_HASH)
    if not (email_ok and password_ok):
        limiter.failed(key)
        log.warning("sign-in failed from %s", key)
        raise ApiError(401, "bad_credentials", "That email and password do not match")
    limiter.clear(key)
    log.info("sign-in ok for %s from %s", settings.owner_email, key)
    return User(email=settings.owner_email, role="owner")


def current_user(request: Request) -> User:
    """FastAPI dependency: the signed-in user, or 401."""
    user = session_user(request)
    if user is None:
        raise ApiError(401, "unauthenticated", "Sign in first")
    return user


def session_user(request: Request) -> User | None:
    """The signed-in user from the cookie, or None (no exception: for middleware and optional checks)."""
    sessions: Sessions = request.app.state.sessions
    return sessions.load(request.cookies.get(COOKIE))
