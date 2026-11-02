"""Triage + Bug Reporter agent.

Groups failures by root-cause signature (one defect per broken screen,
field, link or workflow), sets severity, and writes defect drafts with steps,
expected vs actual, evidence and the requirement IDs. Drafts wait for a
person to confirm them (gate 2) before export. Earlier decisions persist by
signature: a rejected defect stays rejected, a confirmed one that no longer
fails is marked resolved.
"""
from __future__ import annotations

import csv
import re

import httpx

from agentqa import live
from agentqa.config import Project
from agentqa.llm import get_llm
from agentqa.store import Store, now
from agentqa.util import log, warn

SEVERITY_PRIORITY = {"Critical": "P1", "High": "P1", "Medium": "P2", "Low": "P3"}
SEV_ORDER = ["Critical", "High", "Medium", "Low"]


def _actual(msg: str) -> str:
    msg = re.sub(r"^\w+(Error|Exception)?: ", "", msg or "")
    return msg.replace("DEFECT: ", "").strip()


def _steps(case: dict, base) -> list[str]:
    """Steps to reproduce. `base` is the Project (several portals) or a base URL."""
    p = case["params"] or {}
    role = case["role"]
    login = "Stay logged out." if role == "anonymous" else f"Log in as {role}."
    u = base.url(case["path"] or "/") if hasattr(base, "url") else base + (case["path"] or "")
    base_url = base.url("/", base.app_of(role)).rstrip("/") if hasattr(base, "url") else base
    t = case["type"]
    if t == "access_denied":
        return [login, f"Type {u} into the address bar and open it directly."]
    if t == "page_smoke":
        return [login, f"Open {u}."]
    if t == "a11y_basic":
        return [login, f"Open {u}.", "Inspect images, form labels, page title and the html lang attribute."]
    if t in ("field_rejects", "field_accepts"):
        vals = ", ".join(f"{k}={v!r}" for k, v in (p.get("base") or {}).items() if k != p.get("field"))
        return [login, f"Open {u}.", f"Fill the form with valid data ({vals}).",
                f"Set {p.get('label')} to each value: " + "; ".join(p.get("descriptions") or []),
                "Submit the form (browser validation bypassed, so the server's own validation is tested)."]
    if t == "form_valid":
        return [login, f"Open {u}.", f"Fill every field with valid data: {p.get('values')}", "Submit the form."]
    if t in ("field_options", "field_attribute"):
        return [login, f"Open {u}.", f"Inspect the {p.get('label')} field."]
    if t == "links_ok":
        return [login, "Open the page listed under Actual and click the broken link."]
    if t == "workflow":
        return [f"{i}. As {st['role']}: " + ", ".join(f"{k} {v}" for k, v in st.items() if k != "role")
                for i, st in enumerate(p.get("steps") or [], 1)]
    if t in ("api_smoke", "api_access"):
        return [login, f"Send GET {u} (for example, open it in the browser's address bar)."]
    if t == "record_isolation":
        return [f"Log in as the first {role} user and note the record address {u}.",
                f"Log in as a different {role} user ({p.get('peer', '').replace('__peer', '')} account 2).",
                f"Open {u}: the other user's record is returned."]
    if t == "security_headers":
        return [f"Open {u} with the browser's developer tools (F12), Network tab.", "Read the response headers."]
    if t == "security_session":
        return [login, f"Copy the session cookie, then log out through {base_url}{p.get('logout_url', '/logout')}.",
                f"Put the copied cookie back and open {u}: it still works."]
    if t == "security_csrf":
        return [login, "Open each listed form and look for a hidden anti-forgery token field: there is none."]
    if t == "security_otp":
        return [f"Log in as {p.get('role')} with the password and the OTP sent by SMS; note the OTP.", "Log out.",
                "Log in again with the password, and on the OTP screen type the OTP from the first login.",
                "The portal accepts it and opens the dashboard."]
    if t == "performance_load":
        return [login, f"Send GET {u} from {p.get('users')} users at once for {p.get('seconds')} seconds.",
                "Measure the 95th percentile response time and the error rate."]
    if t == "manual_converted":
        return [f"{i}. {st.get('text') or st}" for i, st in enumerate(p.get("steps") or [], 1)]
    if t == "functional":
        pre = [f"Precondition: {p['preconditions']}"] if p.get("preconditions") else []
        data = [f"Test data: {p['test_data']}"] if p.get("test_data") and p["test_data"] != "-" else []
        return pre + data + [f"{i}. {x}" for i, x in enumerate(p.get("steps_text") or [], 1)]
    return [login, f"Open {u}."]


