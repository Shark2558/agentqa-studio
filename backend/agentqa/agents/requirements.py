"""Requirement standardisation, completeness and traceability (the Requirement Analysis agent's second half).

standardise()  turns each extracted requirement into one structured record and a use case: module, title,
               category, objective, actor, preconditions, trigger, business rules, main / alternative / exception
               flows, expected outcome, dependencies, acceptance criteria, source reference, confidence and
               clarification status. Rules, the app map and the reconciler's verdicts fill it; with an AI key the
               model fills what the rules leave empty (marked as such).
check()        duplicates (near-identical text), contradictions (the same field or screen given different values),
               and a disposition per requirement: covered by tests, needs clarification, not testable, out of scope,
               or a gap. A person's disposition on the Requirements page overrides the automatic one.
rtm()          one row per requirement and test case: source document > requirement > use case > test case >
               execution > result > defect, with the disposition. Coverage is counted only from these rows, so
               nothing is claimed that was not traced and run.
"""
from __future__ import annotations

import json
import re

from agentqa import live
from agentqa.config import Project
from agentqa.store import Store
from agentqa.util import norm, similarity, warn

DISPOSITIONS = {"covered": "Covered by tests", "clarify": "Needs clarification", "not_testable": "Not testable",
                "out_of_scope": "Out of scope", "gap": "Gap: no test yet", "manual": "Manual test only"}
FIELD_KINDS = {"required", "max_length", "min_length", "exact_length", "length_range", "digits_only", "alpha_only",
               "format_email", "format_mobile", "starts_with", "numeric_range", "date_not_future", "options",
               "file_types", "file_max_size"}


def _rule_text(r: dict) -> str:
    v = (r.get("decided_value") if r.get("status") == "Decided" and r.get("decided_value") else r.get("value")) or {}
    f = r.get("field") or r.get("target") or ""
    k = r["kind"]
    return {
        "required": f"{f} is mandatory", "max_length": f"{f} at most {v.get('max')} characters",
        "min_length": f"{f} at least {v.get('min')} characters", "exact_length": f"{f} exactly {v.get('length')} characters",
        "length_range": f"{f} {v.get('min')}-{v.get('max')} characters", "digits_only": f"{f} digits only",
        "alpha_only": f"{f} letters only", "format_email": f"{f} a valid email address", "format_mobile": f"{f} a valid mobile number",
        "starts_with": f"{f} starts with {', '.join(v.get('chars') or [])}",
        "numeric_range": f"{f} between {v.get('min')} and {v.get('max')}", "date_not_future": f"{f} not a future date",
        "options": f"{f} offers {', '.join(v.get('options') or [])}", "file_types": f"{f} accepts {', '.join(v.get('types') or [])}",
        "file_max_size": f"{f} at most {v.get('kb')} KB", "access_only": f"only {', '.join(r.get('roles') or [])} may {f}",
        "access_deny": f"{', '.join(r.get('roles') or [])} may not {f}", "feature": f"{', '.join(r.get('roles') or []) or 'users'} can {f}",
        "status_transition": f"status becomes {v.get('status')}", "perf_max_load": f"pages load within {v.get('ms')} ms",
        "session_timeout": "the session expires after the stated idle time", "otp_single_use": "an OTP works only once",
    }.get(k, f"{k.replace('_', ' ')} {f}".strip())


def _title(text: str) -> str:
    t = re.sub(r"^(the|a|an)\s+", "", text.strip().rstrip("."), flags=re.I)
    t = re.split(r"[;,:]\s|\s(?:so that|in order to|which|where)\s", t)[0]
    words = t.split()
    return (" ".join(words[:12]) + ("…" if len(words) > 12 else "")).strip().capitalize()


