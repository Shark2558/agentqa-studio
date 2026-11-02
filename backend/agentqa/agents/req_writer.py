"""Requirement Writer agent: turns what the Requirement Analyst found into clear, testable wording.

The Requirement Analyst reads the documents and pulls out each requirement as it was written, with its rules and
anything vague. The Requirement Writer comes next. For every requirement it writes:

  statement            one clear sentence ("The system shall ...")
  user story           As a <role>, I want ..., so that ...
  steps                the main flow, step by step, each with who does it (Citizen, Clerk, System)
  alternate flows and exceptions
  acceptance criteria  Given / When / Then
  open points          what the text leaves unclear, as questions for the business analyst

An AI model writes it when one is set up on the AI providers page. Every number, limit and role it uses is checked
against the source text and the extracted rules: anything it added is flagged ("the model added 30") and the
requirement is marked for review, so a rewrite never quietly changes a business rule. Without a model the same
fields are filled from the standardised requirement, plainly, and say so.

The Test Case Generation agent drafts its cases from these steps and acceptance criteria.
"""
from __future__ import annotations

import hashlib
import json
import re

from agentqa import live
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import warn

SYSTEM = """[[AQ-TASK:req-writer]] You are a senior business analyst for government web portals. Rewrite each
requirement into clear, testable wording without changing its meaning. Use only the facts given: the requirement text,
its extracted rules, the roles and the screens listed. Never invent a number, limit, role, screen or rule; when the
text leaves something unclear, put it in open_points instead of guessing. Write in plain English.
Reply with JSON only:
{"items": [{"id": "...", "statement": "The system shall ...", "user_story": "As a <role>, I want ..., so that ...",
 "preconditions": ["..."], "steps": [{"actor": "<role or System>", "action": "..."}], "alternate_flows": ["..."],
 "exceptions": ["..."], "acceptance_criteria": ["Given ..., when ..., then ..."], "open_points": ["..."]}]}"""

NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?!\w)(?!\.\d)")
MODAL = re.compile(r"\b(shall|must|should|will|can|may|is able to|are able to)\b", re.I)


def _src_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode()).hexdigest()[:12]


def _numbers(*parts) -> set[str]:
    out: set[str] = set()
    for p in parts:
        for n in NUM.findall(json.dumps(p, ensure_ascii=False) if not isinstance(p, str) else p):
            out.add(n.replace(",", ""))
    return out


def check(item: dict, req: dict, rules: list[dict], roles: set[str]) -> list[str]:
    """What a rewrite added or dropped compared with the source: numbers, limits, roles."""
    flags = []
    written = {k: item.get(k) for k in ("statement", "user_story", "preconditions", "steps", "alternate_flows",
                                        "exceptions", "acceptance_criteria")}
    src = _numbers(req["text"], [r.get("value") for r in rules], [r.get("decided_value") for r in rules])
    got = _numbers(written)
    added = sorted(got - src, key=lambda x: float(x))
    if added:
        flags.append("the model added " + ", ".join(added) + " (not in the source)")
    dropped = sorted(src - got - {"0", "1"}, key=lambda x: float(x)) if _numbers(req["text"]) else []
    dropped = [d for d in dropped if d in _numbers(req["text"])]
    if dropped:
        flags.append("the rewrite leaves out " + ", ".join(dropped) + " from the source")
    known = {r.lower() for r in roles} | {"system", "user", "portal", "application", "the system", "visitor", "applicant"}
    for st in item.get("steps") or []:
        actor = str((st or {}).get("actor") or "").strip().lower()
        if actor and actor not in known and not any(actor.startswith(k) or k in actor for k in known):
            flags.append(f"step actor '{st.get('actor')}' is not a known role")
            break
    if not str(item.get("statement") or "").strip():
        flags.append("no statement was written")
    return flags


def _goal(text: str) -> str:
    first = re.split(r"(?<=[.;])\s+(?=[A-Z])", text.strip())[0]          # the first sentence carries the goal
    m = re.search(r"\b(?:shall|must|should|will|can|may)\s+(?:be\s+able\s+to\s+)?(?:be\s+)?(.+?)[.;]?$", first, re.I)
    goal = (m.group(1) if m else first).strip().rstrip(".")
    return re.sub(r"\b(their|his or her|his/her)\b", "my", goal)