def _signature_and_meta(case: dict, message: str) -> list[dict]:
    """One or more (signature, severity, title) groups for a failed case."""
    t, p, path = case["type"], case["params"] or {}, case["path"]
    actual = _actual(message)
    if t == "access_denied":
        return [{"sig": f"access:{path}", "severity": "Critical",
                 "title": f"{p.get('screen') or path} ({path}) is open to roles that must be blocked"}]
    if t == "page_smoke":
        sev = "High" if re.search(r"HTTP 5\d\d|server error", actual) else ("Medium" if "HTTP" in actual else "Low")
        what = "fails to load" if sev != "Low" else "is slower than the limit"
        return [{"sig": f"page:{path}", "severity": sev, "title": f"{path} {what}: {actual.split(': ', 1)[-1][:90]}"}]
    if t == "links_ok":
        out = []
        for href, code, on in re.findall(r"(\S+) -> HTTP (\d+) \(linked from ([^)]+)\)", actual):
            if code.startswith("5"):
                out.append({"sig": f"page:{href}", "severity": "High",
                            "title": f"{href} fails to load: HTTP {code}", "detail": f"{href} -> HTTP {code} (linked from {on})"})
            else:
                out.append({"sig": f"link:{href}", "severity": "Medium",
                            "title": f"Broken link to {href} (HTTP {code}) on {on}", "detail": f"{href} -> HTTP {code} (linked from {on})"})
        return out or [{"sig": f"links:{case['role']}", "severity": "Medium", "title": "Broken internal links"}]
    if t in ("field_rejects", "field_accepts", "field_attribute", "field_options"):
        label = p.get("label") or p.get("field")
        if t == "field_options":
            return [{"sig": f"field:{path}:{p.get('field')}:options", "severity": "Medium",
                     "title": f"{label} offers the wrong options on {path}"}]
        if t == "field_accepts":
            return [{"sig": f"field:{path}:{p.get('field')}:accept", "severity": "High",
                     "title": f"{label} on {path} rejects valid input"}]
        return [{"sig": f"field:{path}:{p.get('field')}", "severity": "Medium",
                 "title": f"{label} on {path} accepts invalid input"}]
    if t == "form_valid":
        return [{"sig": f"form:{path}", "severity": "High", "title": f"Valid submission on {path} is not accepted"}]
    if t == "a11y_basic":
        return [{"sig": f"a11y:{path}", "severity": "Low", "title": f"Accessibility gaps on {path}"}]
    if t == "workflow":
        return [{"sig": f"workflow:{p.get('workflow_id')}", "severity": "High",
                 "title": f"Workflow {p.get('workflow_id')} breaks: {actual[:90]}"}]
    pat = p.get("pattern") or path
    if t == "api_smoke":
        if "missing field" in actual:
            return [{"sig": f"api:{pat}", "severity": "Medium",
                     "title": f"API GET {pat} no longer returns fields the screens use"}]
        sev = "High" if re.search(r"HTTP 5\d\d", actual) else "Medium"
        return [{"sig": f"api:{pat}", "severity": sev, "title": f"API GET {pat} fails: {actual.split(': ', 1)[-1][:80]}"}]
    if t == "api_access":
        if case["role"] == "anonymous":
            return [{"sig": f"api-login:{pat}", "severity": "Critical", "title": f"API GET {pat} answers without login"}]
        return [{"sig": f"access:{pat}", "severity": "Critical",
                 "title": f"API GET {pat} is open to roles that must be blocked"
                          + (f" (the {p['screen']} screen is protected)" if p.get("screen") else "")}]
    if t == "record_isolation":
        return [{"sig": f"isolation:{pat}", "severity": "Critical",
                 "title": f"Users can read other users' records through GET {pat}"}]
    if t == "security_headers":
        return [{"sig": "security:headers", "severity": "Medium", "title": "Security headers are missing"}]
    if t == "security_session":
        what = "Session is not ended on the server at logout" if "after logout" in actual else "Session fixation at login"
        return [{"sig": "security:session", "severity": "High", "title": what}]
    if t == "security_csrf":
        return [{"sig": "security:csrf", "severity": "Low" if "mitigated" in actual else "Medium",
                 "title": "Forms that change data have no anti-forgery (CSRF) token"}]
    if t == "performance_load":
        return [{"sig": f"perf:{path}", "severity": "High", "title": f"{path} is too slow or fails under load"}]
    if t == "security_otp":
        return [{"sig": "security:otp", "severity": "High", "title": "A used one-time password (OTP) is accepted again"}]
    if t == "functional":
        m = re.search(r"got 'Not found' at (\S+)", actual)
        if m:
            return [{"sig": f"link:{m.group(1)}", "severity": "Medium", "title": f"{m.group(1)} is missing (HTTP 404)"}]
        sig = p.get("sig") or f"func:{case['key']}"
        title = p.get("defect_title") or f"{case['title']} - failed"
        return [{"sig": sig, "severity": p.get("severity") or "Medium", "title": title}]
    if t == "manual_converted":
        m = re.search(r"expected access to be denied, but (\S+) opened", actual)
        if m:
            return [{"sig": f"access:{m.group(1)}", "severity": "Critical",
                     "title": f"{m.group(1)} is open to roles that must be blocked"}]
        m = re.search(r"got 'Not found' at (\S+)", actual)
        if m:
            return [{"sig": f"link:{m.group(1)}", "severity": "Medium", "title": f"{m.group(1)} is missing (HTTP 404)"}]
        return [{"sig": f"manual:{p.get('manual_id')}", "severity": "Medium",
                 "title": f"Manual test {p.get('manual_id')} fails: {actual[:90]}"}]
    return [{"sig": f"{t}:{path}", "severity": "Medium", "title": f"{case['title']} failed"}]


