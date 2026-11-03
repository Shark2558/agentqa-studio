"""Assistant: ask AgentQA about requirements, tests, results and defects in plain language.

It answers from the project's own records and always shows where an answer came
from (requirement, test case, defect). Common questions and commands are handled
by fixed rules, so it works with no AI model at all:

  "how ready is this release?"           "show critical defects"
  "why did TC-0016 fail?"                 "explain FR-05"
  "what is not tested?"                   "what questions are open?"
  "add a test that clerk cannot open /admin/users"
  "re-run the failed tests"

When the optional local model is on, questions the rules do not cover are
answered by the model from the most relevant records, which are listed with
the answer.
"""
from __future__ import annotations

import re

from agentqa import readiness
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import similarity, tokens

SUGGESTIONS = ["How ready is this release?", "Show critical and high defects", "What failed in the last run?",
               "What is not tested yet?", "What questions are open?", "Explain FR-05",
               "Add a test that clerk cannot open /admin/users", "Re-run the failed tests"]
SEV = ["Critical", "High", "Medium", "Low"]


def _item(title, detail="", link=None, tag=None) -> dict:
    return {"title": title, "detail": detail, "link": link, "tag": tag}


def answer(project: Project, store: Store, question: str) -> dict:
    q = (question or "").strip()
    store.insert("chat", {"who": "user", "text": q, "data": None, "created_at": now()})
    try:
        out = _route(project, store, q)
    except Exception as exc:  # noqa: BLE001
        out = {"text": f"Something went wrong while answering: {exc}", "items": [], "actions": [], "source": "error"}
    out.setdefault("items", [])
    out.setdefault("actions", [])
    out.setdefault("source", "records")
    store.insert("chat", {"who": "assistant", "text": out["text"], "data": out, "created_at": now()})
    return out


def as_text(out: dict) -> str:
    lines = [out["text"]]
    for it in out.get("items", []):
        lines.append(f"  - {it['title']}" + (f": {it['detail']}" if it.get("detail") else ""))
    for a in out.get("actions", []):
        lines.append(f"  [{a['label']}]")
    return "\n".join(lines)


def _route(project: Project, store: Store, q: str) -> dict:
    low = q.lower()
    if not q or re.fullmatch(r"(hi|hello|hey|help|\?|what can you do\??|how do i use (this|you)\??)[.!]*", low):
        return {"text": "I answer from this project's requirements, tests, results and defects, and I can add simple "
                        "access tests or start runs. Try one of these:", "suggestions": SUGGESTIONS}
    if re.search(r"\b(add|create|write|make)\b.*\btest\b|^(make sure|ensure|check|verify) (that )?.+\b(can|cannot|can't|can not|must not|should not)\b", low):
        return _add_test(project, store, q)
    if re.match(r"(please |can you |could you |now )?(re-?run|run|execute|start|retest|re-?test)\b", low) \
            and re.search(r"\btests?\b|\bsuite\b|tc-\d{4}|\bfail", low):
        return _run(store, q)
    m = re.search(r"\btc-\d{4}\b", low)
    if m:
        return _case(store, m.group(0).upper())
    m = re.search(r"\bdef-\d{3}\b", low)
    if m:
        return _defect(store, m.group(0).upper())
    m = re.search(r"\b(fr|nfr|tbl|srs|br|req)-\d+\b", low)
    if m:
        return _requirement(store, m.group(0).upper())
    if re.search(r"\b(ready|readiness|release|status|summary|overview|how (are|is) (we|it|things|the build))\b|last run", low) \
            and not re.search(r"\bdefects?\b|\bbugs?\b|\bfail\w*|\bbroken\b", low):
        return _status(project, store)
    if re.search(r"\b(questions?|clarif\w*|need from me|waiting on me|answer)\b", low):
        return _questions(store)
    if re.search(r"\b(not (yet )?tested|untested|uncovered|coverage|without tests?|missing tests?)\b", low):
        return _coverage(store)
    if re.search(r"\b(visual|snapshots?|look(s)? different|layout)\b", low):
        return _visual(store)
    if re.search(r"\bapis?\b|\bendpoints?\b", low):
        return _apis(store)
    if re.search(r"\b(defects?|bugs?|issues?|problems?|vulnerabilit\w+)\b", low):
        return _defects(store, low)
    if re.search(r"\b(fail\w*|broken)\b", low):
        return _failures(store)
    return _search(project, store, q)


# ---------------------------------------------------------------------------

