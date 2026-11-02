"""Test Planner and Case Designer agents.

The Designer turns every Confirmed or Decided rule into concrete test cases
using standard techniques (boundary values, equivalence classes, negative
inputs, role-permission matrix) and adds baseline checks every portal should
pass (pages load, links work, login is enforced, basic accessibility).

Each case has a stable key, so approvals survive a re-design. Every case says
where its expected result comes from (oracle_source): srs, decided, workflow
or baseline.
"""
from __future__ import annotations

import hashlib
import string

from agentqa.agents.reconciler import FIELD_KINDS, app_index
from agentqa import live
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import future_date, guess_semantic, norm, path_pattern, valid_value

USABLE = ("Confirmed", "Decided")
PRIORITY = {"access": "P1", "workflow": "P1", "page": "P1", "form_valid": "P1", "api_access": "P1", "isolation": "P1",
            "security": "P1", "api": "P2", "field": "P2", "links": "P2", "options": "P2", "performance": "P2",
            "visual": "P3", "attribute": "P3", "a11y": "P3", "manual": "P2", "functional": "P2"}


def _len_value(base: str, n: int, sem: str) -> str:
    if sem == "email":
        domain = "@example.com"
        return "q" * max(1, n - len(domain)) + domain
    if sem in ("mobile", "pincode", "aadhaar") or base.isdigit():
        digits = (base if base.isdigit() else "9876543210") * 20
        return digits[:n]
    filler = (base + " " + "abcdefghij" * 30).replace("  ", " ")
    return filler[:n]