def triage(project: Project, store: Store, run_id: str | None = None) -> dict:
    run_id = run_id or store.get_meta("last_run")
    if not run_id:
        raise RuntimeError("No test run yet. Run 'agentqa run' first.")
    cases = {c["id"]: c for c in store.all("SELECT * FROM cases")}
    results = store.all("SELECT * FROM results WHERE run_id=? AND category='defect'", [run_id])
    reqs = {r["id"]: r for r in store.all("SELECT id, text FROM requirements")}
    groups: dict[str, dict] = {}
    for res in results:
        case = cases.get(res["case_id"])
        if not case:
            continue
        for meta in _signature_and_meta(case, res["message"]):
            g = groups.setdefault(meta["sig"], {"meta": meta, "cases": [], "actual": [], "roles": set(),
                                                 "evidence": [], "rule_ids": set(), "req_ids": set(),
                                                 "expected": []})
            if SEV_ORDER.index(meta["severity"]) < SEV_ORDER.index(g["meta"]["severity"]):
                g["meta"]["severity"] = meta["severity"]
            g["cases"].append(case)
            g["actual"].append(meta.get("detail") or _actual(res["message"]))
            g["roles"].add(case["role"])
            g["evidence"] += res["evidence"] or []
            if case["type"] != "page_smoke" or "took" in (res["message"] or ""):
                # a page smoke test cites the load-time rule; only blame it for slowness
                g["rule_ids"].update(case["rule_ids"] or [])
                g["req_ids"].update(case["req_ids"] or [])
            g["expected"].append(((case["params"] or {}).get("expected") if case["type"] == "functional" else None)
                                 or case["title"])

    # findings that need no test run: confirmed-missing features and fields
    for r in store.all("SELECT * FROM rules WHERE status='Missing in app'"):
        field = r.get("field")
        sig = f"missing:field:{field.strip().lower()}" if field else f"missing:{r['req_id']}:{r['kind']}"
        what = f"the '{field}' field" if field else (reqs.get(r["req_id"], {}).get("text") or r.get("target") or "")
        g = groups.setdefault(sig, {"meta": {"sig": sig, "severity": "High",
                                             "title": f"Missing from the app: {what[:100]}"},
                                    "cases": [], "actual": ["Not present in the application (confirmed by reviewer)"],
                                    "roles": set(), "evidence": [], "rule_ids": set(), "req_ids": set(),
                                    "expected": []})
        g["roles"].update(r["roles"] or [])
        g["rule_ids"].add(r["id"])
        g["req_ids"].add(r["req_id"])
        g["expected"].append(reqs.get(r["req_id"], {}).get("text", what))

    # findings from the Exploratory Tester share signatures with test failures, so they merge
    xrun, zrun = store.get_meta("exploratory_run"), store.get_meta("zap_run")
    consumed = store.get_meta("triage_consumed") or {}
    fresh_runs = {r for r in (xrun, zrun) if r and r not in (consumed.get("exploratory"), consumed.get("zap"))}
    for f in store.all("SELECT * FROM findings WHERE run_id IN (?, ?) ORDER BY id", [xrun or "-", zrun or "-"]):
        g = groups.setdefault(f["sig"], {"meta": {"sig": f["sig"], "severity": f["severity"], "title": f["title"]},
                                         "cases": [], "actual": [], "roles": set(), "evidence": [],
                                         "rule_ids": set(), "req_ids": set(), "expected": []})
        if SEV_ORDER.index(f["severity"]) < SEV_ORDER.index(g["meta"]["severity"]):
            g["meta"]["severity"] = f["severity"]
        g["actual"].append(f["detail"])
        g["roles"].update(f["roles"] or [])
        g["evidence"] += f["evidence"] or []
        g["expected"].append(f["expected"])
        g.setdefault("steps", (f["steps"] or "").split("\n"))
        g.setdefault("url", f["url"])
        g["found_by"] = "zap" if str(f["run_id"]).startswith("Z-") else "exploratory"
        if f["run_id"] in fresh_runs:
            g["fresh_finding"] = True
        if f.get("rule_id"):
            g["rule_ids"].add(f["rule_id"])
            g["req_ids"].add(f["req_id"])

    previous = {d["signature"]: d for d in store.all("SELECT * FROM defects")}
    seq = store.scalar("SELECT MAX(seq) FROM defects") or 0
    seen = set()
    created = updated = 0
    llm = get_llm(project, "defects") if project.cfg["llm"].get("polish_defects") else None
    for sig, g in sorted(groups.items(), key=lambda kv: (SEV_ORDER.index(kv[1]["meta"]["severity"]), kv[0])):
        if not g["cases"] and not g.get("fresh_finding") and previous.get(sig):
            continue  # only old exploratory/ZAP evidence: no new verdict from it this run
        seen.add(sig)
        first = g["cases"][0] if g["cases"] else None
        roles = sorted(x for x in g["roles"] if x)
        steps = (_steps(first, project) if first else
                 g.get("steps") or ["Review the requirement against the application."])
        if first and first["type"] == "access_denied":
            steps = [f"As any of: {', '.join(roles)} (log in, or stay logged out for anonymous)",
                     f"Open {project.url(first['path'] or '/')} directly."]
        req_text = "; ".join(f"{rid}: {reqs[rid]['text']}" for rid in sorted(g["req_ids"]) if rid in reqs)
        expected = req_text or "; ".join(dict.fromkeys(g["expected"]))
        actual = "\n".join(dict.fromkeys(g["actual"]))
        title = g["meta"]["title"]
        if llm and llm.available():
            out = llm.chat_json("You write concise, factual bug titles for developers. Return JSON {\"title\": \"...\"} "
                                "under 90 characters. Do not invent facts.",
                                f"Expected: {expected}\nActual: {actual}\nDraft title: {title}", 80)
            if out and out.get("title"):
                title = str(out["title"])[:120]
        row = {"run_id": run_id, "case_ids": [c["id"] for c in g["cases"]], "signature": sig, "title": title,
               "severity": g["meta"]["severity"], "priority": SEVERITY_PRIORITY[g["meta"]["severity"]],
               "role": ", ".join(roles), "url": project.url(first["path"] or "/") if first else g.get("url", ""),
               "steps": "\n".join(steps), "expected": expected, "actual": actual,
               "evidence": g["evidence"][:12], "rule_ids": sorted(g["rule_ids"]), "req_ids": sorted(g["req_ids"])}
        old = previous.get(sig)
        if old and not row["case_ids"]:
            row["case_ids"] = old["case_ids"] or []   # found again by exploration only: keep the tests linked to it
        live.emit("triage", "defect", f"{g['meta']['severity']}: {title}", severity=g["meta"]["severity"], sig=sig,
                  cases=[c["id"] for c in g["cases"]] or None, roles=roles or None, reqs=sorted(g["req_ids"]) or None,
                  actual=actual[:300], found_by=g.get("found_by"),
                  level={"Critical": "bad", "High": "bad", "Medium": "warn"}.get(g["meta"]["severity"]))
        if old:
            status = old["status"]
            if status == "fixed" or (status == "resolved" and old.get("external_key")):
                status = "reopened"  # the tracker says fixed, but it still fails: tell the tracker
            elif status in ("resolved",):
                status = "draft"  # it is failing again
            store.update("defects", "id", old["id"], {**row, "status": status})
            updated += 1
        else:
            seq += 1
            store.insert("defects", {"id": f"DEF-{seq:03d}", "seq": seq, **row, "status": "draft",
                                     "created_at": now(), "notes": "", "external_key": None})
            created += 1
    resolved = 0
    store.set_meta("triage_consumed", {"exploratory": xrun, "zap": zrun, "run": run_id})
    # only a checked result counts: a Blocked or Not Run test says nothing about whether a defect is fixed
    executed = {r["case_id"] for r in store.all("SELECT case_id FROM results WHERE run_id=? AND category='pass'", [run_id])}
    fresh_kinds = {"zap" if str(r).startswith("Z-") else "exploratory" for r in fresh_runs}
    for sig, d in previous.items():
        if d["case_ids"] and not set(d["case_ids"]) & executed:
            continue  # none of its tests passed in this run (not run, blocked, or a partial re-run): no verdict
        if not d["case_ids"]:
            last = store.one("SELECT run_id FROM findings WHERE sig=? ORDER BY id DESC LIMIT 1", [sig])
            kind = "zap" if last and str(last["run_id"]).startswith("Z-") else "exploratory"
            if kind not in fresh_kinds:
                continue  # found only by an exploratory or ZAP run that did not run again: no verdict
        if sig not in seen and d["status"] in ("draft", "confirmed", "exported", "fixed", "reopened"):
            store.update("defects", "id", d["id"], {"status": "resolved", "notes": (d["notes"] or "") +
                                                     f"\nNot reproduced in {run_id}."})
            resolved += 1
    nfind = sum(1 for g in groups.values() if g.get("found_by"))
    live.emit("triage", "start" if not groups else "summary",
              f"{len(results)} failing test(s)" + (f" and {nfind} exploratory finding(s)" if nfind else "")
              + f" grouped into {len(groups)} defect(s); {resolved} resolved", run_id=run_id)
    counts = {s["severity"]: s["n"] for s in store.all(
        "SELECT severity, COUNT(*) n FROM defects WHERE status NOT IN ('rejected','resolved') GROUP BY severity")}
    store.set_meta("triage", {"run_id": run_id, "new": created, "updated": updated, "resolved": resolved, **counts})
    return {"run_id": run_id, "new": created, "updated": updated, "resolved": resolved, "open_by_severity": counts}


