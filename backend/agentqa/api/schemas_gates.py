"""Request schemas for the three gates and the requirements page (M1.4): ids by pattern and count, decisions from a
fixed list, reasons as trimmed text of at most 500 characters. Which decisions need a reason is the services' rule."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Query
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from agentqa.orchestrator.gates.changelog import WHY_MAX, clean_why

LIST_MAX = 200
ID_MAX = 2 ** 31 - 1                  # a row id SQLite can compare (a larger number is "not found", never a crash)
Limit = Query(default=50, ge=1, le=LIST_MAX)
Offset = Query(default=0, ge=0, le=1_000_000)
CASES_MAX, DEFECTS_MAX = 500, 200
CASE_ID = r"^TC-\d{4,6}$"
DEFECT_ID = r"^DEF-\d{3,6}$"
DOC_ID = r"^[^\x00-\x1f\x7f]{1,200}$"   # ids written in a document (requirement, imported case): any text, one line
CASE_TYPE = r"^[a-z0-9_]{1,40}$"
DIGEST = r"^[0-9a-f]{12}$"


def _required(why: str) -> str:
    why = clean_why(why)
    if not why:
        raise ValueError("give a short reason")
    return why


Why = Annotated[str, Field(max_length=WHY_MAX), AfterValidator(clean_why)]
RequiredWhy = Annotated[str, Field(max_length=WHY_MAX), AfterValidator(_required)]
CaseId = Annotated[str, Field(pattern=CASE_ID)]
DefectId = Annotated[str, Field(pattern=DEFECT_ID)]
DocId = Annotated[str, Field(pattern=DOC_ID)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyIn(_In):
    pass


class AnswerIn(_In):
    choice: int = Field(ge=0, le=50)
    value: str = Field(default="", max_length=400)


class ReopenIn(_In):
    why: RequiredWhy


class CaseDecisionIn(_In):
    ids: list[CaseId] = Field(min_length=1, max_length=CASES_MAX)
    decision: Literal["approve", "reject", "reset"]
    why: Why = ""


class TypeDecisionIn(_In):
    decision: Literal["approve", "reject"]
    why: Why = ""


class ImportedDecisionIn(_In):
    ids: list[DocId] = Field(default_factory=list, max_length=CASES_MAX)
    decision: Literal["approve_ready", "approve", "reject", "review"]
    why: Why = ""


class ApproveIn(_In):
    digest: str = Field(pattern=DIGEST)
    why: Why = ""


class DefectDecisionIn(_In):
    ids: list[DefectId] = Field(min_length=1, max_length=DEFECTS_MAX)
    decision: Literal["confirmed", "rejected", "draft"]
    why: Why = ""


class DispositionIn(_In):
    disposition: Literal["out_of_scope", "not_testable", "manual", "clarify"]     # covered and gap are computed
    why: RequiredWhy