def _category(req: dict, rules: list[dict]) -> str:
    kinds = {r["kind"] for r in rules}
    t = req["text"].lower()
    if req["kind"] == "field-spec" or kinds & FIELD_KINDS:
        return "Field validation"
    if kinds & {"access_only", "access_deny"}:
        return "Access control"
    if "status_transition" in kinds:
        return "Workflow"
    if re.search(r"\bapis?\b|\bhttp \d{3}\b|endpoint", t):
        return "Integration"
    if re.search(r"\blog ?in\b|otp|password|session|authenticat", t):
        return "Authentication"
    if kinds & {"perf_max_load"} or re.search(r"\bload(s|ed|ing)?\b|\brespond|performance|\bseconds?\b|concurrent", t):
        return "Performance"
    if re.search(r"secur|encrypt|csrf|xss|audit", t):
        return "Security"
    if re.search(r"accessib|wcag|screen reader", t):
        return "Accessibility"
    if re.search(r"language|usab|user[- ]friendly|intuitive", t):
        return "Usability"
    if re.search(r"email|sms|notif", t):
        return "Notification"
    if re.search(r"api|integrat|interface with|digilocker|payment gateway", t):
        return "Integration"
    return "Non-functional" if req["kind"] == "non-functional" else "Functional"


def standardise(project: Project, store: Store, use_llm: bool | None = None) -> dict:
    reqs = store.all("SELECT * FROM requirements ORDER BY seq")
    if not reqs:
        return {"requirements": 0}
    rules = store.all("SELECT * FROM rules ORDER BY id")
    by_req: dict[str, list] = {}
    for r in rules:
        by_req.setdefault(r["req_id"], []).append(r)
    titles = {s["path"]: s["title"] for s in store.all("SELECT path, title FROM screens")}
    open_q = {q["req_id"] for q in store.all("SELECT req_id FROM questions WHERE status='open'") if q["req_id"]}
    role_names = project.role_aliases()
    for req in reqs:
        rs = by_req.get(req["id"], [])
        low = req["text"].lower()
        actors = sorted(set(req["roles"] or []) | {x for r in rs for x in (r.get("roles") or [])},
                        key=lambda a: (low.find(a.lower()) if a.lower() in low else 10_000, a))
        screens = sorted({m.get("path") for r in rs for m in (r.get("matched") or []) if m.get("path")})
        screen_names = [f"{titles.get(p) or p} ({p})" for p in screens]
        brules = [_rule_text(r) for r in rs]
        cat = _category(req, rs)
        actor = actors[0] if actors else ("user" if cat not in ("Performance", "Security") else "system")
        trans = next((r for r in rs if r["kind"] == "status_transition"), None)
        feat = next((r for r in rs if r["kind"] == "feature"), None)
        flags = [f["term"] for f in (req["ambiguity"] or [])]
        trigger = (re.split(r",", req["text"])[0] if trans else
                   f"{actor.capitalize()} opens {screen_names[0]}" if screen_names else
                   f"{actor.capitalize()} uses the portal")
        pre = ([] if actor in ("user", "system") else [f"Logged in as {actor}"]) + \
              ([f"{titles.get(screens[0]) or screens[0]} is available to {actor}"] if screens else [])
        main = ([f"Log in as {actor}"] if actor not in ("user", "system") else []) + \
               ([f"Open {screen_names[0]}"] if screen_names else []) + \
               ([f"{(feat.get('target') or '').capitalize()}"] if feat and feat.get("target") else []) + \
               ([f"Perform the action ({trans.get('target', '')[:80]})"] if trans else [])
        if cat == "Authentication":
            who = ", ".join(actors) if actors else "each role"
            trigger = "A user opens the login page"
            pre = [f"A registered account for {who}", "Not logged in"]
            main = ["Open the login page", "Enter the login details", "Enter the OTP if one is asked for",
                    "Submit", "Reach the role's home page with a session"]
            exceptions = ["Wrong or missing details: refused with a message and no session",
                          "Wrong or expired OTP: refused", "Logout or idle timeout: the session ends"]
        if not main:
            main = [req["text"]]
        exceptions = [f"Invalid {r.get('field') or 'input'}: the system refuses it with a clear message"
                      for r in rs if r["kind"] in FIELD_KINDS and r["kind"] not in ("options",)][:6]
        if any(r["kind"] in ("access_only", "access_deny") for r in rs):
            exceptions.append("A role without permission is refused (access denied or sent to login)")
        expected = ("; ".join(brules[:4]) if brules else
                    "The user is signed in to the role's home page; wrong details are refused" if cat == "Authentication" else
                    "The behaviour described is observed" if not flags else "To be clarified (see questions)")
        criteria = []
        for r in rs[:8]:
            if r["kind"] in FIELD_KINDS:
                criteria.append(f"Given the form is open, when {r.get('field')} breaks '{_rule_text(r)}', then it is refused "
                                f"with an error; when it meets it, it is accepted")
            elif r["kind"] in ("access_only", "access_deny"):
                criteria.append(f"Given a role outside {', '.join(r.get('roles') or [])}, when it opens the screen, "
                                "then it is refused")
            elif r["kind"] == "status_transition":
                criteria.append(f"Given a submitted record, when {r.get('target', '')[:80].rstrip('.')}, then its status is "
                                f"{(r.get('value') or {}).get('status')} for every role that can see it")
            else:
                criteria.append(f"Given {actor}, then {_rule_text(r)}")
        clar = ("needs clarification: " + ", ".join(sorted(set(flags)))) if flags else \
            ("open question" if req["id"] in open_q else "clear")
        std = {
            "module": req["section"] or req["source_file"], "submodule": "",
            "title": _title(req["text"]), "description": req["text"], "category": cat,
            "objective": (f"Let {actor} {feat['target']}" if feat and feat.get("target") else
                          f"Keep the {cat.lower()} rule: {brules[0]}" if brules else ""),
            "actors": actors or [actor], "preconditions": pre, "trigger": trigger,
            "business_rules": brules, "main_flow": main, "alternative_flows": [], "exceptions": exceptions,
            "expected_outcome": expected, "dependencies": [], "acceptance_criteria": criteria,
            "screens": screens, "source": req.get("source_ref") or f"{req['source_file']} › {req['section'] or 'start'}",
            "confidence": ("rules and model" if any(r.get("source") == "llm" for r in rs) else "rules") if rs else "text only",
            "clarification": clar,
            "use_case": {"name": _title(req["text"]), "actor": actor, "preconditions": pre, "main_flow": main,
                         "exceptions": exceptions, "postconditions": expected},
        }
        old = req["std"] or {}
        if (old.get("written") or {}).get("src"):
            from agentqa.agents.req_writer import _src_hash
            if old["written"]["src"] == _src_hash(req["text"]):
                std["written"] = old["written"]       # the Requirement Writer's wording stays while the text is the same
        store.update("requirements", "id", req["id"], {"std": std})
    _dependencies(store)
    _enrich(project, store, use_llm)
    out = check(project, store)
    live.emit("analyst", "summary", f"Standardised {len(reqs)} requirement(s): {out['duplicates']} possible duplicate(s), "
              f"{out['contradictions']} contradiction(s)", level="ok")
    _ = role_names
    return out