def invalid_values(kind: str, val: dict, field: dict, valid: str, all_kinds: set[str]) -> list[tuple[str, str]]:
    """(value, description) pairs that must be rejected for this rule."""
    sem = guess_semantic(field)
    out: list[tuple[str, str]] = []
    if kind == "required":
        out.append(("", "empty"))
    elif kind == "max_length":
        n = int(val["max"])
        out.append((_len_value(valid, n + 1, sem), f"{n + 1} characters (limit {n})"))
    elif kind == "min_length":
        n = int(val["min"])
        if n > 1:
            out.append((_len_value(valid, n - 1, sem), f"{n - 1} characters (minimum {n})"))
    elif kind == "length_range":
        lo, hi = int(val["min"]), int(val["max"])
        if lo > 1:
            out.append((_len_value(valid, lo - 1, sem), f"{lo - 1} characters (minimum {lo})"))
        out.append((_len_value(valid, hi + 1, sem), f"{hi + 1} characters (limit {hi})"))
    elif kind == "exact_length":
        n = int(val["length"])
        out.append((_len_value(valid, n - 1, sem), f"{n - 1} characters (must be exactly {n})"))
        out.append((_len_value(valid, n + 1, sem), f"{n + 1} characters (must be exactly {n})"))
    elif kind == "digits_only":
        n = len(valid) if valid else 6
        bad = (valid[: max(1, n // 2)] + "abcdefghij")[:n] if valid else "12ab56"
        out.append((bad, "letters mixed with digits"))
    elif kind == "starts_with":
        allowed = set(val.get("chars") or [])
        bad_first = next((d for d in "0123456789" if d not in allowed), None)
        if bad_first and valid:
            out.append((bad_first + valid[1:], f"starts with {bad_first} (allowed: {', '.join(sorted(allowed))})"))
    elif kind == "format_mobile" and not ({"digits_only", "starts_with"} & all_kinds):
        out.append(("98765abcde", "letters in a mobile number"))
    elif kind == "format_email":
        out += [("qa.tester@", "missing domain"), ("qa.tester.example.com", "missing @")]
    elif kind == "alpha_only":
        out.append(((valid or "Test")[:6] + "123", "digits in a letters-only field"))
    elif kind == "numeric_range":
        out += [(str(int(val["min"]) - 1), f"below minimum {val['min']}"),
                (str(int(val["max"]) + 1), f"above maximum {val['max']}")]
    elif kind == "date_not_future":
        out.append((future_date(30), "a date 30 days in the future"))
    elif kind == "file_types":
        allowed = [t.lower() for t in val.get("types") or []]
        bad = next((x for x in ("exe", "html", "txt") if x not in allowed), None)
        if bad:
            out.append((f"@file:sample.{bad}", f"a .{bad} file (allowed: {', '.join(allowed)})"))
    elif kind == "file_max_size":
        kb = int(val["kb"])
        over = kb + max(64, kb // 20)
        ext = (valid.rsplit(".", 1)[-1] if valid.startswith("@file:") else "pdf")
        out.append((f"@file:large.{ext}:{over}", f"a {over / 1024:.1f} MB file (limit {kb / 1024:g} MB)"
                    if kb >= 1024 else f"a {over} KB file (limit {kb} KB)"))
    return out


def design(project: Project, store: Store) -> dict:
    from agentqa.agents import requirements as reqs_agent
    try:
        reqs_agent.standardise(project, store)
    except Exception as exc:  # noqa: BLE001
        from agentqa.util import warn
        warn(f"[requirements] standardisation failed: {exc}")
    by_path, fields = app_index(project, store)
    screens = store.all("SELECT * FROM screens ORDER BY id")
    rules = store.all("SELECT * FROM rules ORDER BY id")
    max_load = None
    for r in rules:
        if r["kind"] == "perf_max_load" and r["status"] in USABLE:
            max_load = int((r["decided_value"] or r["value"])["ms"])
    max_load = max_load or project.cfg["policy"].get("max_load_ms")

    previous = {c["key"]: c for c in store.all("SELECT key, status, id FROM cases")}
    store.clear("cases")
    cases: list[dict] = []

    def add(key, ctype, group, title, role, path, params, rule_ids=(), req_ids=(), oracle="baseline"):
        cases.append({"key": key, "type": ctype, "group": group, "title": title, "role": role, "path": path,
                      "params": params, "rule_ids": sorted(set(rule_ids)),
                      "req_ids": sorted(set(x for x in req_ids if x)), "oracle_source": oracle})

    form_index: dict[tuple, dict] = {}
    for s in screens:
        for fm in s["forms"] or []:
            form_index.setdefault((s["path"], fm["index"], s["role"]), fm)

    # ---- field rules -> validation cases -------------------------------------------
    groups: dict[tuple, dict] = {}
    for r in rules:
        if r["kind"] not in FIELD_KINDS or r["status"] not in USABLE or not r.get("matched"):
            continue
        val = r["decided_value"] if r["status"] == "Decided" and r["decided_value"] else r["value"]
        for m in r["matched"]:
            role = (m.get("roles") or [None])[0]
            gkey = (m["path"], m["form_index"], m["name"])
            g = groups.setdefault(gkey, {"role": role, "label": m.get("label") or m["name"], "rules": {}})
            entry = g["rules"].setdefault((r["kind"], str(val)), {"kind": r["kind"], "value": val or {},
                                                                    "rule_ids": [], "req_ids": [], "statuses": set()})
            entry["rule_ids"].append(r["id"])
            entry["req_ids"].append(r["req_id"])
            entry["statuses"].add(r["status"])

    # login pages are tested by the Functional Test Analyst (a 'valid' login needs a registered account)
    login_pages: set[str] = set()
    try:
        if project.vault.path.exists():
            for role in project.roles():
                for stage in project.vault.login_screens(role).values():
                    if stage.get("path"):
                        login_pages.add(stage["path"])
    except Exception:  # noqa: BLE001
        pass
    forms_used: dict[tuple, dict] = {}
    for (path, fidx, fname), g in groups.items():
        role = g["role"]
        fm = form_index.get((path, fidx, role))
        if not fm:
            continue
        field = next((f for f in fm["fields"] if f["name"] == fname), None)
        if not field:
            continue
        per_field = [{"kind": e["kind"], "value": e["value"]} for e in g["rules"].values()]
        fkey = (path, fidx, role)
        forms_used.setdefault(fkey, {"fm": fm, "rules": {}})["rules"][fname] = per_field
    # valid data for each form, honouring every known constraint
    base_values: dict[tuple, dict] = {}
    for fkey, info in forms_used.items():
        fm = info["fm"]
        values = {}
        for f in fm["fields"]:
            if not f["name"]:
                continue
            v = valid_value(f, info["rules"].get(f["name"]))
            if v is None:
                continue
            if f["type"] == "checkbox" and not f.get("required"):
                continue
            if not f.get("required") and not info["rules"].get(f["name"]) and f["type"] not in ("select",):
                continue
            values[f["name"]] = v
        base_values[fkey] = values
        path, fidx, role = fkey
        if path in login_pages:
            continue
        add(f"form_valid:{path}:{fidx}:{role}", "form_valid", "form_valid",
            f"{by_path.get(path, {}).get('name', path)}: a fully valid submission is accepted",
            role, path, {"form": fidx, "form_id": fm["id"], "values": values,
                         "submit_text": fm.get("submit_text")})

    for (path, fidx, fname), g in groups.items():
        role = g["role"]
        fkey = (path, fidx, role)
        if fkey not in base_values:
            continue
        fm = forms_used[fkey]["fm"]
        field = next(f for f in fm["fields"] if f["name"] == fname)
        base = base_values[fkey]
        valid = base.get(fname) or valid_value(field) or ""
        kinds = {e["kind"] for e in g["rules"].values()}
        label = g["label"]
        for e in g["rules"].values():
            kind, val = e["kind"], e["value"] or {}
            oracle = "decided" if "Decided" in e["statuses"] else "srs"
            common = {"form": fidx, "form_id": fm["id"], "field": fname, "label": label, "kind": kind,
                      "base": base, "rule_value": val}
            if kind == "options":
                add(f"options:{path}:{fname}", "field_options", "options",
                    f"{label} offers exactly: {', '.join(val.get('options', []))}", role, path,
                    {**common, "expected": val.get("options", [])}, e["rule_ids"], e["req_ids"], oracle)
                continue
            if kind in ("max_length", "exact_length") and field.get("maxlength"):
                want = int(val.get("max", val.get("length")))
                add(f"attribute:{path}:{fname}:maxlength", "field_attribute", "attribute",
                    f"{label} input is limited to {want} characters in the form", role, path,
                    {**common, "attribute": "maxlength", "expected": str(want)}, e["rule_ids"], e["req_ids"], oracle)
            bad = invalid_values(kind, val, field, valid, kinds)
            if bad:
                add(f"field_reject:{path}:{fname}:{kind}", "field_rejects", "field",
                    f"{label} rejects {', '.join(d for _, d in bad)}", role, path,
                    {**common, "values": [v for v, _ in bad], "descriptions": [d for _, d in bad]},
                    e["rule_ids"], e["req_ids"], oracle)
            if kind == "file_types":
                types = [t.lower() for t in val.get("types") or []][:4]
                add(f"field_accept:{path}:{fname}:{kind}", "field_accepts", "field",
                    f"{label} accepts {', '.join(t.upper() for t in types)} files", role, path,
                    {**common, "values": [f"@file:sample.{t}" for t in types],
                     "descriptions": [f"a small .{t} file" for t in types]}, e["rule_ids"], e["req_ids"], oracle)
            if kind == "file_max_size":
                kb = int(val["kb"])
                under = max(1, kb - max(64, kb // 20))
                ext = valid.rsplit(".", 1)[-1] if valid.startswith("@file:") else "pdf"
                add(f"field_accept:{path}:{fname}:{kind}", "field_accepts", "field",
                    f"{label} accepts a file just under {kb / 1024:g} MB" if kb >= 1024 else f"{label} accepts a file just under {kb} KB",
                    role, path, {**common, "values": [f"@file:near_limit.{ext}:{under}"],
                                 "descriptions": [f"a {under} KB file (limit {kb} KB)"]}, e["rule_ids"], e["req_ids"], oracle)
            if kind in ("max_length", "length_range"):
                n = int(val["max"])
                add(f"field_accept:{path}:{fname}:{kind}", "field_accepts", "field",
                    f"{label} accepts exactly {n} characters", role, path,
                    {**common, "values": [_len_value(valid, n, guess_semantic(field))],
                     "descriptions": [f"{n} characters (at the limit)"]}, e["rule_ids"], e["req_ids"], oracle)

    # ---- access rules ------------------------------------------------------------
    access_seen = set()
    for r in rules:
        if r["kind"] not in ("access_only", "access_deny") or r["status"] not in USABLE:
            continue
        oracle = "srs" if r["source"] in ("srs-text", "srs-table") else "decided"
        for m in r.get("matched") or []:
            allowed = m.get("allowed") or []
            for role in m.get("deny") or []:
                if (role, m["path"]) in access_seen:
                    continue
                access_seen.add((role, m["path"]))
                who = "anonymous visitor" if role == "anonymous" else role
                add(f"access:{role}:{m['path']}", "access_denied", "access",
                    f"{who.capitalize()} is blocked from {m['title']} ({m['path']})", role, m["path"],
                    {"allowed": allowed, "screen": m["title"]}, [r["id"]], [r["req_id"]], oracle)

    # ---- baseline: login enforced for every authenticated-only screen -------------
    for path, e in by_path.items():
        if "anonymous" in e["roles"] or not e["roles"] or project.is_login_path(path):
            continue
        if ("anonymous", path) in access_seen:
            continue
        access_seen.add(("anonymous", path))
        add(f"access:anonymous:{path}", "access_denied", "access",
            f"Anonymous visitor must log in before opening {e['name']} ({path})", "anonymous", path,
            {"allowed": e["roles"], "screen": e["name"]}, [], [], "baseline")

    # ---- baseline: pages load, links work, accessibility ----------------------------
    a11y_done = set()
    links_by_role: dict[str, dict[str, str]] = {}
    for s in screens:
        reach = s["status"] < 400 or s["status"] >= 500
        final_login = project.is_login_path(project.rel(s["final_url"] or ""))
        if final_login and not project.is_login_path(s["path"]):
            continue
        if norm(s["title"]) == "access denied" or s["status"] in (401, 403):
            continue
        if reach:
            add(f"page:{s['role']}:{s['path']}", "page_smoke", "page",
                f"{s['path']} loads for {s['role']} without errors" + (f" within {max_load} ms" if max_load else ""),
                s["role"], s["path"], {"max_load_ms": max_load},
                [r["id"] for r in rules if r["kind"] == "perf_max_load" and r["status"] in USABLE],
                [r["req_id"] for r in rules if r["kind"] == "perf_max_load" and r["status"] in USABLE])
        for link in s["links"] or []:
            href = link["href"]
            if not project.is_internal(href):
                continue
            p = project.rel(href)
            if any(x in p.lower() for x in project.cfg["explore"]["exclude_patterns"]):
                continue
            links_by_role.setdefault(s["role"], {}).setdefault(p, s["path"])
        if s["status"] < 400 and s["path"] not in a11y_done and not (project.is_login_path(s["path"]) and "?" in s["path"]):
            a11y_done.add(s["path"])
            add(f"a11y:{s['path']}", "a11y_basic", "a11y", f"{s['path']} meets basic accessibility checks",
                s["role"], s["path"], {})
    for role, links in links_by_role.items():
        add(f"links:{role}", "links_ok", "links", f"Every internal link seen by {role} opens without error",
            role, "", {"links": [{"href": h, "on": on} for h, on in sorted(links.items())]})

    # ---- workflows written by the QA lead ----------------------------------------------
    for wf in project.cfg.get("workflows") or []:
        add(f"workflow:{wf['id']}", "workflow", "workflow", f"{wf['id']}: {wf.get('title', '')}",
            ",".join(dict.fromkeys(st["role"] for st in wf.get("steps", []))), "",
            {"steps": wf.get("steps", []), "workflow_id": wf["id"]},
            [r["id"] for r in rules if r["req_id"] in wf.get("rule_ids", [])], wf.get("rule_ids", []), "workflow")

    # ---- APIs the screens call (and documented ones) ------------------------------------
    if project.cfg.get("api", {}).get("enabled", True):
        _design_api(project, store, rules, add, max_load)

    # ---- security basics, load, visual snapshots ----------------------------------------
    _design_extras(project, store, screens, rules, add, max_load, by_path)

    # ---- manual test cases imported from Excel and approved for automation --------------
    for m in store.all("SELECT * FROM manual_cases WHERE status='approved' ORDER BY id"):
        conv = m["converted"] or {}
        add(f"manual:{m['id']}", "manual_converted", "manual", f"{m['id']}: {m['title']}", m["role"] or "anonymous",
            conv.get("start") or "", {"steps": conv.get("steps") or [], "manual_id": m["id"]},
            [], conv.get("req_ids") or [], "manual")

    # ---- functional cases drafted like a manual tester (login, navigation, forms, search) ---------
    from agentqa.agents import analyst
    try:
        cases += analyst.draft(project, store, cases)
    except Exception as exc:  # noqa: BLE001
        from agentqa.util import warn
        warn(f"[analyst] functional cases could not be drafted: {exc}")

    # ---- requirements nothing above covered: the Test Case Generation agent (template cases) -------
    from agentqa.agents import casegen
    try:
        gen = casegen.generate(project, store, cases)
        for i, c in enumerate(gen):
            c["params"]["order"] = (analyst.MODULE_ORDER.index("Requirements"), i)
        cases += gen
    except Exception as exc:  # noqa: BLE001
        from agentqa.util import warn
        warn(f"[casegen] template cases could not be drafted: {exc}")

    # ---- live production portals: read-only checks only, and say what was left out --------------
    changing = {"form_valid", "field_rejects", "field_accepts", "performance_load", "workflow", "manual_converted"}

    def touches_production(c: dict) -> bool:
        # the case's own page, and every step's page or role: a workflow that starts on a test site may approve on a
        # production one
        from agentqa.execution import _apps
        if c["path"] and project.is_production(c["path"]):
            return True
        return any(project.is_production(a) for a in _apps(project, c))
    prod_skipped = [c for c in cases if touches_production(c) and (
        c["type"] in changing or (c["type"] == "functional" and (c["params"] or {}).get("module") in ("Forms", "Workflows")))]
    if prod_skipped:
        keys = {c["key"] for c in prod_skipped}
        cases = [c for c in cases if c["key"] not in keys]
        live.emit("designer", "skip", f"{len(prod_skipped)} case(s) that submit data or load the portal left out: their "
                  f"application is marked Production", level="warn")
    store.set_meta("production_skipped", [{"key": c["key"], "title": c["title"], "path": c["path"]} for c in prod_skipped])

    # ---- write -----------------------------------------------------------------------
    order = ["functional", "access", "api_access", "isolation", "security", "workflow", "page", "form_valid", "field",
             "options", "api", "performance", "manual", "attribute", "links", "a11y", "visual"]

    def sort_key(c):
        g = order.index(c["group"])
        if c["group"] == "functional":
            mod, i = c["params"].get("order") or (9, 0)
            return (g, mod, "", i, "", "")
        return (g, 0, c["path"] or "", 0, c["role"] or "", c["key"])
    cases.sort(key=sort_key)
    live.emit("designer", "start", f"Designing tests from {sum(1 for r in rules if r['status'] in USABLE)} usable rule(s) "
              f"and {len(by_path)} screen(s)")
    from agentqa import contracts
    for c in cases:                                # the standard template's fields, on every case
        c["params"] = c.get("params") or {}
        c["params"].setdefault("test_type", contracts.test_type(c))
        c["params"].setdefault("objective", contracts.objective(c))
    for i, c in enumerate(cases, 1):
        prev = previous.get(c["key"])
        live.emit("designer", "case", f"TC-{i:04d} {c['title']}", case=f"TC-{i:04d}", ctype=c["type"],
                  group=c["group"], priority=c.get("priority") or PRIORITY[c["group"]], role=c["role"], path=c["path"] or None,
                  oracle=c["oracle_source"], reqs=c["req_ids"] or None)
        store.insert("cases", {
            "id": f"TC-{i:04d}", "key": c["key"], "seq": i, "type": c["type"], "title": c["title"],
            "role": c["role"], "path": c["path"], "params": c["params"], "rule_ids": c["rule_ids"],
            "req_ids": c["req_ids"], "priority": c.get("priority") or PRIORITY[c["group"]], "oracle_source": c["oracle_source"],
            "status": prev["status"] if prev else "proposed", "created_at": now()})
    _log_case_changes(store, previous, cases)
    try:
        reqs_agent.check(project, store)          # dispositions now that the cases exist
    except Exception as exc:  # noqa: BLE001
        from agentqa.util import warn
        warn(f"[requirements] coverage check failed: {exc}")
    return plan(project, store)


def _log_case_changes(store: Store, previous: dict, cases: list[dict]) -> None:
    """Change log: cases added or dropped by this design, with the reason the agents had."""
    new_keys = {c["key"] for c in cases}
    added = [c for c in cases if c["key"] not in previous]
    dropped = [k for k in previous if k not in new_keys]
    if not previous:
        store.insert("change_log", {"at": now(), "agent": "designer", "object": "plan", "object_id": "-",
                                    "change": f"first design: {len(cases)} case(s)", "justification":
                                    "derived from the SRS rules, the app map and the recorded logins", "by": "agents"})
        return
    for c in added[:200]:
        store.insert("change_log", {"at": now(), "agent": "designer", "object": "case", "object_id": c["key"],
                                    "change": f"added: {c['title'][:160]}", "justification": f"oracle: {c['oracle_source']}; "
                                    f"requirements {', '.join(c['req_ids']) or '-'}", "by": "agents"})
    for k in dropped[:200]:
        store.insert("change_log", {"at": now(), "agent": "designer", "object": "case", "object_id": k,
                                    "change": "dropped", "justification": "its rule, screen or requirement changed or was "
                                    "answered differently", "by": "agents"})


def _design_api(project: Project, store: Store, rules: list[dict], add, max_load) -> None:
    eps = store.all("SELECT * FROM endpoints WHERE method='GET' ORDER BY id")
    if not eps:
        return
    api_ms = int(project.cfg.get("api", {}).get("max_ms") or 0) or None
    by_pat: dict[str, dict] = {}
    for e in eps:
        g = by_pat.setdefault(e["pattern"], {"traffic": {}, "probed": {}, "initiators": set(), "keys": [],
                                              "shape": "", "documented": False})
        ok = 200 <= (e["status"] or 0) < 300
        g["documented"] = g["documented"] or bool(e["documented"])
        if e["source"] == "traffic":
            g["initiators"].add(e["initiator"])
            if ok:
                g["traffic"].setdefault(e["role"], e["path"])
        elif ok:
            g["probed"].setdefault(e["role"], e["path"])
        if ok and e["keys"] and not g["keys"]:
            g["keys"], g["shape"] = e["keys"], e["shape"]
    deny_by_path: dict[str, dict] = {}
    for r in rules:
        if r["kind"] in ("access_only", "access_deny") and r["status"] in USABLE:
            for m in r.get("matched") or []:
                for role in m.get("deny") or []:
                    deny_by_path.setdefault(m["path"], {}).setdefault(role, (r, m))
    peers = set(project.peers())
    for pat, g in sorted(by_pat.items()):
        # who may call it: the roles whose own screens call it; documented-only APIs fall back to what answered
        allowed = g["traffic"] or g["probed"]
        if not allowed:
            continue
        role0, example = next(((r, p) for r, p in allowed.items() if r != "anonymous"), next(iter(allowed.items())))
        add(f"api:{pat}", "api_smoke", "api", f"GET {pat} answers {role0} with the expected fields"
            + (f" within {api_ms} ms" if api_ms else ""), role0, example,
            {"method": "GET", "pattern": pat, "keys": g["keys"], "shape": g["shape"], "max_ms": api_ms,
             "documented": g["documented"]}, [], [], "baseline")
        if "anonymous" not in allowed:
            add(f"api_access:anonymous:{pat}", "api_access", "api_access", f"GET {pat} refuses callers who are not logged in",
                "anonymous", example, {"pattern": pat, "allowed": sorted(allowed), "screen": None}, [], [], "baseline")
        inits = [i for i in g["initiators"] if i]
        if inits and g["traffic"]:
            deny = set.intersection(*[set(deny_by_path.get(i, {})) for i in inits])
            for role in sorted(deny - set(g["traffic"]) - {"anonymous"}):
                rule, m = deny_by_path[inits[0]][role]
                oracle = "srs" if rule["source"] in ("srs-text", "srs-table") else "decided"
                add(f"api_access:{role}:{pat}", "api_access", "api_access",
                    f"{role.capitalize()} is refused by GET {pat}, like the {m['title']} screen that uses it",
                    role, example, {"pattern": pat, "allowed": sorted(g["traffic"]), "screen": m["title"]},
                    [rule["id"]], [rule["req_id"]], oracle)
        if "{n}" in pat or "{id}" in pat:
            for role, path in g["traffic"].items():
                peer = f"{role}__peer"
                if peer in peers:
                    add(f"isolation:{role}:{pat}", "record_isolation", "isolation",
                        f"Another {role} cannot read {path} (a record that belongs to the first {role})",
                        role, path, {"pattern": pat, "peer": peer}, [], [], "baseline")


def _design_extras(project: Project, store: Store, screens: list[dict], rules: list[dict], add, max_load,
                   by_path: dict) -> None:
    """Security basics, load checks and visual snapshots."""
    cfg = project.cfg
    login_path = cfg["login"]["url"]
    roles = [r for r in project.roles()]
    reachable = [s for s in screens if (s["status"] or 0) < 400 and "?" not in s["path"]
                 and not project.is_login_path(project.rel(s["final_url"] or ""))
                 and norm(s["title"]) != "access denied"]
    if cfg.get("security", {}).get("enabled", True) and roles:
        from agentqa.login_flow import needs_person
        # the logout test needs its own login: use a role that does not need you to type an OTP
        role0 = next((r for r in roles if not needs_person(project, r)), roles[0])
        add("security:headers", "security_headers", "security", "Responses send the standard security headers",
            "anonymous", "/", {}, [], [], "baseline")
        protected = next((p for p, e in by_path.items() if role0 in e["roles"] and "anonymous" not in e["roles"]
                          and not project.is_login_path(p) and "{" not in path_pattern(p)), None)
        if protected:
            add(f"security:session:{role0}", "security_session", "security",
                "Logging in issues a new session, and logging out ends it on the server", role0, protected,
                {"logout_url": cfg.get("security", {}).get("logout_url") or "/logout", "protected": protected},
                [], [], "baseline")
        posts = sorted({(s["path"], s["role"]) for s in reachable for f in (s["forms"] or [])
                        if (f.get("method") or "get") == "post" and not any(x["type"] == "password" for x in f["fields"])})
        if posts:
            path, role = posts[0]
            add("security:csrf", "security_csrf", "security", "Forms that change data carry an anti-forgery token",
                role, path, {"forms": [{"path": p, "role": r} for p, r in posts[:6]]}, [], [], "baseline")
    from agentqa.login_flow import otp_source
    otp_roles = [r for r in (store.get_meta("otp_roles") or []) if otp_source(project, r) in ("inbox", "api")]
    if cfg.get("security", {}).get("enabled", True) and otp_roles:
        orules = [r for r in rules if r["kind"] == "otp_single_use" and r["status"] in USABLE]
        add(f"security:otp:{otp_roles[0]}", "security_otp", "security",
            f"A one-time password works only once (login as {otp_roles[0]})", otp_roles[0], login_path,
            {"role": otp_roles[0]}, [r["id"] for r in orules], [r["req_id"] for r in orules],
            "srs" if orules else "baseline")
    perf = cfg.get("performance", {})
    if perf.get("enabled", True):
        perf_rules = [r for r in rules if r["kind"] == "perf_max_load" and r["status"] in USABLE]
        limit = max_load or 3000
        picks, seen = [], set()
        for s in sorted(reachable, key=lambda s: (s["path"] != "/dashboard", -(len(s["forms"] or [])), s["load_ms"] or 0)):
            if (s["role"] == "anonymous" or s["path"] in seen or project.is_login_path(s["path"])
                    or s["path"] == "/" or s["path"].startswith("/help")):
                continue
            seen.add(s["path"])
            picks.append(s)
            if len(picks) >= int(perf.get("pages", 3)):
                break
        for s in picks:
            add(f"perf:{s['role']}:{s['path']}", "performance_load", "performance",
                f"{s['path']} stays under {limit} ms for {perf.get('users', 5)} users at once", s["role"], s["path"],
                {"users": int(perf.get("users", 5)), "seconds": int(perf.get("seconds", 8)), "limit_ms": limit,
                 "max_error_rate": float(perf.get("max_error_rate", 0.01))},
                [r["id"] for r in perf_rules], [r["req_id"] for r in perf_rules],
                "srs" if perf_rules else "baseline")
    vis = cfg.get("visual", {})
    if vis.get("enabled", True):
        done = set()
        for s in reachable:
            key = f"{s['role']}{s['path']}".replace("/", "_").strip("_") or s["role"]
            if (s["role"], s["path"]) in done or path_pattern(s["path"]) != s["path"]:
                continue
            done.add((s["role"], s["path"]))
            add(f"visual:{s['role']}:{s['path']}", "visual_snapshot", "visual",
                f"{s['path']} looks the same for {s['role']} as its approved snapshot", s["role"], s["path"],
                {"key": key, "threshold": float(vis.get("threshold", 0.002)), "mask": vis.get("mask") or [],
                 "full_page": bool(vis.get("full_page", True))}, [], [], "snapshot")


def plan(project: Project, store: Store) -> dict:
    """Test Planner: summarises scope and risk and resets approval if the case set changed."""
    cases = store.all("SELECT type, priority, role, status, key FROM cases")
    digest = hashlib.sha1("".join(sorted(c["key"] for c in cases)).encode(), usedforsecurity=False).hexdigest()[:12]
    req_total = store.scalar("SELECT COUNT(*) FROM requirements")
    covered = {x for c in store.all("SELECT req_ids FROM cases") for x in (c["req_ids"] or [])}
    rules_by_status = {r["status"]: r["n"] for r in store.all("SELECT status, COUNT(*) n FROM rules GROUP BY status")}
    summary = {
        "digest": digest,
        "cases": len(cases),
        "by_type": _count(cases, "type"),
        "by_priority": _count(cases, "priority"),
        "by_role": _count(cases, "role"),
        "by_status": _count(cases, "status"),
        "requirements": req_total,
        "requirements_covered": len(covered),
        "rules_by_status": rules_by_status,
        "open_questions": store.scalar("SELECT COUNT(*) FROM questions WHERE status='open'"),
        "risk_notes": [
            "P1: logins (valid and wrong details, OTP), access control, multi-role workflows, page failures and each form's happy path.",
            "P2: server-side field validation, option lists and internal links.",
            "P3: client-side form attributes, accessibility and visual snapshots.",
            "Not tested until answered: rules that are Divergent, SRS-only, App-only, Ambiguous or Proposed.",
        ],
    }
    old = store.one("SELECT * FROM plan WHERE id=1")
    approved = 1 if old and old["approved"] and (old["summary"] or {}).get("digest") == digest else 0
    store.insert("plan", {"id": 1, "approved": approved, "approved_at": old["approved_at"] if approved and old else None,
                          "summary": summary}, replace=True)
    live.emit("designer", "summary", f"Plan: {summary['cases']} cases covering {summary['requirements_covered']} of "
              f"{summary['requirements']} requirements", by_type=summary["by_type"], by_priority=summary["by_priority"])
    return summary


def approve(store: Store, case_types: list[str] | None = None, case_ids: list[str] | None = None,
            reject: bool = False) -> int:
    status = "rejected" if reject else "approved"
    if case_ids:
        for cid in case_ids:
            store.update("cases", "id", cid, {"status": status})
        n = len(case_ids)
        live.emit("designer", "approve", f"{'Rejected' if reject else 'Approved'} {n} case(s)", ids=case_ids)
    elif case_types:
        n = 0
        for t in case_types:
            n += store.scalar("SELECT COUNT(*) FROM cases WHERE type=? AND status='proposed'", [t])
            store.exec("UPDATE cases SET status=? WHERE type=? AND status='proposed'", [status, t])
    else:
        n = store.scalar("SELECT COUNT(*) FROM cases WHERE status='proposed'")
        store.exec("UPDATE cases SET status=? WHERE status='proposed'", [status])
        store.exec("UPDATE plan SET approved=1, approved_at=? WHERE id=1", [now()])
        live.emit("designer", "approve", f"Plan approved: {n} case(s)", level="ok")
    return n


def _count(rows, key):
    out: dict[str, int] = {}
    for r in rows:
        out[r[key] or "-"] = out.get(r[key] or "-", 0) + 1
    return out


_ = string  # keep import for future character-class generators
