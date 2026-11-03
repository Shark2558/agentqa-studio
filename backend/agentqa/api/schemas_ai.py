"""Request schemas for the AI endpoints: keys, the routing policy and a project's `ai:` block."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from agentqa.ai.settings import AGENT_KEYS, MAX_BUDGET_USD, MAX_CHUNKS, MIN_BUDGET_USD, MIN_CHUNKS

Mode = Literal["none", "local", "cloud", "hybrid"]
Tier = Literal["cheap", "balanced", "strong", "vision", "off"]
KeyStatus = Literal["active", "disabled"]
Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Seconds = Annotated[float, Field(ge=0, le=86_400, allow_inf_nan=False)]
MAX_KEY = 512
MAX_MODEL = 120


class KeyIn(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    key: str = Field(default="", max_length=MAX_KEY)
    base_url: str | None = Field(default=None, max_length=400)
    model: str = Field(default="auto", max_length=MAX_MODEL)
    fallback_model: str = Field(default="", max_length=MAX_MODEL)
    priority: int = Field(default=10, ge=1, le=100)
    timeout_s: float | None = Field(default=None, ge=1, le=900)
    deployment: str | None = Field(default=None, max_length=MAX_MODEL)      # Azure OpenAI only
    api_version: str | None = Field(default=None, max_length=40)
    status: KeyStatus = "active"


class KeyPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    key: str | None = Field(default=None, max_length=MAX_KEY)             # empty keeps the stored key
    base_url: str | None = Field(default=None, max_length=400)
    model: str | None = Field(default=None, max_length=MAX_MODEL)
    fallback_model: str | None = Field(default=None, max_length=MAX_MODEL)
    priority: int | None = Field(default=None, ge=1, le=100)
    timeout_s: float | None = Field(default=None, ge=1, le=900)
    deployment: str | None = Field(default=None, max_length=MAX_MODEL)
    api_version: str | None = Field(default=None, max_length=40)
    status: KeyStatus | None = None


class PolicyIn(BaseModel):
    order: list[str] | None = Field(default=None, max_length=20)
    provider_fallback: bool | None = None
    attempts_per_key: int | None = Field(default=None, ge=1, le=5)
    timeout_s: float | None = Field(default=None, ge=5, le=600)
    backoff_s: float | None = Field(default=None, ge=0, le=30)
    cooldown_s: dict[str, Seconds] | None = None
    redact: bool | None = None
    prices: dict[str, dict[str, list[Money]]] | None = None

    @field_validator("prices")
    @classmethod
    def _two_prices(cls, v: dict[str, dict[str, list[float]]] | None) -> dict[str, dict[str, list[float]]] | None:
        for provider, models in (v or {}).items():
            for model, pair in models.items():
                if len(pair) != 2:
                    raise ValueError(f"prices.{provider}.{model} must be [usd per 1M input tokens, usd per 1M output tokens]")
        return v


class ConsentIn(BaseModel):
    send_text: bool = False
    send_screenshots: bool = False


class BudgetIn(BaseModel):
    monthly_usd: float = Field(default=10, ge=MIN_BUDGET_USD, le=MAX_BUDGET_USD)
    alert_at_pct: int = Field(default=80, ge=1, le=100)


class ProjectAiIn(BaseModel):
    mode: Mode
    consent: ConsentIn = Field(default_factory=ConsentIn)
    budget: BudgetIn = Field(default_factory=BudgetIn)
    assignments: dict[str, Tier] = Field(default_factory=dict)
    max_chunks: int = Field(default=40, ge=MIN_CHUNKS, le=MAX_CHUNKS)

    @field_validator("assignments")
    @classmethod
    def _known_agents(cls, v: dict[str, str]) -> dict[str, str]:
        for agent in v:
            if agent not in AGENT_KEYS:
                raise ValueError(f"'{agent}' is not an agent (choose from {', '.join(AGENT_KEYS)})")
        return v
