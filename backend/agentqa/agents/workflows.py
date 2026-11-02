"""Workflow agent: multi-role, cross-portal workflows derived from the SRS and the app map.

From the SRS it takes the status changes ('When the Clerk verifies an application, its status shall
change to Verified'), in document order. From the app map it finds:

  the form that creates the record    a form of another role whose button or page names the record
                                      ('Submit Application' on Apply for Certificate)
  where each actor acts               the actor's screen named after the action (Verification Queue,
                                      Approval Queue), on whichever portal that role uses
  where the creator follows it        the creator's screen that lists the records (My Applications)

and writes one end-to-end case: the creator submits and notes the reference number, each actor finds
that same record and acts on it, and after every step the creator sees the new status. When the portal
offers Reject, Return or Send back actions, a second case follows that path. Nothing is invented: a step
whose screen or action cannot be found is listed as a gap with the reason, not silently dropped.
"""
from __future__ import annotations

import re

from agentqa import live
from agentqa.config import Project
from agentqa.store import Store
from agentqa.util import guess_semantic, similarity, valid_value

ACT = re.compile(r"\b(?:when|once|after|if)\s+(?:the\s+)?([\w ]{2,40}?)\s+(\w+)\s+(?:an?|the)\s+(\w+)", re.I)


def _lemma(verb: str) -> str:
    """verifies -> verify, approves -> approve, rejects -> reject, forwards -> forward."""
    v = verb.lower()
    if v.endswith("ies"):
        return v[:-3] + "y"
    if v.endswith("es") and v[:-2].endswith(("s", "x", "ch", "sh")):
        return v[:-2]
    return v[:-1] if v.endswith("s") and not v.endswith("ss") else v
NEG = re.compile(r"\b(reject|return|send back|sent back|decline|refuse)\w*", re.I)


def _past(verb: str) -> str:
    v = verb.lower()
    return v[:-1] + "ied" if v.endswith("y") else v + "d" if v.endswith("e") else v + "ed"


def _stem(word: str) -> str:
    return word.lower()[:5]


def _actor_screen(screens: list[dict], role: str, stem: str) -> dict | None:
    mine = [s for s in screens if s["role"] == role and (s["status"] or 0) < 400]
    named = [s for s in mine if stem in (s["title"] or "").lower() or stem in s["path"].lower()]
    if named:
        return named[0]
    acted = [s for s in mine if any(stem in (b.get("text") if isinstance(b, dict) else str(b)).lower()
                                    for b in (s["buttons"] or []))]
    if acted:
        return acted[0]
    return next((s for s in mine if re.search(r"queue|pending|inbox|task|worklist", (s["title"] or "") + s["path"], re.I)), None)


def _status_screen(screens: list[dict], role: str, noun: str) -> dict | None:
    mine = [s for s in screens if s["role"] == role and (s["status"] or 0) < 400 and "{" not in s["path"]]
    want = f"my {noun}s"

    def score(s):
        t = (s["title"] or "").lower()
        return max(similarity(want, t), 0.9 if noun[:5] in t and re.search(r"\bmy\b|status|track", t) else 0)
    best = max(mine, key=score, default=None)
    return best if best and score(best) >= 0.6 else None


def _creator_form(screens: list[dict], actors: set[str], noun: str, project: Project):
    best, best_score = None, 0.0
    for s in screens:
        if s["role"] in actors or s["role"] == "anonymous" or (s["status"] or 0) >= 400 or project.is_login_path(s["path"]):
            continue
        for fm in s["forms"] or []:
            if (fm.get("method") or "get").lower() != "post" or not fm.get("fields"):
                continue
            text = f"{fm.get('submit_text') or ''} {s['title'] or ''}".lower()
            score = (2.0 if noun[:5] in text else 0) + (1.0 if re.search(r"submit|apply|register|create|request", text) else 0) \
                + len(fm["fields"]) / 50
            if score > best_score:
                best, best_score = (s, fm), score
    return best if best_score >= 2.0 else None


