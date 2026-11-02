"""Reconciler agent: the three-source truth model.

Compares what the SRS says with what the Explorer saw, then gives every rule
one status:
  Confirmed   SRS and app agree (or the app is silent): becomes a test oracle
  Divergent   SRS and app disagree: question, or decided by policy
  SRS-only    SRS mentions something the app does not seem to have: question
  App-only    App has something the SRS never mentions: question
  Ambiguous   SRS wording cannot be tested as written: question
  Decided     a person (or policy) chose the truth: becomes a test oracle
  Workflow    a status change, covered by a multi-role workflow
  Not automated / Rejected / Missing in app

Answers are stored by a stable key, so re-running analysis keeps them.
"""
from __future__ import annotations

import json
import re

from agentqa import live
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import containment, norm, similarity, tokens

FIELD_KINDS = {"required", "max_length", "min_length", "exact_length", "length_range", "digits_only",
               "alpha_only", "format_email", "format_mobile", "starts_with", "numeric_range",
               "date_not_future", "options", "tbd", "file_types", "file_max_size"}
GENERIC_TITLES = {"home", "dashboard", "help", "login", "not found", "access denied", "search"}

OPTIONS = {
    "divergence": ["SRS is correct (the app has a defect)", "App is correct (update the SRS)",
                   "Neither: I will enter the correct value"],
    "srs_only_field": ["Missing from the app (log a defect)", "Exists under another name: enter it",
                       "Not applicable: drop the rule"],
    "srs_only_feature": ["Missing from the app (log a defect)", "Exists elsewhere: enter the page path",
                         "Out of scope for this release"],
    "srs_only_screen": ["Missing from the app (log a defect)", "Exists elsewhere: enter the page path",
                        "Out of scope for this release"],
    "ambiguous": ["Use the proposed interpretation (manual check)", "Enter a precise rule",
                  "Not testable: leave for manual review"],
    "app_only": ["Expected: test them as the app declares", "Unexpected (log a defect)", "Ignore"],
    "inferred_access": ["Yes: block these roles", "No: they may open it"],
    "llm_rule": ["Confirm the model's rule", "Reject it"],
    "workflow": ["I will describe the flow in project.yaml (workflows)", "Leave for manual testing"],
}


# ---------------------------------------------------------------------------
# App indexes
# ---------------------------------------------------------------------------

def reachable(screen: dict, project: Project) -> bool:
    final = project.rel(screen.get("final_url") or "")
    if screen["status"] in (401, 403) or (screen["status"] or 0) >= 400 and screen["status"] != 500:
        return False
    if project.is_login_path(final) and not project.is_login_path(screen["path"]):
        return False
    if norm(screen.get("title")) in ("access denied",):
        return False
    return True


def app_index(project: Project, store: Store):
    screens = store.all("SELECT * FROM screens ORDER BY id")
    by_path: dict[str, dict] = {}
    link_text: dict[str, set] = {}
    for s in screens:
        for link in s["links"] or []:
            path = project.rel(link["href"]) or "/"
            link_text.setdefault(path, set()).add(link["text"])
    for s in screens:
        entry = by_path.setdefault(s["path"], {"path": s["path"], "title": s["title"], "headings": s["headings"],
                                               "roles": [], "blocked": [], "status": s["status"],
                                               "buttons": set()})
        if s["title"] and not entry["title"]:
            entry["title"] = s["title"]
        (entry["roles"] if reachable(s, project) else entry["blocked"]).append(s["role"])
        entry["buttons"].update(s["buttons"] or [])
    for path, e in by_path.items():
        e["links_to"] = sorted(t for t in link_text.get(path, set()) if t)
        title = re.split(r"\s+[-|\u2013]\s+", e["title"] or "")[0].strip()
        e["name"] = title or ((e["headings"] or [""])[0]) or (e["links_to"][0] if e["links_to"] else path)
    fields = []
    seen = set()
    for s in screens:
        if not reachable(s, project):
            continue
        for form in s["forms"] or []:
            for f in form["fields"]:
                if not f.get("name") or (f.get("type") == "hidden" and not f.get("widget")):
                    continue  # unnamed inputs are never submitted; plain hidden inputs are not user-facing
                key = (s["path"], form["index"], f["name"] or f["id"])
                if key in seen:
                    for x in fields:
                        if (x["path"], x["form_index"], x["field"]["name"] or x["field"]["id"]) == key and s["role"] not in x["roles"]:
                            x["roles"].append(s["role"])
                    continue
                seen.add(key)
                fields.append({"path": s["path"], "form_index": form["index"], "form_id": form["id"],
                               "field": f, "roles": [s["role"]]})
    return by_path, fields