def _dependencies(store: Store) -> None:
    """A requirement depends on others that act on the same screen or field, or that it names."""
    reqs = store.all("SELECT id, text, std FROM requirements ORDER BY seq")
    ids = {r["id"] for r in reqs}
    for r in reqs:
        std = r["std"] or {}
        deps = {x for x in re.findall(r"\b[A-Z]{1,5}-\d+(?:\.\d+)?\b", r["text"]) if x in ids and x != r["id"]}
        for o in reqs:
            if o["id"] == r["id"]:
                continue
            if set((std.get("screens") or [])) & set(((o["std"] or {}).get("screens") or [])):
                if (o["std"] or {}).get("category") in ("Functional", "Workflow") and std.get("category") in (
                        "Workflow", "Field validation", "Notification"):
                    deps.add(o["id"])
        std["dependencies"] = sorted(deps)[:8]
        store.update("requirements", "id", r["id"], {"std": std})


ENRICH = """You are a senior business analyst. For each requirement, fill the standard fields that are empty, using
only what the requirement and the screens say. Reply with JSON:
{"items": [{"id": "...", "objective": "...", "trigger": "...", "main_flow": ["..."], "alternative_flows": ["..."],
"exceptions": ["..."], "expected_outcome": "...", "acceptance_criteria": ["Given ..., when ..., then ..."]}]}"""