def _by_rules(req: dict) -> dict:
    """No model: the standardised requirement in the same shape, plainly worded."""
    std = req["std"] or {}
    text = re.sub(r"\s+", " ", req["text"]).strip()
    statement = text if MODAL.search(text) else "The system shall " + text[:1].lower() + text[1:]
    statement = statement[:1].upper() + statement[1:]
    if not statement.endswith("."):
        statement += "."
    actors = [a for a in (std.get("actors") or []) if a not in ("user", "system")]
    actor = actors[0] if actors else "user"
    goal = _goal(text)
    story = f"As a {actor}, I want {('to ' + goal) if not goal.lower().startswith(('to ', 'be ')) else goal}." if goal else ""
    steps = []
    for x in std.get("main_flow") or []:
        m = re.match(r"log ?in as (\w+)", x, re.I)
        steps.append({"actor": (m.group(1) if m else actor).capitalize(), "action": x})
    if std.get("expected_outcome") and std["expected_outcome"] != "The behaviour described is observed":
        steps.append({"actor": "System", "action": std["expected_outcome"]})
    opens = []
    for a in req.get("ambiguity") or []:
        opens.append(f"'{a.get('term')}' needs a precise value")
    if std.get("clarification") not in (None, "", "clear") and not opens:
        opens.append(std["clarification"])
    if not story.count("so that"):
        opens.append("the benefit (so that ...) is not stated")
    return {"statement": statement, "user_story": story, "preconditions": std.get("preconditions") or [],
            "steps": steps, "alternate_flows": std.get("alternative_flows") or [], "exceptions": std.get("exceptions") or [],
            "acceptance_criteria": std.get("acceptance_criteria") or [], "open_points": opens}


def write(project: Project, store: Store, use_llm: bool | None = None) -> dict:
    from agentqa.agents import requirements as reqs_agent
    reqs_agent.standardise(project, store, use_llm=False)
    reqs = store.all("SELECT * FROM requirements ORDER BY seq")
    if not reqs:
        return {"requirements": 0}
    rules: dict[str, list] = {}
    for r in store.all("SELECT * FROM rules"):
        rules.setdefault(r["req_id"], []).append(r)
    roles = set(project.roles()) | {a for al in project.role_aliases().values() for a in al}
    screens = [{"path": s["path"], "title": s["title"], "role": s["role"]}
               for s in store.all("SELECT DISTINCT path, title, role FROM screens WHERE status < 400 ORDER BY id")][:60]
    live.emit("writer", "start", f"Requirement Writer: rewriting {len(reqs)} requirement(s) into clear, testable wording")
    written: dict[str, dict] = {}
    llm = None
    if use_llm is not False:
        from agentqa.llm import get_llm
        llm = get_llm(project, "requirement-writer")
        if llm is not None and not llm.available():
            llm = None
    if llm is not None:
        for i in range(0, len(reqs), 6):
            chunk = reqs[i:i + 6]
            payload = {"roles": sorted(roles), "screens": screens, "requirements": [
                {"id": r["id"], "text": r["text"], "section": r.get("section"), "source": (r["std"] or {}).get("source"),
                 "rules": [{"kind": x["kind"], "field": x.get("field"), "value": x.get("decided_value") or x.get("value"),
                            "roles": x.get("roles")} for x in rules.get(r["id"], [])],
                 "actors": (r["std"] or {}).get("actors"), "vague_words": [a.get("term") for a in r.get("ambiguity") or []],
                 "main_flow": (r["std"] or {}).get("main_flow"), "expected_outcome": (r["std"] or {}).get("expected_outcome")}
                for r in chunk]}
            try:
                out = llm.chat_json(SYSTEM, "PAYLOAD:\n" + json.dumps(payload, ensure_ascii=False), max_tokens=3500) or {}
            except Exception as exc:  # noqa: BLE001
                warn(f"[writer] the model could not rewrite requirements: {exc}")
                break
            for item in out.get("items") or []:
                req = next((r for r in chunk if r["id"] == item.get("id")), None)
                if req is None:
                    continue
                flags = check(item, req, rules.get(req["id"], []), roles)
                if "no statement was written" in flags:
                    continue
                written[req["id"]] = {
                    **{k: item.get(k) or ([] if k not in ("statement", "user_story") else "") for k in (
                        "statement", "user_story", "preconditions", "steps", "alternate_flows", "exceptions",
                        "acceptance_criteria", "open_points")},
                    "by": f"model ({getattr(llm, 'model', 'AI')})", "flags": flags}
    by_model = len(written)
    flagged = 0
    for r in reqs:
        w = written.get(r["id"]) or {**_by_rules(r), "by": "rules (no AI model)", "flags": []}
        w["src"] = _src_hash(r["text"])
        w["at"] = now()
        if w["flags"]:
            flagged += 1
        std = dict(r["std"] or {})
        std["written"] = w
        store.update("requirements", "id", r["id"], {"std": std})
        live.emit("writer", "requirement", f"{r['id']}: {w['statement']}", req=r["id"], by=w["by"],
                  flags=w["flags"] or None, level="warn" if w["flags"] else None)
    out = {"requirements": len(reqs), "by_model": by_model, "by_rules": len(reqs) - by_model, "flagged": flagged}
    store.set_meta("writer", out)
    live.emit("writer", "summary", f"Rewrote {len(reqs)} requirement(s): {by_model} by the model, {len(reqs) - by_model} "
              f"from the rules; {flagged} need a look (a number or role the source does not have)",
              level="ok" if not flagged else "warn")
    return out