def match_field(name: str, fields: list[dict]) -> list[dict]:
    scored = []
    for f in fields:
        fl = f["field"]
        score = max(similarity(name, fl.get("label")), similarity(name, fl.get("name")),
                    similarity(name, fl.get("id")), similarity(name, fl.get("placeholder")))
        if score >= 0.72:
            scored.append((score, f))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    return [f for s, f in scored if s >= best - 0.05]


ACTION_VERBS = r"approve|verify|reject|edit|modify|delete|create|update|submit|process|download|print|forward"


def object_phrase(target: str) -> str:
    """'access the approval queue and approve applications' -> 'approval queue'."""
    t = norm(target)
    t = re.sub(r"^(?:be able to )?(?:access|view|open|see|use|visit|manage)\s+(?:the |all |any )?", "", t)
    return re.split(rf"\band (?={ACTION_VERBS})", t)[0].strip()


def match_screens(target: str, by_path: dict) -> list[dict]:
    obj = object_phrase(target)
    out = []
    for e in by_path.values():
        name = norm(e["name"])
        if not name or name in GENERIC_TITLES:
            continue
        tt = tokens(name)
        if not tt:
            continue
        literal = len(name) >= 6 and re.search(rf"\b{re.escape(name)}\b", obj)
        score = containment(name, obj)
        if literal or score >= 0.99 or (len(tt) >= 2 and score >= 0.6):
            out.append(e)
    return out


def match_feature(target: str, roles: list[str], by_path: dict) -> tuple[float, str | None]:
    best, where = 0.0, None
    for e in by_path.values():
        if roles and not set(roles) & set(e["roles"]):
            continue
        candidates = [e["name"], *(e["headings"] or []), *e["links_to"], *e["buttons"]]
        low_target = norm(target)
        for c in candidates:
            nc = norm(c)
            literal = len(nc) >= 6 and nc not in GENERIC_TITLES and re.search(rf"\b{re.escape(nc)}\b", low_target)
            score = 1.0 if literal else containment(target, c)
            if score > best:
                best, where = score, e["path"]
    return best, where


# ---------------------------------------------------------------------------
# Questions and answers
# ---------------------------------------------------------------------------

def _ask(store: Store, key: str, kind: str, question: str, rule_id=None, req_id=None,
         proposed=None, priority="Medium", context=None) -> dict | None:
    """Return a stored answer for this key, or open a question."""
    answered = store.one("SELECT * FROM questions WHERE key=? AND status='answered' ORDER BY id DESC LIMIT 1", [key])
    if answered:
        store.update("questions", "id", answered["id"], {"rule_id": rule_id, "req_id": req_id, "context": context})
        return answered
    if not store.one("SELECT id FROM questions WHERE key=? AND status='open'", [key]):
        live.emit("reconciler", "question", question, req=req_id, rule=rule_id, priority=priority, qkind=kind,
                  level="warn")
        store.insert("questions", {"key": key, "kind": kind, "question": question, "rule_id": rule_id,
                                   "req_id": req_id, "options": OPTIONS[kind], "proposed": proposed,
                                   "priority": priority, "status": "open", "context": context})
    return None


def answer_question(store: Store, qid: int, choice: int, value: str = "") -> None:
    q = store.one("SELECT * FROM questions WHERE id=?", [qid])
    if not q:
        raise KeyError(f"No question {qid}")
    opts = q["options"] or []
    label = opts[choice] if 0 <= choice < len(opts) else str(choice)
    store.update("questions", "id", qid, {"status": "answered", "answer": label,
                                          "answer_value": json.dumps({"choice": choice, "value": value}),
                                          "answered_at": now()})
    store.insert("change_log", {"at": now(), "agent": "person", "object": "question", "object_id": str(qid),
                                "change": f"answered '{label}'" + (f" ({value})" if value else "") + " for "
                                          + str(q.get("req_id") or q.get("rule_id") or "the plan"),
                                "justification": (q.get("question") or "")[:300], "by": "dashboard"})