def _enrich(project: Project, store: Store, use_llm: bool | None) -> None:
    if use_llm is False:
        return
    from agentqa.ai.client import model_for
    llm = model_for(project, "requirements")
    if not llm or not llm.available():
        return
    reqs = store.all("SELECT id, text, std FROM requirements ORDER BY seq")
    for i in range(0, min(len(reqs), 80), 8):
        chunk = reqs[i:i + 8]
        out = llm.chat_json(ENRICH, json.dumps([{"id": r["id"], "text": r["text"], "category": (r["std"] or {}).get("category"),
                                                 "screens": (r["std"] or {}).get("screens")} for r in chunk]),
                            max_tokens=2500) or {}
        for item in out.get("items") or []:
            r = next((x for x in chunk if x["id"] == item.get("id")), None)
            if not r:
                continue
            std = r["std"] or {}
            filled = []
            for k in ("objective", "trigger", "main_flow", "alternative_flows", "exceptions", "expected_outcome",
                      "acceptance_criteria"):
                v = item.get(k)
                if v and (not std.get(k) or k in ("alternative_flows",)):
                    std[k] = v
                    filled.append(k)
            if filled:
                std["enriched_by_model"] = filled
                std.setdefault("use_case", {}).update({k: std[k] for k in ("main_flow", "alternative_flows", "exceptions")
                                                       if k in filled})
                store.update("requirements", "id", r["id"], {"std": std})


def check(project: Project, store: Store) -> dict:
    """Duplicates, contradictions and dispositions."""
    reqs = store.all("SELECT * FROM requirements ORDER BY seq")
    rules = store.all("SELECT * FROM rules ORDER BY id")
    dup_pairs = []
    for i, a in enumerate(reqs):
        for b in reqs[i + 1:]:
            if a["kind"] == "field-spec" and b["kind"] == "field-spec":
                continue
            if similarity(a["text"], b["text"]) >= 0.88 and norm(a["text"]) != "":
                dup_pairs.append((a["id"], b["id"]))
    contradictions = []
    groups: dict[tuple, dict] = {}
    for r in rules:
        if r["kind"] not in FIELD_KINDS | {"perf_max_load"} or not r.get("value"):
            continue
        key = (r["kind"], norm(r.get("field") or r.get("target") or ""))
        groups.setdefault(key, {}).setdefault(json.dumps(r["value"], sort_keys=True), set()).add(r["req_id"])
    for (kind, field), vals in groups.items():
        if len(vals) > 1:
            ids = sorted({x for v in vals.values() for x in v})
            contradictions.append({"kind": kind, "field": field, "values": {k: sorted(v) for k, v in vals.items()}, "reqs": ids})
    from agentqa.agents.reconciler import _ask
    for c in contradictions:
        _ask(store, f"contradiction:{c['kind']}:{c['field']}", "ambiguous",
             f"The SRS gives different values for {c['field']} ({c['kind'].replace('_', ' ')}): " +
             "; ".join(f"{', '.join(ids)} say {v}" for v, ids in c["values"].items()) + ". Which one is right?",
             req_id=c["reqs"][0], priority="High")
    overrides = store.get_meta("req_dispositions") or {}
    case_reqs: dict[str, list] = {}
    for c in store.all("SELECT id, req_ids FROM cases"):
        for r in c["req_ids"] or []:
            case_reqs.setdefault(r, []).append(c["id"])
    by_req = {}
    for r in rules:
        by_req.setdefault(r["req_id"], []).append(r)
    open_q = {q["req_id"] for q in store.all("SELECT req_id FROM questions WHERE status='open'") if q["req_id"]}
    counts = {k: 0 for k in DISPOSITIONS}
    for req in reqs:
        std = req["std"] or {}
        std["duplicates"] = sorted({b for a, b in dup_pairs if a == req["id"]} | {a for a, b in dup_pairs if b == req["id"]})
        std["contradictions"] = [c for c in contradictions if req["id"] in c["reqs"]]
        rs = by_req.get(req["id"], [])
        if req["id"] in overrides:
            disp, note = overrides[req["id"]]["disposition"], overrides[req["id"]].get("note", "")
        elif case_reqs.get(req["id"]):
            disp, note = "covered", f"{len(case_reqs[req['id']])} test case(s)"
        elif std["contradictions"] or req["id"] in open_q or any(r["status"] in ("Ambiguous", "Divergent", "Proposed") for r in rs):
            disp, note = "clarify", "an open question or contradiction must be answered first"
        elif any(r["status"] == "Not automated" for r in rs) or (req["ambiguity"] and not rs):
            disp, note = "not_testable", "vague wording with no measurable rule: " + ", ".join(
                f["term"] for f in (req["ambiguity"] or []))[:120]
        elif any(r["status"] == "SRS-only" for r in rs):
            disp, note = "gap", "the SRS describes something the portal does not show: answer the question to log a defect or drop it"
        else:
            disp, note = "gap", "no test case traces to it yet"
        counts[disp] = counts.get(disp, 0) + 1
        store.update("requirements", "id", req["id"], {"std": std, "disposition": disp, "disposition_note": note})
    return {"requirements": len(reqs), "duplicates": len(dup_pairs), "contradictions": len(contradictions), **counts}