def set_defect_status(store: Store, defect_ids: list[str], status: str, note: str = "") -> None:
    for did in defect_ids:
        d = store.one("SELECT notes FROM defects WHERE id=?", [did])
        store.update("defects", "id", did, {"status": status,
                                            "notes": ((d or {}).get("notes") or "") + (f"\n{note}" if note else "")})


def export_csv(project: Project, store: Store, include_drafts: bool = False) -> str:
    """Jira-importable CSV of confirmed defects."""
    statuses = ("confirmed", "exported") + (("draft",) if include_drafts else ())
    rows = store.all(f"SELECT * FROM defects WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY seq", statuses)
    path = project.reports_dir / "defects.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Defect ID", "Summary", "Severity", "Priority", "Role", "URL", "Steps to reproduce",
                    "Expected result", "Actual result", "Requirement IDs", "Test cases", "Evidence", "Status"])
        for d in rows:
            w.writerow([d["id"], d["title"], d["severity"], d["priority"], d["role"], d["url"], d["steps"],
                        d["expected"], d["actual"], ", ".join(d["req_ids"] or []), ", ".join(d["case_ids"] or []),
                        "; ".join(e["path"] for e in d["evidence"] or []), d["status"]])
    return str(path)


# Zoho BugTracker / Zoho Projects / Zoho Sprints import: these are the column names the Zoho bug importer maps
# from. A file saved this way imports straight into a Zoho project's Bugs (Import Bugs -> map by header).
ZOHO_SEVERITY = {"Critical": "Show Stopper", "High": "Critical", "Medium": "Major", "Low": "Minor"}


