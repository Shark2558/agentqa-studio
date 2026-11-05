"""Request schemas for M1.4 Phase C: visual review, heals, the help box's answers and take-over commands, teach.

A take-over command drives a real browser on the application under test, so every field is bounded here: a click is
a point on a screen of at most 10 000 px, keys come from the engine's allow-list, an address is a path of the project
(the service then checks its scope), typed text is one line of at most 500 characters."""
from __future__ import annotations

from typing import Annotated, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentqa.api.schemas_gates import RequiredWhy, Why

VISUAL_KEY = r"^[\w@.\-]{1,200}$"
ROLE = r"^[\w.\-]{1,64}$"
ONE_LINE = r"^[^\x00-\x1f\x7f]+$"
POINT_MAX = 10_000
Key = Literal["Enter", "Tab", "Backspace", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Space"]
KEYS = get_args(Key)                  # a test checks these are the engine's own (assist.KEYS)
Coord = Annotated[float, Field(ge=0, le=POINT_MAX, allow_inf_nan=False)]
VisualKey = Annotated[str, Field(pattern=VISUAL_KEY)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisualDecisionIn(_In):
    decision: Literal["approve", "defect"]
    why: Why = ""


class VisualApproveAllIn(_In):
    keys: list[VisualKey] | None = Field(default=None, min_length=1, max_length=200)
    why: RequiredWhy


class HealDecisionIn(_In):
    decision: Literal["approve", "reject"]
    why: Why = ""


class TeachIn(_In):
    role: str = Field(pattern=ROLE)


class AssistAnswerIn(_In):
    """Exactly one answer: a typed value, a choice, a point on the screenshot (with the label clicked, when known),
    yes/no, skip, "let me take over", or "I'm done"."""
    text: str | None = Field(default=None, max_length=200, pattern=ONE_LINE)
    option: int | None = Field(default=None, ge=0, le=19)
    x: Coord | None = None
    y: Coord | None = None
    ok: bool | None = None
    skip: Literal[True] | None = None
    takeover: Literal[True] | None = None
    done: Literal[True] | None = None

    @model_validator(mode="after")
    def _one_action(self) -> AssistAnswerIn:
        given = self.model_dump(exclude_none=True)
        point = {"x", "y"} & set(given)
        if point and point != {"x", "y"}:
            raise ValueError("x and y go together")
        actions = set(given) - {"x", "y"} - ({"text"} if point else set())
        if len(actions) + bool(point) != 1:
            raise ValueError("give exactly one answer: text, option, x and y, ok, skip, takeover or done")
        return self

    def answer(self) -> dict:
        return self.model_dump(exclude_none=True)


class ClickCmd(_In):
    kind: Literal["click"]
    x: Coord
    y: Coord


class TypeCmd(_In):
    kind: Literal["type"]
    text: str = Field(min_length=1, max_length=500, pattern=ONE_LINE)
    secret: bool = False
    replace: bool = False


class PressCmd(_In):
    kind: Literal["press"]
    key: Key


class BackCmd(_In):
    kind: Literal["back"]


class ScrollCmd(_In):
    kind: Literal["scroll"]
    dy: int = Field(default=400, ge=-5000, le=5000)


class GotoCmd(_In):
    kind: Literal["goto"]
    path: str = Field(min_length=1, max_length=400, pattern=r"^[/@][^\x00-\x1f\x7f]*$")


CommandIn = Annotated[Union[ClickCmd, TypeCmd, PressCmd, BackCmd, ScrollCmd, GotoCmd], Field(discriminator="kind")]
