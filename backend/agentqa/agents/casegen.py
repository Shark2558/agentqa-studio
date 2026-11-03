"""Test Case Generation agent: template test cases for the requirements nothing else covered.

The deterministic agents come first (login, session, navigation, forms, access, workflows): their steps were
recorded on the live app. What they leave uncovered comes here. For each such requirement (taken in its
standardised form) the agent drafts cases in the standard template: test type, objective, priority, role,
preconditions, test data, steps and expected result.

  with a model    the model writes the cases; every step it names is checked against the app map. A step on a
                  screen, button or field that exists becomes a recorded step; one that does not is kept as an
                  *intent* step for the Visual QA agent instead of being dropped
  without one     the standardised use case is turned into intent steps plus a verify step

Requirements waiting for clarification, marked out of scope, not testable or manual, get no case, and each is
listed with its reason (meta 'casegen_skipped'), so nothing is silently left out.
"""
from __future__ import annotations

import json
import re

from agentqa import live
from agentqa.config import Project
from agentqa.contracts import PRIORITIES, TEST_TYPES
from agentqa.store import Store
from agentqa.util import slug, warn

SYSTEM = """[[AQ-TASK:casegen]] You are a senior manual QA engineer. Write functional test cases for each requirement
given (in its standardised form), the way an experienced tester would: the positive path, the important negative
and boundary cases, role and business-rule checks. Use the screens, buttons, links and fields listed when a step
can be named exactly; otherwise describe the step as a tester would ("Open the latest application") with
{"action": "intent", "text": "..."}. End each case with what to check: {"action": "verify", "expect": "..."}.
Reply with JSON only:
{"cases": [{"req_id": "...", "title": "...", "scenario": "Positive|Negative|Boundary", "test_type": "<one of the types>",
 "priority": "Critical|High|Medium|Low", "role": "<role>", "objective": "...", "preconditions": "...",
 "test_data": "...", "steps": [{"action": "goto", "path": "/x"} | {"action": "click", "target": "<exact text>"} |
 {"action": "fill", "path": "/x", "field": "<field name>", "value": "..."} | {"action": "intent", "text": "..."} |
 {"action": "verify", "expect": "..."}], "expected": "..."}]}
At most 4 cases per requirement. Never invent data you were not given; use test data tokens like {mobile}."""

GROUNDED = {"goto", "click", "fill", "expect_text", "expect_visible", "expect_error", "expect_success", "expect_path"}
P_OF = {"Critical": "P1", "High": "P1", "Medium": "P2", "Low": "P3"}
SKIP_DISPOSITIONS = {"out_of_scope": "marked out of scope", "not_testable": "marked not testable",
                     "manual": "marked as a manual test"}


def _catalog(store: Store) -> dict:
    cat: dict[str, dict] = {}
    for s in store.all("SELECT role, path, title, links, forms, buttons FROM screens WHERE status < 400 ORDER BY id"):
        e = cat.setdefault(s["path"], {"title": s["title"], "roles": set(), "fields": {}, "clicks": set()})
        e["roles"].add(s["role"])
        for ln in s["links"] or []:
            if ln.get("text"):
                e["clicks"].add(ln["text"].strip())
        for fm in s["forms"] or []:
            if fm.get("submit_text"):
                e["clicks"].add(fm["submit_text"].strip())
            for f in fm.get("fields") or []:
                if f.get("name"):
                    e["fields"][f["name"]] = f.get("label") or f["name"]
        for b in s["buttons"] or []:
            t = b.get("text") if isinstance(b, dict) else b
            if t:
                e["clicks"].add(str(t).strip())
    return cat


def targets(project: Project, store: Store, existing: list[dict]) -> tuple[list[dict], list[dict]]:
    covered = {r for c in existing for r in (c.get("req_ids") or [])}
    overrides = store.get_meta("req_dispositions") or {}
    todo, skipped = [], []
    for r in store.all("SELECT * FROM requirements ORDER BY seq"):
        if r["id"] in covered:
            continue
        over = (overrides.get(r["id"]) or {}).get("disposition") if isinstance(overrides.get(r["id"]), dict) else overrides.get(r["id"])
        if over in SKIP_DISPOSITIONS:
            skipped.append({"req_id": r["id"], "why": SKIP_DISPOSITIONS[over]})
            continue
        std = r["std"] or {}
        clar = std.get("clarification") or "clear"
        if clar != "clear":
            skipped.append({"req_id": r["id"], "why": f"waits for clarification ({clar}); its expected result is not "
                                                      "known yet"})
            continue
        todo.append(r)
    return todo, skipped