def _status(project: Project, store: Store) -> dict:
    r = readiness.compute(project, store)
    run = store.one("SELECT * FROM runs WHERE id=?", [r["run_id"]]) if r["run_id"] else None
    if not run:
        return {"text": "Nothing has run yet. Start the pipeline from the Pipeline page.", "items": []}
    text = (f"Release readiness is {r['score']}/100: {r['verdict']}. The latest run ({run['id']}) had "
            f"{run['passed']} of {run['total']} tests passing, {run['failed']} failing on defects"
            + (f" and {run['errors']} test issue(s)" if run["errors"] else "") + ".")
    return {"text": text, "items": [_item(x) for x in r["reasons"]],
            "actions": [{"label": "Show open defects", "kind": "ask", "question": "Show critical and high defects"}]}


def _defects(store: Store, low: str) -> dict:
    sevs = [s for s in SEV if s.lower() in low]
    rows = store.all("SELECT * FROM defects WHERE status NOT IN ('rejected','resolved') ORDER BY seq")
    rows.sort(key=lambda d: (SEV.index(d["severity"]), d["seq"]))
    if sevs:
        rows = [d for d in rows if d["severity"] in sevs]
    words = [w for w in re.findall(r"/[\w/{}-]+|\b[a-z]{4,}\b", low)
             if w not in ("show", "list", "defects", "defect", "bugs", "issues", "open", "what", "which", "critical",
                          "high", "medium", "with", "there", "are", "the", "about", "found", "problems", "security")]
    if "security" in low:
        rows = [d for d in rows if re.search(r"security|session|csrf|access|isolation|records|login|html", d["title"], re.I)]
    for w in words:
        sub = [d for d in rows if w in (d["title"] + d["url"]).lower()]
        if sub:
            rows = sub
    if not rows:
        return {"text": "No open defects match that." + (" Triage has not run yet." if not store.scalar(
            "SELECT COUNT(*) FROM defects") else ""), "items": []}
    return {"text": f"{len(rows)} open defect(s)" + (f" at {' or '.join(s.lower() for s in sevs)} severity" if sevs else "")
                    + ". Each one is a draft until someone confirms it on the Defects page.",
            "items": [_item(f"{d['id']} {d['title']}", f"{d['role']} - {d['actual'][:160]}", "defects", d["severity"])
                      for d in rows[:12]]}


def _failures(store: Store) -> dict:
    run_id = store.get_meta("last_run")
    rows = store.all("SELECT r.*, c.title, c.type FROM results r JOIN cases c ON c.id=r.case_id "
                     "WHERE r.run_id=? AND r.outcome!='passed' ORDER BY r.case_id", [run_id]) if run_id else []
    if not rows:
        return {"text": "Nothing failed in the latest run." if run_id else "Nothing has run yet.", "items": []}
    cats = {}
    for r in rows:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    text = (f"{len(rows)} test(s) did not pass in {run_id}: "
            + ", ".join(f"{n} {k.replace('-', ' ')}" for k, n in cats.items()) + ".")
    return {"text": text, "items": [_item(f"{r['case_id']} {r['title']}",
                                          re.sub(r"^\w+Error: (DEFECT: )?", "", r["message"] or "")[:170], "results",
                                          r["category"]) for r in rows[:15]],
            "actions": [{"label": "Re-run these tests", "kind": "run", "only": [r["case_id"] for r in rows]}]}


def _case(store: Store, cid: str) -> dict:
    c = store.one("SELECT * FROM cases WHERE id=?", [cid])
    if not c:
        return {"text": f"There is no test {cid}.", "items": []}
    run_id = store.get_meta("last_run")
    r = store.one("SELECT * FROM results WHERE run_id=? AND case_id=?", [run_id, cid]) if run_id else None
    oracle = {"srs": "the SRS", "decided": "a decision recorded in the clarification queue", "workflow": "a workflow in project.yaml",
              "baseline": "a baseline rule every portal should meet", "snapshot": "the approved visual snapshot",
              "manual": "an imported manual test case"}.get(c["oracle_source"], c["oracle_source"])
    text = f"{cid}: {c['title']}. It runs as {c['role']} and its expected result comes from {oracle}."
    items = []
    if c["req_ids"]:
        reqs = store.all(f"SELECT id, text FROM requirements WHERE id IN ({','.join('?' * len(c['req_ids']))})", c["req_ids"])
        items += [_item(q["id"], q["text"], "srs", "requirement") for q in reqs]
    if r:
        msg = re.sub(r"^\w+Error: (DEFECT: )?", "", r["message"] or "")
        items.append(_item(f"Latest result: {r['outcome']} ({r['category']})", msg[:300], "results", r["category"]))
        d = next((d for d in store.all("SELECT * FROM defects") if cid in (d["case_ids"] or [])), None)
        if d:
            items.append(_item(f"{d['id']} {d['title']}", d["status"], "defects", d["severity"]))
    return {"text": text, "items": items, "actions": [{"label": f"Re-run {cid}", "kind": "run", "only": [cid]}]}


