"""Request schemas: everything that crosses the API boundary is validated here."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agentqa.cli import STAGES

Scope = Literal["pipeline", "continue", *STAGES]
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(pattern=r"^https?://[^\s/]+", max_length=400)


class RunIn(BaseModel):
    scope: Scope
    policy: Literal["", "srs_wins", "app_wins", "ask"] = ""
    auto_approve: bool = False
    headed: bool = False