def _choice(ans: dict) -> tuple[int, str]:
    try:
        v = json.loads(ans.get("answer_value") or "{}")
        return int(v.get("choice", -1)), str(v.get("value") or "")
    except (ValueError, TypeError):
        return -1, ""


def _parse_custom(kind: str, value: str):
    nums = [int(n) for n in re.findall(r"\d+", value)]
    if kind in ("max_length",) and nums:
        return {"max": nums[0]}
    if kind == "min_length" and nums:
        return {"min": nums[0]}
    if kind == "exact_length" and nums:
        return {"length": nums[0]}
    if kind in ("length_range", "numeric_range") and len(nums) >= 2:
        return {"min": nums[0], "max": nums[1]}
    if kind == "options":
        return {"options": [o.strip() for o in re.split(r",|/|\bor\b", value) if o.strip()]}
    return {"text": value}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def reconcile(project: Project, store: Store, policy: str | None = None) -> dict:
    policy = policy or project.cfg["policy"]["divergence"]
    inferred_policy = project.cfg["policy"].get("inferred_access", "ask")
    by_path, fields = app_index(project, store)
    if not by_path:
        raise RuntimeError("No screens recorded. Run the Explorer first.")
    live.emit("reconciler", "start", f"Comparing the SRS with {len(by_path)} screen(s) and {len(fields)} form field(s)",
              screens=len(by_path), fields=len(fields), policy=policy)
    store.exec("DELETE FROM questions WHERE status='open'")
    store.exec("DELETE FROM rules WHERE source IN ('app', 'inferred', 'answer')")
    rules = store.all("SELECT * FROM rules ORDER BY id")
    reqs = {r["id"]: r for r in store.all("SELECT * FROM requirements")}
    all_roles = list(project.roles())
    workflows = project.cfg.get("workflows") or []
    wf_reqs = {rid for wf in workflows for rid in wf.get("rule_ids", [])}
    extra_seq = store.scalar("SELECT COUNT(*) FROM rules") or 0

    def new_rule(row: dict) -> None:
        nonlocal extra_seq
        extra_seq += 1
        live.emit("reconciler", "status", f"app {row['kind'].replace('_', ' ')} {row.get('field') or row.get('target') or ''}: "
                  f"{row['status']}", rule_kind=row["kind"], field=row.get("field"), status=row["status"],
                  note=row.get("status_note"), where=", ".join(m.get("path", "") for m in row.get("matched") or []) or None,
                  level="warn" if row["status"] == "App-only" else None)
        store.insert("rules", {"id": f"R-A{extra_seq:03d}", "confidence": 0.9, "status_note": "",
                               "decided_value": None, "matched": None, **row})

    def set_status(rule, status, note="", matched=None, decided=None):
        store.update("rules", "id", rule["id"], {"status": status, "status_note": note,
                                                  "matched": matched, "decided_value": decided})
        what = rule.get("field") or (rule.get("target") or "")[:60]
        where = ", ".join(dict.fromkeys(f"{m.get('path')}" + (f"#{m['name']}" if m.get("name") else "")
                                        for m in (matched or []) if m.get("path")))
        live.emit("reconciler", "status", f"{rule['req_id'] or 'app'} {rule['kind'].replace('_', ' ')} {what}: {status}",
                  req=rule["req_id"], rule=rule["id"], rule_kind=rule["kind"], field=rule.get("field"),
                  status=status, note=note or None, where=where or None,
                  level={"Divergent": "bad", "SRS-only": "warn", "Missing in app": "bad", "Ambiguous": "warn",
                         "Proposed": "warn"}.get(status))

    matched_fields: set = set()
    field_groups: dict[str, list[dict]] = {}
    for r in rules:
        if r["kind"] in FIELD_KINDS and r.get("field"):
            field_groups.setdefault(norm(r["field"]), []).append(r)

    # ---- 1. field rules ------------------------------------------------------
    for fkey, group in field_groups.items():
        fname = group[0]["field"]
        hits = match_field(fname, fields)
        if not hits:
            ans = _ask(store, f"srs_only_field:{fkey}", "srs_only_field",
                       f"The SRS describes a field '{fname}' ({', '.join(sorted({g['kind'].replace('_', ' ') for g in group}))}), "
                       f"but no matching field was found on any screen. Is it missing from the app?",
                       rule_id=group[0]["id"], req_id=group[0]["req_id"], priority="High",
                       context={"field": fname})
            choice, value = _choice(ans) if ans else (-1, "")
            for r in group:
                if r["kind"] == "tbd" and choice != 0:
                    continue
                if choice == 0:
                    set_status(r, "Missing in app", f"Confirmed missing by {ans['answer']!r}")
                elif choice == 1 and value:
                    hits2 = match_field(value, fields)
                    if hits2:
                        set_status(r, "Confirmed", f"Mapped by reviewer to '{value}'",
                                   matched=[{k: h[k] for k in ("path", "form_index")} | {"name": h["field"]["name"]} for h in hits2])
                    else:
                        set_status(r, "SRS-only", f"Reviewer mapped to '{value}' but no such field was seen")
                elif choice == 2:
                    set_status(r, "Rejected", "Dropped by reviewer")
                else:
                    set_status(r, "SRS-only", "No matching field seen on any screen")
            if choice != 0:
                for r in group:
                    if r["kind"] == "tbd":
                        _tbd(store, r, set_status)
            continue
        for h in hits:
            matched_fields.add((h["path"], h["form_index"], h["field"]["name"]))
        ref = [{"path": h["path"], "form_index": h["form_index"], "name": h["field"]["name"],
                "label": h["field"]["label"], "roles": h["roles"]} for h in hits]
        app = hits[0]["field"]
        for r in group:
            kind, val = r["kind"], r["value"] or {}
            if kind == "tbd":
                _tbd(store, r, set_status, ref)
                continue
            divergence = None
            app_value = None
            if kind in ("max_length", "exact_length") and app.get("maxlength"):
                want = val.get("max", val.get("length"))
                if want is not None and int(app["maxlength"]) != int(want):
                    divergence = f"SRS limit {want} characters; the app's field allows {app['maxlength']}"
                    app_value = {"max": int(app["maxlength"])} if kind == "max_length" else {"length": int(app["maxlength"])}
            elif kind == "min_length" and app.get("minlength"):
                if int(app["minlength"]) != int(val["min"]):
                    divergence = f"SRS minimum {val['min']} characters; the app's field requires {app['minlength']}"
                    app_value = {"min": int(app["minlength"])}
            elif kind == "options" and app.get("options") is not None:
                app_opts = [o["text"] for o in app["options"] if (o.get("value") or "").strip()]
                srs_opts = val.get("options", [])
                missing = [o for o in srs_opts if max((similarity(o, a) for a in app_opts), default=0) < 0.8]
                extra = [a for a in app_opts if max((similarity(a, o) for o in srs_opts), default=0) < 0.8]
                if missing or extra:
                    divergence = (f"SRS options: {', '.join(srs_opts)}; app offers: {', '.join(app_opts)}"
                                  + (f" (missing {', '.join(missing)}" if missing else " (")
                                  + (f"; extra {', '.join(extra)})" if extra else ")"))
                    app_value = {"options": app_opts}
            elif kind == "file_types" and app.get("accept"):
                norm_ext = lambda x: x.strip().lstrip(".").lower().replace("jpeg", "jpg")  # noqa: E731
                app_types = sorted({norm_ext(x) for x in app["accept"].split(",") if x.strip() and "/" not in x})
                srs_types = sorted({norm_ext(x) for x in val.get("types", [])})
                if app_types and set(app_types) != set(srs_types):
                    divergence = f"SRS allows {', '.join(srs_types)}; the form's file chooser allows {', '.join(app_types)}"
                    app_value = {"types": app_types}
            if not divergence:
                note = ""
                if kind == "required" and not app.get("required"):
                    note = "Form has no required attribute; the server must enforce it"
                set_status(r, "Confirmed", note, matched=ref)
                continue
            key = f"divergence:{fkey}:{kind}"
            if policy == "srs_wins":
                set_status(r, "Decided", f"{divergence}. Policy: SRS wins", matched=ref, decided=val)
            elif policy == "app_wins":
                set_status(r, "Decided", f"{divergence}. Policy: app wins", matched=ref, decided=app_value)
            else:
                ans = _ask(store, key, "divergence", f"{fname}: {divergence}. Which is correct?",
                           rule_id=r["id"], req_id=r["req_id"], priority="High",
                           context={"srs": val, "app": app_value, "field": fname})
                if not ans:
                    set_status(r, "Divergent", divergence, matched=ref)
                else:
                    choice, value = _choice(ans)
                    decided = {0: val, 1: app_value}.get(choice) or _parse_custom(kind, value)
                    set_status(r, "Decided", f"{divergence}. Reviewer: {ans['answer']}", matched=ref, decided=decided)

    # ---- 2. access, feature, workflow and non-functional rules ------------------
    for r in rules:
        kind = r["kind"]
        if kind in ("access_only", "access_deny"):
            screens = match_screens(r["target"] or "", by_path)
            if not screens:
                ans = _ask(store, f"srs_only_screen:{r['req_id']}:{norm(r['target'])[:60]}", "srs_only_screen",
                           f"{r['req_id']} restricts '{r['target']}', but no screen with that name was found. "
                           f"Is it missing from the app?", rule_id=r["id"], req_id=r["req_id"], priority="High")
                _apply_srs_only(r, ans, set_status, by_path)
                continue
            if kind == "access_only":
                deny = [x for x in all_roles if x not in (r["roles"] or [])] + ["anonymous"]
            else:
                deny = list(r["roles"] or [])
            set_status(r, "Confirmed", f"Matches {', '.join(s['path'] for s in screens)}",
                       matched=[{"path": s["path"], "title": s["name"], "deny": deny,
                                 "allowed": r["roles"] if kind == "access_only" else None} for s in screens])
        elif kind == "feature":
            score, where = match_feature(r["target"] or "", r["roles"] or [], by_path)
            if score >= 0.5:
                set_status(r, "Confirmed", f"Found at {where} (match {score:.0%})", matched=[{"path": where}])
            else:
                who = ", ".join(r["roles"] or []) or "users"
                ans = _ask(store, f"srs_only_feature:{r['req_id']}", "srs_only_feature",
                           f"{r['req_id']}: '{reqs.get(r['req_id'], {}).get('text', r['target'])}' - no matching screen, "
                           f"link or button was found for {who}. Is the feature missing?",
                           rule_id=r["id"], req_id=r["req_id"], priority="High")
                _apply_srs_only(r, ans, set_status, by_path)
        elif kind == "status_transition":
            if r["req_id"] in wf_reqs:
                wf = next(w["id"] for w in workflows if r["req_id"] in w.get("rule_ids", []))
                set_status(r, "Workflow", f"Covered by {wf}")
            else:
                ans = _ask(store, f"workflow:{r['req_id']}", "workflow",
                           f"{r['req_id']} describes a status change ('{(r['value'] or {}).get('status')}'). "
                           f"Describe the multi-role flow in project.yaml so it can be tested end to end?",
                           rule_id=r["id"], req_id=r["req_id"], priority="Medium")
                set_status(r, "Not automated" if ans and _choice(ans)[0] == 1 else "Workflow",
                           "Needs a workflow definition in project.yaml")
        elif kind == "perf_max_load":
            set_status(r, "Confirmed", f"Applied to every page load test ({r['value']['ms']} ms)")
        elif kind == "otp_single_use":
            otp = (project.cfg.get("login") or {}).get("otp") or {}
            if otp.get("field") and otp.get("source", "inbox") in ("inbox", "api") and store.get_meta("otp_roles"):
                set_status(r, "Confirmed", f"Checked by logging in twice as {store.get_meta('otp_roles')[0]} "
                                           f"and reusing the first OTP")
            else:
                set_status(r, "Not automated", "Set login.otp (source inbox or api) so AgentQA can read OTPs")
        elif kind == "session_timeout":
            set_status(r, "Not automated", "Needs a long idle test; check manually or shorten the timeout in the test environment")
        if r["source"] == "llm" and kind not in ("tbd",):
            ans = _ask(store, f"llm_rule:{r['req_id']}:{kind}:{norm(r.get('field') or r.get('target') or '')[:40]}",
                       "llm_rule", f"The local model read {r['req_id']} as a '{kind.replace('_', ' ')}' rule "
                       f"({r.get('field') or r.get('target') or ''} {r['value'] or ''}). Is that right?",
                       rule_id=r["id"], req_id=r["req_id"], priority="Medium")
            if not ans:
                set_status(r, "Proposed", "Suggested by the local model; awaiting confirmation")
            elif _choice(ans)[0] == 1:
                set_status(r, "Rejected", "Reviewer rejected the model's reading")

    # ---- 3. ambiguous requirements ----------------------------------------------
    for req in reqs.values():
        flags = req.get("ambiguity") or []
        terms = [f for f in flags if f["term"] not in ("tbd", "tbc", "model interpretation")]
        if not terms:
            continue
        interp = next((f["reason"] for f in flags if f["term"] == "model interpretation"), None)
        proposed = interp or _proposal(req["text"], terms)
        _ask(store, f"ambiguous:{req['id']}", "ambiguous",
             f"{req['id']} is not testable as written: \"{req['text']}\" "
             f"({'; '.join(t['term'] + ': ' + t['reason'] for t in terms)}).",
             req_id=req["id"], proposed=proposed, priority="Medium" if req["priority"] == "High" else "Low")

    # ---- 4. app-only fields --------------------------------------------------------
    unmatched: dict[str, list[dict]] = {}
    form_meta = {(s["path"], fm["index"]): fm for s in store.all("SELECT path, forms FROM screens")
                 for fm in (s["forms"] or [])}
    for f in fields:
        fl = f["field"]
        fm = form_meta.get((f["path"], f["form_index"])) or {}
        if fm.get("method") == "get" and len(fm.get("fields") or []) <= 2:
            continue  # search boxes and filters
        if (f["path"], f["form_index"], fl["name"]) in matched_fields:
            continue
        if project.is_login_path(f["path"]):
            continue
        unmatched.setdefault(f"{f['path']}#{f['form_index']}", []).append(f)
    for key, flist in unmatched.items():
        names = [x["field"]["label"] or x["field"]["name"] for x in flist]
        ans = _ask(store, f"app_only:{key}:{','.join(sorted(n for n in names))[:80]}", "app_only",
                   f"Fields on {flist[0]['path']} that the SRS never mentions: {', '.join(names)}. Are they expected?",
                   priority="Low", context={"path": flist[0]["path"]})
        choice = _choice(ans)[0] if ans else -1
        for x in flist:
            fl = x["field"]
            declared = []
            if fl.get("required"):
                declared.append(("required", {}))
            if fl.get("maxlength"):
                declared.append(("max_length", {"max": int(fl["maxlength"])}))
            if fl.get("minlength"):
                declared.append(("min_length", {"min": int(fl["minlength"])}))
            if fl.get("type") == "email":
                declared.append(("format_email", {}))
            for kind, val in declared:
                status = {0: "Decided", 2: "Rejected"}.get(choice, "App-only")
                new_rule({"req_id": None, "kind": kind, "field": fl["label"] or fl["name"], "value": val,
                          "roles": x["roles"], "target": None, "source": "app", "status": status,
                          "status_note": "Declared by the app's own form attributes",
                          "matched": [{"path": x["path"], "form_index": x["form_index"], "name": fl["name"],
                                       "label": fl["label"], "roles": x["roles"]}]})

    # ---- 5. inferred access (screens only some roles can see) ---------------------
    covered = {m["path"] for r in store.all("SELECT matched FROM rules WHERE kind IN ('access_only','access_deny') AND status='Confirmed'")
               for m in (r["matched"] or [])}
    for path, e in by_path.items():
        if "anonymous" in e["roles"] or path in covered or not e["roles"]:
            continue
        if norm(e["name"]) in GENERIC_TITLES or project.is_login_path(path):
            continue
        others = [x for x in all_roles if x not in e["roles"]]
        if not others or inferred_policy == "ignore":
            continue
        if inferred_policy == "deny":
            ans, choice = None, 0
        else:
            ans = _ask(store, f"inferred_access:{path}", "inferred_access",
                       f"'{e['name']}' ({path}) is only linked for {', '.join(e['roles'])}. "
                       f"Must {', '.join(others)} be blocked from opening it directly?",
                       priority="Medium", context={"path": path, "roles": others})
            choice = _choice(ans)[0] if ans else -1
        if choice == 0:
            new_rule({"req_id": None, "kind": "access_only", "field": None, "value": {}, "roles": e["roles"],
                      "target": e["name"], "source": "inferred", "status": "Decided",
                      "status_note": "Inferred from navigation and confirmed" if ans else "Inferred (policy: deny)",
                      "matched": [{"path": path, "title": e["name"], "deny": others + ["anonymous"],
                                   "allowed": e["roles"]}]})

    counts = {s["status"]: s["n"] for s in store.all("SELECT status, COUNT(*) n FROM rules GROUP BY status")}
    counts["open_questions"] = store.scalar("SELECT COUNT(*) FROM questions WHERE status='open'")
    store.set_meta("reconcile", counts)
    live.emit("reconciler", "summary", ", ".join(f"{v} {k}" for k, v in counts.items()), counts=counts)
    return counts