def _fill_steps(s: dict, fm: dict, field_rules: dict) -> list[dict]:
    out = []
    for f in fm["fields"]:
        if not f.get("name"):
            continue
        rs = [{"kind": r["kind"], "value": (r["decided_value"] if r["status"] == "Decided" and r["decided_value"] else r["value"]) or {}}
              for r in field_rules.get((s["path"], f["name"]), [])]
        if not (f.get("required") or rs) and f["type"] != "select":
            continue
        v = valid_value(f, rs)
        if v is None or (f["type"] == "checkbox" and not f.get("required")):
            continue
        if guess_semantic(f) == "name" and not str(v).startswith("@"):
            v = "Workflow Tester"
        shown = "a sample file" if str(v).startswith("@file:") else f"'{v}'"
        out.append({"action": "fill", "field": f["name"], "value": v, "text": f"Enter {shown} in '{f.get('label') or f['name']}'"})
    return out


def derive(project: Project, store: Store) -> tuple[list[dict], list[dict]]:
    """(cases, gaps). Cases are functional cases in module 'Workflows'."""
    rules = [r for r in store.all("SELECT * FROM rules ORDER BY id") if r["kind"] == "status_transition"]
    if not rules:
        return [], []
    screens = store.all("SELECT * FROM screens ORDER BY id")
    reqs = {r["id"]: r["text"] for r in store.all("SELECT id, text FROM requirements")}
    field_rules: dict[tuple, list] = {}
    for r in store.all("SELECT * FROM rules WHERE status IN ('Confirmed', 'Decided')"):
        for m in r.get("matched") or []:
            if m.get("name"):
                field_rules.setdefault((m["path"], m["name"]), []).append(r)
    chain, gaps = [], []
    for r in rules:
        text = r.get("target") or reqs.get(r["req_id"], "")
        m = ACT.search(text)
        role = (r.get("roles") or [None])[0]
        status = (r.get("value") or {}).get("status")
        if not (m and role and status):
            gaps.append({"req_id": r["req_id"], "why": f"could not read who does what in: {text[:120]}"})
            continue
        chain.append({"req_id": r["req_id"], "rule_id": r["id"], "role": role, "verb": _lemma(m.group(2)), "noun": m.group(3).lower(),
                      "status": status, "negative": bool(NEG.search(m.group(2)))})
    if not chain:
        return [], gaps
    noun = chain[0]["noun"].rstrip("s")
    actors = {c["role"] for c in chain}
    made = _creator_form(screens, actors, noun, project)
    if not made:
        gaps.append({"req_id": chain[0]["req_id"], "why": f"no form found that creates a {noun} (needed to start the workflow)"})
        return [], gaps
    form_screen, fm = made
    creator = form_screen["role"]
    follow = _status_screen(screens, creator, noun)
    feature_reqs = [r["req_id"] for r in store.all("SELECT * FROM rules WHERE kind='feature'")
                    if creator in (r.get("roles") or []) and (
                        re.search(r"\b(apply|submit|create|register|request|file)\b", (r.get("target") or "").lower())
                        and noun[:5] in (r.get("target") or "").lower()
                        or re.search(r"\b(status|track|view)\b", (r.get("target") or "").lower()) and noun[:5] in
                        (r.get("target") or "").lower())]

    def creator_steps() -> list[dict]:
        submit = fm.get("submit_text") or "Submit"
        return ([{"action": "goto", "role": creator, "path": form_screen["path"],
                  "text": f"As {creator}: open {form_screen['title'] or form_screen['path']}"}]
                + [{**st, "role": creator} for st in _fill_steps(form_screen, fm, field_rules)]
                + [{"action": "click", "role": creator, "target": submit, "text": f"As {creator}: click '{submit}'"},
                   {"action": "expect_success", "role": creator, "text": "Check the submission is confirmed"},
                   {"action": "capture_ref", "role": creator, "text": f"Note the {noun} number shown"}])

    def check_status(status: str) -> list[dict]:
        if not follow:
            return []
        return [{"action": "goto", "role": creator, "path": follow["path"],
                 "text": f"As {creator}: open {follow['title'] or follow['path']}"},
                {"action": "expect_record_status", "role": creator, "ref": "{ref}", "status": status,
                 "text": f"Check {noun} {{ref}} shows '{status}'"}]

    def act_steps(c: dict) -> list[dict] | None:
        scr = _actor_screen(screens, c["role"], _stem(c["verb"]))
        if not scr:
            gaps.append({"req_id": c["req_id"], "why": f"no screen of {c['role']} found where they {c['verb']} a {noun}"})
            return None
        verb = c["verb"].capitalize()
        return [{"action": "goto", "role": c["role"], "path": scr["path"],
                 "text": f"As {c['role']}: open {scr['title'] or scr['path']}"
                         + (f" on the {project.applications()[project.split_path(scr['path'])[0]]['name']}"
                            if len(project.applications()) > 1 else "")},
                {"action": "expect_record_listed", "role": c["role"], "ref": "{ref}",
                 "text": f"Check {noun} {{ref}} has reached {c['role']}"},
                {"action": "click_record", "role": c["role"], "verb": verb, "ref": "{ref}",
                 "text": f"As {c['role']}: {c['verb'].lower()} {noun} {{ref}}"}]

    cases = []
    happy = [c for c in chain if not c["negative"]]
    steps = creator_steps()
    used, ok = [], True
    for c in happy:
        st = act_steps(c)
        if st is None:
            ok = False
            break
        steps += st + check_status(c["status"])
        used.append(c)
    if ok and used:
        portals = sorted({project.applications()[project.split_path(s["path"])[0]]["name"]
                          for s in steps if s.get("path")})
        path_desc = " → ".join([creator] + [c["role"] for c in used] + [creator])
        cases.append(_case(project, "workflow:main", f"End to end: {noun} submitted by {creator}, then "
                           + ", then ".join(f"{_past(c['verb'])} by {c['role']}" for c in used)
                           + f"; {creator} sees '{used[-1]['status']}'", creator, form_screen["path"], steps,
                           [c["req_id"] for c in used] + feature_reqs, [c["rule_id"] for c in used],
                           f"Workflow {path_desc} across {', '.join(portals)}",
                           f"The {noun} reaches each role in turn; after each action its status changes to "
                           + ", then ".join(f"'{c['status']}'" for c in used) + f", and {creator} sees each change.",
                           [c["role"] for c in used]))
    # rejection paths, when the SRS names them and the portal offers the action
    for c in [c for c in chain if c["negative"]]:
        st = act_steps(c)
        if st is None:
            continue
        steps = creator_steps()
        for prior in happy:
            if prior["role"] == c["role"]:
                break
            pre = act_steps(prior)
            if pre:
                steps += pre
        steps += st + check_status(c["status"])
        cases.append(_case(project, f"workflow:{c['req_id']}", f"Workflow: {noun} {c['verb'].lower()} by {c['role']}; "
                           f"{creator} sees '{c['status']}'", creator, form_screen["path"], steps,
                           [c["req_id"]] + feature_reqs, [c["rule_id"]], "Rejection path",
                           f"After the {c['verb'].lower()} the {noun} shows '{c['status']}' to {creator}.", [c["role"]]))
    if not [c for c in chain if c["negative"]]:
        acts = {re.sub(r"\s+", " ", (b.get("text") if isinstance(b, dict) else str(b))).strip() for s in screens
                for b in (s["buttons"] or []) if s["role"] in actors}
        if not any(NEG.search(a) for a in acts):
            gaps.append({"req_id": "-", "why": "no rejection or return action is in the SRS or on the actors' screens, "
                                               "so no rejection workflow was generated"})
    live.emit("analyst", "observe", f"Workflow agent: {len(cases)} multi-role workflow(s) from {len(chain)} status rule(s)"
              + (f"; {len(gaps)} gap(s)" if gaps else ""), level="ok" if cases else "warn")
    store.set_meta("workflow_gaps", gaps)
    return cases, gaps


def _case(project, key, title, creator, path, steps, reqs, rules, scenario, expected, actors) -> dict:
    return {"key": "func:" + key, "type": "functional", "group": "functional", "title": title, "role": creator, "path": path,
            "priority": "P1", "rule_ids": sorted(set(rules)), "req_ids": sorted(set(reqs)), "oracle_source": "srs",
            "params": {"module": "Workflows", "scenario": scenario,
                       "preconditions": "Each role logged in on its own portal: " + ", ".join(
                           f"{r} ({project.applications()[project.app_of(r)]['name']})" for r in [creator] + actors),
                       "steps_text": [s["text"] for s in steps], "test_data": "Valid values for every mandatory field",
                       "expected": expected, "steps": steps, "page_role": creator, "fresh_login": False,
                       "sig": f"workflow:{key}", "severity": "High",
                       "defect_title": f"{title.split(':')[0]} breaks", "order": (4, 0)}}