def set_disposition(store: Store, req_id: str, disposition: str, note: str = "") -> None:
    if disposition not in DISPOSITIONS:
        raise ValueError(disposition)
    ov = store.get_meta("req_dispositions") or {}
    ov[req_id] = {"disposition": disposition, "note": note}
    store.set_meta("req_dispositions", ov)
    store.update("requirements", "id", req_id, {"disposition": disposition, "disposition_note": note})
    from agentqa.store import now
    store.insert("change_log", {"at": now(), "agent": "person", "object": "requirement", "object_id": req_id,
                                "change": f"disposition set to {DISPOSITIONS[disposition]}", "justification": note,
                                "by": "dashboard"})


def rtm(project: Project, store: Store) -> list[dict]:
    """Source > requirement > use case > test case > execution > result > defect, one row per requirement and case."""
    designed = store.scalar("SELECT MIN(created_at) FROM cases") or ""
    last: dict[str, dict] = {}
    for r in store.all("SELECT r.*, u.started_at run_started FROM results r JOIN runs u ON u.id = r.run_id "
                       "WHERE u.started_at >= ? ORDER BY u.started_at, r.rowid", [designed]):
        last[r["case_id"]] = r
    defects: dict[str, list] = {}
    for d in store.all("SELECT id, case_ids, status FROM defects WHERE status != 'rejected'"):
        for c in d["case_ids"] or []:
            defects.setdefault(c, []).append(f"{d['id']} ({d['status']})")
    cases_by_req: dict[str, list] = {}
    for c in store.all("SELECT id, title, type, req_ids, status FROM cases ORDER BY seq"):
        for r in c["req_ids"] or []:
            cases_by_req.setdefault(r, []).append(c)
    rows = []
    status_word = {"pass": "Passed", "defect": "Failed", "blocked": "Blocked", "not-run": "Not run", "test-issue": "Test issue",
                   "visual-change": "Visual change", "environment": "Environment problem", "skipped": "Skipped"}
    for req in store.all("SELECT * FROM requirements ORDER BY seq"):
        std = req["std"] or {}
        base = {"source": std.get("source") or req.get("source_ref") or req["source_file"], "req_id": req["id"],
                "requirement": req["text"], "title": std.get("title") or "", "category": std.get("category") or "",
                "use_case": (std.get("use_case") or {}).get("name") or "", "disposition": DISPOSITIONS.get(req["disposition"] or "gap", ""),
                "note": req["disposition_note"] or ""}
        cs = cases_by_req.get(req["id"], [])
        if not cs:
            rows.append({**base, "case_id": "", "case": "", "executed": "", "result": "", "defects": ""})
        for c in cs:
            res = last.get(c["id"])
            rows.append({**base, "case_id": c["id"], "case": c["title"], "executed": (res or {}).get("started_at") or
                         ((res or {}).get("run_started") or ""), "result": status_word.get((res or {}).get("category"), "Not run")
                         if c["status"] == "approved" else f"Not approved ({c['status']})",
                         "defects": ", ".join(defects.get(c["id"], []))})
    return rows