def _tbd(store, r, set_status, ref=None):
    ans = _ask(store, f"tbd:{norm(r['field'])}", "ambiguous",
               f"{r['req_id']}: the {(r['value'] or {}).get('what', 'value')} for '{r['field']}' is TBD in the SRS. "
               f"What is the rule?", rule_id=r["id"], req_id=r["req_id"],
               proposed="e.g. 'max 250 characters'", priority="Medium", context={"field": r["field"]})
    if ans and _choice(ans)[0] == 1 and _choice(ans)[1]:
        from agentqa.agents.srs_analyst import constraint_rules
        for nr in constraint_rules(_choice(ans)[1], r["field"]):
            store.insert("rules", {"id": f"{r['id']}-{nr['kind']}", "req_id": r["req_id"], "kind": nr["kind"],
                                   "field": r["field"], "value": nr["value"], "roles": [], "target": None,
                                   "source": "answer", "confidence": 1.0, "status": "Decided",
                                   "status_note": f"Defined by reviewer: {_choice(ans)[1]}",
                                   "matched": ref, "decided_value": nr["value"]}, replace=True)
        set_status(r, "Decided", "Value supplied by reviewer", matched=ref)
    else:
        set_status(r, "Ambiguous", "Value is TBD in the SRS", matched=ref)


def _apply_srs_only(r, ans, set_status, by_path):
    if not ans:
        set_status(r, "SRS-only", "Not found in the app")
        return
    choice, value = _choice(ans)
    if choice == 0:
        set_status(r, "Missing in app", f"Confirmed missing: {ans['answer']}")
    elif choice == 1 and value:
        path = value if value.startswith("/") else "/" + value
        e = by_path.get(path)
        set_status(r, "Confirmed" if e else "SRS-only", f"Reviewer says it is at {path}",
                   matched=[{"path": path, "title": e["name"] if e else path,
                             "deny": [], "allowed": r["roles"]}])
    else:
        set_status(r, "Rejected", "Out of scope (reviewer)")


def _proposal(text: str, terms: list[dict]) -> str:
    low = text.lower()
    if "error message" in low:
        return "Each invalid input shows a visible error message that names the field and the problem."
    if any(t["term"] in ("quickly", "fast", "promptly") for t in terms):
        return "Every page loads within 3 seconds on the test environment."
    if "language" in low:
        return "List the languages (for example English and Malayalam) and the screens that must be translated."
    return "Rewrite with a measurable acceptance criterion (a value, a limit or an exact behaviour)."