def generate(project: Project, store: Store, existing: list[dict]) -> list[dict]:
    if not (project.cfg.get("functional") or {}).get("enabled", True):
        return []
    todo, skipped = targets(project, store, existing)
    cat = _catalog(store)
    roles = list(project.roles())
    cases: list[dict] = []
    by_model: set[str] = set()
    if todo and (project.cfg.get("functional") or {}).get("llm_cases", True):
        from agentqa.ai.client import model_for
        llm = model_for(project, "casegen")
        if llm is not None and llm.available():
            lines = [{"path": p, "title": e["title"], "roles": sorted(e["roles"]), "clicks": sorted(e["clicks"])[:20],
                      "fields": dict(list(e["fields"].items())[:15])} for p, e in list(cat.items())[:40]]
            for i in range(0, min(len(todo), 30), 5):
                chunk = todo[i:i + 5]
                payload = {"test_types": TEST_TYPES, "roles": roles + ["anonymous"], "screens": lines,
                           "test_data_tokens": ["{mobile}", "{username}", "{email}", "{password}"],
                           "requirements": [{"id": r["id"], "text": r["text"], **{k: (r["std"] or {}).get(k) for k in (
                               "title", "category", "actors", "objective", "preconditions", "main_flow", "exceptions",
                               "expected_outcome", "acceptance_criteria", "business_rules")},
                               "written": {k: ((r["std"] or {}).get("written") or {}).get(k) for k in (
                                   "statement", "user_story", "steps", "acceptance_criteria", "exceptions")}}
                               for r in chunk]}
                try:
                    out = llm.chat_json(SYSTEM, "PAYLOAD:\n" + json.dumps(payload), max_tokens=3500) or {}
                except Exception as exc:  # noqa: BLE001
                    warn(f"[casegen] the model could not draft cases: {exc}")
                    break
                ids = {r["id"]: r for r in chunk}
                per: dict[str, int] = {}
                for c in out.get("cases") or []:
                    r = ids.get(c.get("req_id"))
                    if r is None or per.get(r["id"], 0) >= 4:
                        continue                    # every case must trace to a requirement it was asked about
                    case = _from_model(c, r, cat, roles)
                    if case:
                        per[r["id"]] = per.get(r["id"], 0) + 1
                        cases.append(case)
                        by_model.add(r["id"])
    for r in todo:
        if r["id"] not in by_model:
            cases.append(_from_std(r, roles))
    seen: set[str] = set()
    out_cases = []
    for c in cases:
        if c["key"] not in seen:
            seen.add(c["key"])
            out_cases.append(c)
    store.set_meta("casegen_skipped", skipped)
    live.emit("casegen", "summary", f"Test Case Generation agent: {len(out_cases)} case(s) for {len(todo)} requirement(s) "
              f"without a test ({len(by_model)} drafted by the model); {len(skipped)} requirement(s) left out with a reason",
              level="ok")
    return out_cases


def _role_for(std: dict, roles: list[str]) -> str:
    for a in std.get("actors") or []:
        if a in roles:
            return a
    return roles[0] if roles else "anonymous"


def _case(r: dict, title: str, role: str, steps: list[dict], *, scenario: str, test_type: str, priority: str,
          objective: str, preconditions: str, test_data: str, expected: str, by: str) -> dict:
    std = r["std"] or {}
    key = f"func:gen:{r['id']}:{slug(title, 40)}"
    return {"key": key, "type": "functional", "group": "functional", "title": title[:140], "role": role,
            "path": (std.get("screens") or ["/"])[0], "priority": P_OF.get(priority, "P2"), "rule_ids": [],
            "req_ids": [r["id"]], "oracle_source": "requirement",
            "params": {"module": "Requirements", "scenario": scenario, "preconditions": preconditions,
                       "steps_text": [s.get("text") or s.get("expect") or s["action"] for s in steps], "test_data": test_data,
                       "expected": expected, "steps": steps, "page_role": role, "fresh_login": False,
                       "sig": f"func:gen:{r['id']}:{slug(title, 30)}", "defect_title": f"{r['id']}: {title[:80]} - fails",
                       "severity": "High" if priority in ("Critical", "High") else "Medium", "test_type": test_type,
                       "objective": objective, "generated_by": by, "priority_name": priority}}


