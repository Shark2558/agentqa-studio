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


URL_PATTERN = r"^https?://[^\s/]+"
Environment = Literal["Development", "Test / QA", "UAT", "Staging", "Production"]
Method = Literal["password", "password_otp", "mobile_otp", "email_otp", "mfa", "sso"]
OtpSource = Literal["", "ask", "inbox", "fixed", "totp"]


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(pattern=URL_PATTERN, max_length=400)
    environment: Environment = "Test / QA"


class PreflightIn(BaseModel):
    url: str = Field(min_length=1, max_length=400)


class AnswerIn(BaseModel):
    question: str = Field(max_length=500)
    answer: str = Field(max_length=4000)
    topic: str = Field(default="", max_length=20)


class TypedIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    answers: list[AnswerIn] = Field(default_factory=list, max_length=10)
    items: list[str] = Field(default_factory=list, max_length=500)     # the list the owner confirmed, when there is one


class RoleIn(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    login_option: str = Field(default="Login", max_length=80)
    method: Method = "password"
    username: str | None = Field(default=None, max_length=200)
    mobile: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254)
    password: str | None = Field(default=None, max_length=512)
    otp_source: OtpSource | None = None
    otp_fixed: str | None = Field(default=None, max_length=20)
    totp_secret: str | None = Field(default=None, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    app: str | None = Field(default=None, max_length=40)


class AccountsIn(BaseModel):
    no_login: bool = False
    roles: list[RoleIn] = Field(default_factory=list, max_length=20)


class RunIn(BaseModel):
    scope: Scope
    policy: Literal["", "srs_wins", "app_wins", "ask"] = ""
    auto_approve: bool = False
    headed: bool = False