def _zoho_description(d: dict) -> str:
    return (f"Role / user access: {d['role'] or '-'}\r\nURL: {d['url'] or '-'}\r\n\r\n"
            f"Steps to reproduce:\r\n{d['steps'] or '-'}\r\n\r\nExpected result:\r\n{d['expected'] or '-'}\r\n\r\n"
            f"Actual result:\r\n{d['actual'] or '-'}\r\n\r\nRequirements: {', '.join(d['req_ids'] or []) or '-'}\r\n"
            f"Test cases: {', '.join(d['case_ids'] or []) or 'found by exploratory or security scanning'}\r\n"
            f"AgentQA defect: {d['id']}")


def export_zoho_csv(project: Project, store: Store, include_drafts: bool = True) -> str:
    """A Zoho-importable CSV of defects (Zoho BugTracker / Projects / Sprints 'Import Bugs')."""
    statuses = ("confirmed", "exported") + (("draft",) if include_drafts else ())
    rows = store.all(f"SELECT * FROM defects WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY seq", statuses)
    path = project.reports_dir / "defects-zoho.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:   # BOM: Zoho reads non-ASCII correctly
        w = csv.writer(f)
        w.writerow(["Title", "Description", "Severity", "Classification", "Reproducible", "Module",
                    "Status", "Flag", "Due Date", "AgentQA ID"])
        for d in rows:
            module = (d.get("url") or "").split("//")[-1].split("/", 1)
            mod = ("/" + module[1].split("?")[0]) if len(module) > 1 and module[1] else "General"
            w.writerow([d["title"][:250], _zoho_description(d), ZOHO_SEVERITY.get(d["severity"], "Major"),
                        "Functionality Issue", "Always", mod, "Open", "Internal", "", d["id"]])
    return str(path)