def _from_std(r: dict, roles: list[str]) -> dict:
    """No model: the standardised use case becomes intent steps and a verify step (run by the Visual QA agent)."""
    std = r["std"] or {}
    role = _role_for(std, roles)
    w = std.get("written") or {}
    if w.get("steps"):
        # the Requirement Writer's steps: what the people do becomes intent steps, what the system does is checked
        acts = [x for x in w["steps"] if str(x.get("actor") or "").lower() not in ("system", "the system", "portal")
                and not re.match(r"log ?in as", str(x.get("action") or ""), re.I)]
        flow = [str(x.get("action") or "") for x in acts if x.get("action")] or [w.get("statement") or r["text"]]
        sys_steps = [str(x.get("action")) for x in w["steps"] if str(x.get("actor") or "").lower() in ("system", "the system", "portal")]
        crit = (w.get("acceptance_criteria") or [])
        expected = (re.split(r"\bthen\b", crit[0], flags=re.I)[-1].strip(" ,.") if crit else "") or \
            (sys_steps[-1] if sys_steps else "") or w.get("statement") or r["text"]
    else:
        flow = [x for x in std.get("main_flow") or [] if not re.match(r"log ?in as", x, re.I)] or [r["text"]]
        expected = std.get("expected_outcome") or r["text"]
        if expected in ("The behaviour described is observed", ""):
            expected = r["text"]
    steps = [{"action": "intent", "text": x[:200]} for x in flow[:6]]
    steps.append({"action": "verify", "expect": expected[:300], "text": f"Check: {expected[:200]}"})
    from agentqa.contracts import _CATEGORY_TYPE
    return _case(r, std.get("title") or r["text"][:80], role, steps, scenario="Positive",
                 test_type=_CATEGORY_TYPE.get(std.get("category") or "", "Positive"), priority="Medium",
                 objective=std.get("objective") or (w.get("user_story") or "") or f"Confirm {r['id']} holds: {r['text'][:120]}",
                 preconditions="; ".join(std.get("preconditions") or []) or ("Logged in as " + role),
                 test_data="", expected=expected, by="rules")


def _from_model(c: dict, r: dict, cat: dict, roles: list[str]) -> dict | None:
    role = c.get("role") if c.get("role") in roles + ["anonymous"] else _role_for(r["std"] or {}, roles)
    clicks = {x.lower() for e in cat.values() for x in e["clicks"]}
    steps, last_path = [], None
    for st in c.get("steps") or []:
        a = st.get("action")
        if a == "intent" and st.get("text"):
            steps.append({"action": "intent", "text": str(st["text"])[:200]})
        elif a == "verify" and st.get("expect"):
            steps.append({"action": "verify", "expect": str(st["expect"])[:300], "text": f"Check: {str(st['expect'])[:200]}"})
        elif a in GROUNDED:
            ok = (a != "goto" or st.get("path") in cat) and \
                 (a != "click" or str(st.get("target", "")).strip().lower() in clicks) and \
                 (a != "fill" or str(st.get("field")) in (cat.get(st.get("path") or last_path or "") or {}).get("fields", {}))
            if a == "goto" and ok:
                last_path = st["path"]
            text = {"goto": f"Open {st.get('path')}", "click": f"Click '{st.get('target')}'",
                    "fill": f"Enter '{st.get('value')}' in '{st.get('field')}'"}.get(a, f"Check {st.get('value') or a}")
            if ok:
                steps.append({k: v for k, v in {"action": a, "path": st.get("path"), "target": st.get("target"),
                                                "field": st.get("field"), "value": st.get("value"), "text": text}.items()
                              if v is not None})
            else:
                steps.append({"action": "intent", "text": text})   # not on the app map: the Visual QA agent tries it
    expected = str(c.get("expected") or "").strip()
    if not steps:
        return None
    if not any(s["action"] == "verify" or s["action"].startswith("expect") for s in steps):
        if not expected:
            return None
        steps.append({"action": "verify", "expect": expected[:300], "text": f"Check: {expected[:200]}"})
    tt = c.get("test_type") if c.get("test_type") in TEST_TYPES else "Positive"
    pr = c.get("priority") if c.get("priority") in PRIORITIES else "Medium"
    return _case(r, str(c.get("title") or r["id"]), role, steps, scenario=str(c.get("scenario") or "Positive"),
                 test_type=tt, priority=pr, objective=str(c.get("objective") or ""),
                 preconditions=str(c.get("preconditions") or ""), test_data=str(c.get("test_data") or ""),
                 expected=expected or steps[-1].get("expect", ""), by="model")