def _defect(store: Store, did: str) -> dict:
    d = store.one("SELECT * FROM defects WHERE id=?", [did])
    if not d:
        return {"text": f"There is no defect {did}.", "items": []}
    return {"text": f"{did} ({d['severity']}, {d['status']}): {d['title']}.",
            "items": [_item("Expected", d["expected"][:300]), _item("Actual", d["actual"][:300]),
                      _item("Steps", d["steps"].replace("\n", " / ")[:300]),
                      _item("Tests", ", ".join(d["case_ids"] or []) or "found by the Exploratory Tester")]}


def _requirement(store: Store, rid: str) -> dict:
    req = store.one("SELECT * FROM requirements WHERE id=?", [rid])
    if not req:
        return {"text": f"There is no requirement {rid} in the SRS that was read.", "items": []}
    rules = store.all("SELECT * FROM rules WHERE req_id=?", [rid])
    cases = [c for c in store.all("SELECT id, title, req_ids FROM cases") if rid in (c["req_ids"] or [])]
    run_id = store.get_meta("last_run")
    res = {r["case_id"]: r for r in store.all("SELECT case_id, outcome, category FROM results WHERE run_id=?", [run_id])} \
        if run_id else {}
    text = f"{rid}: {req['text']}"
    if req["ambiguity"]:
        text += " The SRS wording is unclear here: " + "; ".join(a["reason"] for a in req["ambiguity"]) + "."
    items = [_item(f"Rule: {r['kind'].replace('_', ' ')}" + (f" on {r['field']}" if r["field"] else ""),
                   f"{r['status']}" + (f" - {r['status_note']}" if r["status_note"] else ""), "srs", r["status"])
             for r in rules]
    items += [_item(f"{c['id']} {c['title']}", (res.get(c["id"]) or {}).get("category", "not run"), "plan",
                    (res.get(c["id"]) or {}).get("category")) for c in cases]
    if not cases:
        items.append(_item("No test covers this requirement yet",
                           "usually because a rule behind it waits for an answer, or it describes behaviour the app "
                           "does not show"))
    return {"text": text, "items": items}


def _coverage(store: Store) -> dict:
    reqs = store.all("SELECT id, text FROM requirements ORDER BY seq")
    covered = {x for c in store.all("SELECT req_ids FROM cases") for x in (c["req_ids"] or [])}
    missing = [r for r in reqs if r["id"] not in covered]
    items = []
    for r in missing:
        statuses = sorted({x["status"] for x in store.all("SELECT status FROM rules WHERE req_id=?", [r["id"]])})
        why = ("rules: " + ", ".join(statuses)) if statuses else "no testable rule was found in the text"
        items.append(_item(r["id"], f"{r['text'][:140]} ({why})", "srs"))
    return {"text": f"{len(reqs) - len(missing)} of {len(reqs)} requirements have tests. {len(missing)} do not:",
            "items": items}


def _questions(store: Store) -> dict:
    rows = store.all("SELECT * FROM questions WHERE status='open' ORDER BY priority, id")
    if not rows:
        return {"text": "No questions are waiting for you.", "items": []}
    return {"text": f"{len(rows)} question(s) wait for your answer. Rules behind them are not tested until answered.",
            "items": [_item(f"#{q['id']}", q["question"], "questions", q["priority"]) for q in rows[:12]]}


def _visual(store: Store) -> dict:
    rows = store.all("SELECT * FROM visual ORDER BY status, key")
    if not rows:
        return {"text": "No visual snapshots yet. They are taken when the suite runs.", "items": []}
    changed = [r for r in rows if r["status"] == "changed"]
    return {"text": f"{len(rows)} screen snapshot(s); {len(changed)} changed since they were approved.",
            "items": [_item(f"{r['role']} {r['path']}", f"{(r['diff_ratio'] or 0):.2%} of pixels differ", "visual", "changed")
                      for r in changed]}


def _apis(store: Store) -> dict:
    rows = store.all("SELECT pattern, GROUP_CONCAT(DISTINCT CASE WHEN source='traffic' THEN role END) roles, MAX(documented) doc FROM endpoints "
                     "WHERE status BETWEEN 200 AND 299 GROUP BY pattern ORDER BY pattern")
    return {"text": f"{len(rows)} API endpoint(s) answered during exploration. Each gets a check of its answer, "
                    "its login and role protection, and record isolation where it takes an ID.",
            "items": [_item(f"GET {r['pattern']}", f"called by the screens of: {r['roles'] or 'none (found in the API description)'}" + (" - documented" if r["doc"] else ""),
                            "apis") for r in rows]}


def _run(store: Store, q: str) -> dict:
    ids = re.findall(r"tc-\d{4}", q.lower())
    if ids:
        only = [i.upper() for i in ids]
    elif re.search(r"\bfail", q.lower()):
        run_id = store.get_meta("last_run")
        only = [r["case_id"] for r in store.all("SELECT case_id FROM results WHERE run_id=? AND outcome!='passed'",
                                                [run_id])] if run_id else []
        if not only:
            return {"text": "Nothing failed in the latest run, so there is nothing to re-run.", "items": []}
    else:
        only = []
    label = f"Run {len(only)} test(s)" if only else "Run the whole approved suite"
    return {"text": f"Ready to start: {label.lower()}. Press the button to start it and watch it in Live View.",
            "actions": [{"label": label, "kind": "run", "only": only}]}


