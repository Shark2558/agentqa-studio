"""API settings from the environment (or backend/.env, read at start-up). Secrets never live in code."""
from __future__ import annotations

import secrets
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent.parent
DOTENV = ROOT / ".env"
MIN_SECRET_LEN = 32
DEFAULT_SESSION_HOURS = 12


def load_dotenv(path: Path = DOTENV) -> dict[str, str]:
    """The KEY=VALUE pairs of a .env file as a dict (standard library only). It never touches `os.environ`, so the
    secrets stay out of anything that inherits this process's environment (the stage subprocesses)."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        warnings.warn(f"ignoring a non-numeric setting {value!r}; using {default}", stacklevel=3)
        return default


@dataclass(frozen=True)
class Settings:
    owner_email: str = ""
    owner_password_hash: str = ""
    secret_key: str = ""
    session_hours: int = DEFAULT_SESSION_HOURS
    login_attempts: int = 5          # failed sign-ins per IP before a lock
    login_window_s: int = 900        # the lock lasts this long
    rate_limit_per_min: int = 240    # requests per IP per minute on every endpoint
    cookie_secure: bool = False      # True behind HTTPS (the cloud edition)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Settings from `env` (default: the process environment). The server passes `{**load_dotenv(), **os.environ}`
        so a real environment variable wins over backend/.env."""
        env = os.environ if env is None else env
        secret = env.get("AGENTQA_SECRET_KEY", "")
        if len(secret) < MIN_SECRET_LEN:
            warnings.warn("AGENTQA_SECRET_KEY is missing or short: sessions will not survive a restart "
                          "(run `python -m agentqa owner-set` to create backend/.env)", stacklevel=2)
            secret = secrets.token_urlsafe(48)
        return cls(owner_email=env.get("AGENTQA_OWNER_EMAIL", "").strip().lower(),
                   owner_password_hash=env.get("AGENTQA_OWNER_PASSWORD_HASH", "").strip(),
                   secret_key=secret,
                   session_hours=_int(env.get("AGENTQA_SESSION_HOURS"), DEFAULT_SESSION_HOURS),
                   cookie_secure=env.get("AGENTQA_COOKIE_SECURE", "0") == "1")

    @property
    def owner_configured(self) -> bool:
        return bool(self.owner_email and self.owner_password_hash)