def coverage(project: Project, store: Store) -> dict:
    """Honest coverage: counted from traced and executed cases; unread documents and unexplained text are shown."""
    rows = rtm(project, store)
    reqs: dict[str, dict] = {}
    for r in rows:
        e = reqs.setdefault(r["req_id"], {"disp": r["disposition"], "results": []})
        if r["case_id"]:
            e["results"].append(r["result"])
    out = {"requirements": len(reqs), "with_tests": 0, "all_passed": 0, "failing": 0, "blocked_or_not_run": 0,
           "clarify": 0, "not_testable": 0, "out_of_scope": 0, "gaps": 0}
    for e in reqs.values():
        res = e["results"]
        if res:
            out["with_tests"] += 1
            if "Failed" in res:
                out["failing"] += 1
            elif all(x == "Passed" for x in res):
                out["all_passed"] += 1
            else:
                out["blocked_or_not_run"] += 1
        elif e["disp"] == DISPOSITIONS["clarify"]:
            out["clarify"] += 1
        elif e["disp"] == DISPOSITIONS["not_testable"]:
            out["not_testable"] += 1
        elif e["disp"] == DISPOSITIONS["out_of_scope"]:
            out["out_of_scope"] += 1
        else:
            out["gaps"] += 1
    out["documents_not_fully_read"] = store.all("SELECT name, status, detail FROM documents WHERE status != 'read'")
    out["possibly_missed"] = store.scalar("SELECT COUNT(*) FROM segments WHERE disposition='possibly missed'") or 0
    out["complete"] = (out["gaps"] == 0 and not out["documents_not_fully_read"] and out["possibly_missed"] == 0
                       and out["blocked_or_not_run"] == 0 and out["clarify"] == 0)
    return out


def write_rtm(project: Project, store: Store) -> tuple[str, str]:
    import csv
    rows = rtm(project, store)
    head = ["source", "req_id", "requirement", "title", "category", "use_case", "case_id", "case", "executed", "result",
            "defects", "disposition", "note"]
    names = ["Source document", "Requirement ID", "Requirement", "Standard title", "Category", "Use case", "Test case ID",
             "Test case", "Executed", "Result", "Defects", "Disposition", "Note"]
    csv_path = project.reports_dir / "rtm.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(names)
        for r in rows:
            w.writerow([r.get(k, "") for k in head])
    xlsx_path = project.reports_dir / "rtm.xlsx"
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        wb = Workbook()
        ws = wb.active
        ws.title = "Traceability"
        ws.append(names)
        for i, wdt in enumerate([30, 12, 50, 34, 16, 34, 11, 44, 18, 12, 18, 20, 36], 1):
            ws.column_dimensions[get_column_letter(i)].width = wdt
            ws.cell(row=1, column=i).font = Font(bold=True, color="FFFFFF")
            ws.cell(row=1, column=i).fill = PatternFill("solid", fgColor="1D4ED8")
        fills = {"Passed": "DCFCE7", "Failed": "FEE2E2", "Blocked": "FEF3C7", "Not run": "F1F5F9"}
        for r in rows:
            ws.append([r.get(k, "") for k in head])
            for c in ws[ws.max_row]:
                c.alignment = Alignment(vertical="top", wrap_text=True)
            if r.get("result") in fills:
                ws.cell(row=ws.max_row, column=10).fill = PatternFill("solid", fgColor=fills[r["result"]])
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = f"A1:M{ws.max_row}"
        cov = coverage(project, store)
        sm = wb.create_sheet("Coverage")
        for k, v in cov.items():
            if not isinstance(v, (list, dict)):
                sm.append([k.replace("_", " ").capitalize(), v])
        for d in cov["documents_not_fully_read"]:
            sm.append(["Document not fully read", f"{d['name']}: {d['status']} - {d['detail']}"])
        wb.save(xlsx_path)
    except Exception as exc:  # noqa: BLE001
        warn(f"could not write rtm.xlsx: {exc}")
    return str(csv_path), str(xlsx_path)