def _add_test(project: Project, store: Store, q: str) -> dict:
    from agentqa.agents.importer import Context
    ctx = Context(project, store)
    low = q.lower()
    neg = re.search(r"\b(cannot|can't|can not|must not|should not|is not able to|isn't able to|not allowed to|blocked from)\b", low)
    pos = re.search(r"\b(can|is able to|should be able to|must be able to)\b", low)
    m = re.search(r"(?:open|access|see|view|reach|visit|use|from)\s+(?:the\s+)?(.+?)[.?!]*$", q, re.I)
    role = None
    for part in re.split(r"\b(?:cannot|can't|can not|must not|should not|can|is able to|should be able to)\b", q, maxsplit=1, flags=re.I)[:1]:
        role = ctx.role_of(part)
    path = ctx.screen(m.group(1)) if m else None
    if not role or not path or not (neg or pos):
        return {"text": "I can add access tests in this form: \"add a test that <role> cannot open <screen or path>\" "
                        "or \"<role> can open <screen>\". Other kinds of tests come from the SRS or the Excel import.",
                "suggestions": ["Add a test that clerk cannot open /admin/users", "Add a test that citizen can open My Applications"]}
    n = (store.scalar("SELECT COUNT(*) FROM manual_cases WHERE id LIKE 'CHAT-%'") or 0) + 1
    cid = f"CHAT-{n:03d}"
    name = ctx.by_path.get(path, {}).get("name") or path
    who = "anonymous visitor" if role == "anonymous" else role
    steps = [{"text": f"Open {path}", "action": "goto", "path": path, "ok": True}]
    if neg:
        title = f"{who.capitalize()} cannot open {name} ({path})"
        steps.append({"text": "Access is denied", "action": "expect_denied", "ok": True})
    else:
        title = f"{who.capitalize()} can open {name} ({path})"
        steps.append({"text": f"The {name} page is shown", "action": "expect_page", "value": name, "ok": True})
    store.insert("manual_cases", {"id": cid, "title": title, "role": role, "steps": q, "expected": steps[-1]["text"],
                                  "converted": {"role": role, "start": path, "steps": steps, "coverage": 1.0,
                                                "req_ids": []},
                                  "coverage": 1.0, "status": "approved", "source_file": "assistant", "created_at": now()})
    return {"text": f"Added {cid}: {title}. It joins the test plan the next time the Designer runs, as a proposed case "
                    "for approval.",
            "items": [_item(cid, title, "imports", "added")],
            "actions": [{"label": "Re-plan now", "kind": "stage", "stage": "design"}]}


def _search(project: Project, store: Store, q: str) -> dict:
    qt = tokens(q)
    pool = []
    for r in store.all("SELECT id, text FROM requirements"):
        pool.append(("requirement", r["id"], r["text"], "srs"))
    for d in store.all("SELECT id, title, actual, severity FROM defects WHERE status NOT IN ('rejected')"):
        pool.append(("defect", d["id"], d["title"] + ". " + (d["actual"] or "")[:200], "defects"))
    for c in store.all("SELECT id, title FROM cases"):
        pool.append(("test", c["id"], c["title"], "plan"))
    scored = []
    for kind, rid, text, link in pool:
        t = tokens(text)
        s = len(qt & t) / (len(qt) or 1) + 0.3 * similarity(q, text)
        if s > 0.25:
            scored.append((s, kind, rid, text, link))
    scored.sort(reverse=True)
    top = scored[:8]
    items = [_item(f"{rid} ({kind})", text[:180], link, kind) for _, kind, rid, text, link in top]
    from agentqa.ai.client import model_for
    llm = model_for(project, "assistant")
    if llm and llm.available() and top:
        context = "\n".join(f"[{rid}] {text}" for _, _, rid, text, _ in top)
        out = llm.chat_json("You answer questions about a software test project using ONLY the records given. "
                            "Cite record IDs in square brackets. If the records do not answer it, say so. "
                            'Return JSON {"answer": "..."} in under 120 words.',
                            f"Records:\n{context}\n\nQuestion: {q}", 400)
        if out and out.get("answer"):
            return {"text": str(out["answer"]), "items": items, "source": "model"}
    if not top:
        return {"text": "I could not find anything about that in this project. Try one of these:",
                "suggestions": SUGGESTIONS}
    return {"text": "These records match your question best" + ("" if llm else " (turn on AI for this project on its AI page "
                    "for written answers)") + ":", "items": items}