def push_jira(project: Project, store: Store) -> dict:
    """Create Jira issues for confirmed defects (only when jira.enabled is true)."""
    import os
    jc = project.cfg["jira"]
    if not jc.get("enabled"):
        raise RuntimeError("Jira export is disabled (set jira.enabled: true in project.yaml).")
    token = os.environ.get(jc.get("token_env") or "")
    if not token:
        raise RuntimeError(f"Set the {jc.get('token_env')} environment variable to your Jira API token.")
    done, failed = [], []
    for d in store.all("SELECT * FROM defects WHERE status='confirmed' ORDER BY seq"):
        body = {"fields": {"project": {"key": jc["project_key"]}, "issuetype": {"name": jc.get("issue_type", "Bug")},
                           "summary": d["title"][:240],
                           "description": f"Severity: {d['severity']}\nRole: {d['role']}\nURL: {d['url']}\n\n"
                                          f"Steps:\n{d['steps']}\n\nExpected:\n{d['expected']}\n\nActual:\n{d['actual']}\n\n"
                                          f"Requirements: {', '.join(d['req_ids'] or [])}\nAgentQA: {d['id']}"}}
        try:
            r = httpx.post(f"{jc['base_url'].rstrip('/')}/rest/api/2/issue", json=body,
                           auth=(jc["email"], token), timeout=30)
            r.raise_for_status()
            key = r.json().get("key")
            store.update("defects", "id", d["id"], {"status": "exported", "external_key": key})
            done.append(key)
        except Exception as exc:  # noqa: BLE001
            warn(f"{d['id']}: Jira export failed: {exc}")
            failed.append(d["id"])
    log(f"  exported {len(done)} defect(s) to Jira")
    return {"exported": done, "failed": failed}
