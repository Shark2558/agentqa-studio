"""Reporter agent: one self-contained HTML report plus CSV exports.

reports/report.html   summary, defects, traceability, open questions, results
reports/rtm.csv       requirement -> rule -> test case -> latest result
reports/defects.csv   confirmed defects in a Jira-importable layout
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, select_autoescape

from agentqa.agents import requirements as reqs_agent
from agentqa.agents.triage import export_csv
from agentqa import live
from agentqa.config import Project
from agentqa.store import Store

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ project }} - Test report</title>
<style>
:root{--ink:#0f1e3d;--muted:#5d6c88;--line:#e2e8f3;--bg:#f4f7fc;--card:#fff;--accent:#1d4ed8;
--crit:#a3201b;--high:#c2410c;--med:#a16207;--low:#4b5563;--pass:#166534;--fail:#b91c1c}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 "Segoe UI",system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{background:radial-gradient(120% 160% at 100% 0%,#3b82f6 0%,#1d4ed8 45%,#0b1f4d 100%);color:#fff;padding:24px 32px}
header h1{margin:0;font-size:22px}header p{margin:4px 0 0;color:#dbe7ff}
.ready{display:flex;gap:20px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin:0 0 16px}
.ready .score{font-size:40px;font-weight:750;line-height:1;min-width:96px;text-align:center}
.ready .score small{display:block;font-size:12px;font-weight:600;color:var(--muted);margin-top:4px}
.ready ul{margin:0;padding-left:18px;color:#334366}.verdict{font-weight:700;font-size:15px;margin-bottom:4px}
.v-Ready{color:#15803d}.v-Ready-with-risks{color:#b45309}.v-Not-ready{color:#c2271d}
main{max-width:1200px;margin:0 auto;padding:24px 32px 60px}
h2{font-size:17px;margin:32px 0 10px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile b{display:block;font-size:26px;line-height:1.1}.tile span{color:var(--muted);font-size:12.5px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#eef2f7;font-size:12.5px;color:var(--muted);font-weight:600}
tr:last-child td{border-bottom:0}
td:first-child{white-space:nowrap}
.sev{font-weight:600;padding:2px 8px;border-radius:99px;font-size:12px;white-space:nowrap}
.Critical{background:#fde8e7;color:var(--crit)}.High{background:#fff0e6;color:var(--high)}
.Medium{background:#fdf6dc;color:var(--med)}.Low{background:#eef0f3;color:var(--low)}
.pass{color:var(--pass);font-weight:600}.fail{color:var(--fail);font-weight:600}.muted{color:var(--muted)}
.st{font-size:12px;padding:1px 7px;border-radius:6px;background:#eef2f7;white-space:nowrap}
pre{white-space:pre-wrap;margin:0;font:12.5px/1.45 Consolas,monospace}
.note{background:#fffbea;border:1px solid #f2e3a6;padding:10px 14px;border-radius:8px;margin:10px 0}
details summary{cursor:pointer;color:var(--accent)}
a{color:var(--accent)}
</style></head><body>
<header><h1>{{ project }}: automated test report</h1>
<p>Generated {{ generated }} · Run {{ run.id if run else 'none' }} · {{ base_url }}</p></header>
<main>
{% if not plan_approved %}<div class="note">The test plan has not been approved by a QA lead yet.</div>{% endif %}
<div class="ready"><div class="score v-{{ ready.verdict|replace(' ', '-') }}">{{ ready.score }}<small>out of 100</small></div>
<div><div class="verdict v-{{ ready.verdict|replace(' ', '-') }}">Release readiness: {{ ready.verdict }}</div>
<ul>{% for x in ready.reasons %}<li>{{ x }}</li>{% endfor %}</ul></div></div>
<div class="tiles">
<div class="tile"><b>{{ req_cov }}/{{ req_total }}</b><span>requirements with at least one test</span></div>
<div class="tile"><b>{{ run.passed if run else 0 }}/{{ run.total if run else 0 }}</b><span>tests passed in the latest run</span></div>
<div class="tile"><b>{{ open_defects }}</b><span>open defects ({{ sev_summary }})</span></div>
<div class="tile"><b>{{ test_issues }}</b><span>test issues for the Healer</span></div>
<div class="tile"><b>{{ open_q }}</b><span>questions waiting for a person</span></div>
<div class="tile"><b>{{ screens }}</b><span>screens mapped across {{ roles }} roles</span></div>
</div>

<h2>Defects</h2>
{% if defects %}<table><tr><th>ID</th><th>Severity</th><th>Summary</th><th>Roles</th><th>Requirements</th><th>Status</th></tr>
{% for d in defects %}<tr><td>{{ d.id }}</td><td><span class="sev {{ d.severity }}">{{ d.severity }}</span></td>
<td><b>{{ d.title }}</b><details><summary>Steps, expected and actual</summary>
<p><b>Steps</b></p><pre>{{ d.steps }}</pre><p><b>Expected</b></p><pre>{{ d.expected }}</pre>
<p><b>Actual</b></p><pre>{{ d.actual }}</pre>
{% if d.evidence %}<p><b>Evidence</b></p>{% for e in d.evidence %}<div><a href="{{ e.rel }}">{{ e.kind }} ({{ e.role }})</a></div>{% endfor %}{% endif %}
</details></td><td>{{ d.role }}</td><td>{{ (d.req_ids or [])|join(', ') }}</td><td><span class="st">{{ d.status }}</span></td></tr>{% endfor %}
</table>{% else %}<p class="muted">No defects.</p>{% endif %}

<h2>Coverage by test type</h2>
<table><tr><th>Test type</th><th>Cases</th><th>Passed</th><th>Failed on a defect</th><th>Other</th></tr>
{% for t in by_type %}<tr><td>{{ t.type|replace('_', ' ') }}</td><td>{{ t.n }}</td><td class="pass">{{ t.passed }}</td><td class="{{ 'fail' if t.defect }}">{{ t.defect }}</td><td>{{ t.other }}</td></tr>{% endfor %}</table>

<h2>Requirement traceability</h2>
<table><tr><th>Requirement</th><th>Text</th><th>Rules (status)</th><th>Tests</th><th>Result</th></tr>
{% for r in rtm %}<tr><td>{{ r.id }}</td><td>{{ r.text }}</td><td>{% for x in r.rules %}<div>{{ x.kind }} <span class="st">{{ x.status }}</span></div>{% endfor %}</td>
<td>{{ r.cases|join(', ') if r.cases else '-' }}</td>
<td>{% if not r.cases %}<span class="muted">{{ r.gap }}</span>{% elif r.failed %}<span class="fail">{{ r.failed }} failed</span>{% elif r.passed %}<span class="pass">all passed</span>{% else %}<span class="muted">not run</span>{% endif %}</td></tr>{% endfor %}
</table>

<h2>Open questions for the QA lead</h2>
{% if questions %}<table><tr><th>#</th><th>Priority</th><th>Question</th><th>Proposed</th></tr>
{% for q in questions %}<tr><td>{{ q.id }}</td><td>{{ q.priority }}</td><td>{{ q.question }}</td><td>{{ q.proposed or '' }}</td></tr>{% endfor %}</table>
{% else %}<p class="muted">None open.</p>{% endif %}

<h2>Test results</h2>
<table><tr><th>Case</th><th>Priority</th><th>Title</th><th>Role</th><th>Result</th><th>Detail</th></tr>
{% for c in results %}<tr><td>{{ c.id }}</td><td>{{ c.priority }}</td><td>{{ c.title }}<div class="muted">{{ c.oracle_source }} · {{ (c.req_ids or [])|join(', ') }}</div></td><td>{{ c.role }}</td>
<td>{% if c.outcome == 'passed' %}<span class="pass">passed</span>{% elif c.outcome %}<span class="fail">{{ c.category }}</span>{% else %}<span class="muted">not run</span>{% endif %}</td>
<td><pre>{{ c.message }}</pre></td></tr>{% endfor %}
</table>
<p class="muted">Every expected result traces to the SRS (srs), a reviewer's decision (decided), a workflow written by the QA lead (workflow) or a baseline every portal should meet (baseline). The suite runs without any AI model.</p>
</main></body></html>"""


def report(project: Project, store: Store) -> dict:
    run_id = store.get_meta("last_run")
    run = store.one("SELECT * FROM runs WHERE id=?", [run_id]) if run_id else None
    cases = store.all("SELECT * FROM cases ORDER BY seq")
    results = {r["case_id"]: r for r in store.all("SELECT * FROM results WHERE run_id=?", [run_id])} if run_id else {}
    rules = store.all("SELECT * FROM rules ORDER BY id")
    reqs = store.all("SELECT * FROM requirements ORDER BY seq")
    defects = store.all("SELECT * FROM defects WHERE status NOT IN ('rejected') ORDER BY seq")
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    defects.sort(key=lambda d: (d["status"] == "resolved", order.get(d["severity"], 9), d["seq"]))
    for d in defects:
        for e in d["evidence"] or []:
            try:
                e["rel"] = Path(e["path"]).relative_to(project.root).as_posix()
                e["rel"] = "../" + e["rel"]
            except ValueError:
                e["rel"] = Path(e["path"]).as_uri()
    open_def = [d for d in defects if d["status"] not in ("resolved",)]
    sev_count: dict[str, int] = {}
    for d in open_def:
        sev_count[d["severity"]] = sev_count.get(d["severity"], 0) + 1
    sev_summary = ", ".join(f"{n} {s.lower()}" for s, n in sorted(sev_count.items(), key=lambda kv: order[kv[0]])) or "none"

    rtm = []
    for r in reqs:
        rrules = [x for x in rules if x["req_id"] == r["id"]]
        rcases = [c for c in cases if r["id"] in (c["req_ids"] or [])]
        res = [results.get(c["id"]) for c in rcases]
        failed = sum(1 for x in res if x and x["outcome"] != "passed")
        passed = sum(1 for x in res if x and x["outcome"] == "passed")
        if rcases:
            gap = ""
        elif reqs_agent.is_hand_check(r.get("disposition_note")):     # the Requirements stage's note, as the page shows it
            gap = r["disposition_note"]
        elif r["ambiguity"]:
            gap = "ambiguous: waiting for a person"
        elif any(x["status"] in ("SRS-only", "Missing in app") for x in rrules):
            gap = "not found in the app"
        elif any(x["status"] == "Divergent" for x in rrules):
            gap = "SRS and app disagree: waiting for a person"
        elif any(x["status"] in ("Not automated",) for x in rrules):
            gap = "not automated"
        elif any(x["status"] in ("Workflow",) for x in rrules):
            gap = "needs a workflow definition"
        elif not rrules:
            gap = "no testable rule found"
        else:
            gap = "no test generated"
        rtm.append({"id": r["id"], "text": r["text"], "rules": rrules, "cases": [c["id"] for c in rcases],
                    "failed": failed, "passed": passed, "gap": gap})
    result_rows = []
    for c in cases:
        res = results.get(c["id"])
        result_rows.append({**c, "outcome": res["outcome"] if res else None, "category": res["category"] if res else "",
                            "message": (res["message"] or "").replace("AssertionError: DEFECT: ", "")[:600] if res else ""})
    result_rows.sort(key=lambda x: (x["outcome"] == "passed", x["outcome"] is None, x["seq"]))
    plan = store.one("SELECT * FROM plan WHERE id=1")
    by_type: dict[str, dict] = {}
    for c in result_rows:
        t = by_type.setdefault(c["type"], {"type": c["type"], "n": 0, "passed": 0, "defect": 0, "other": 0})
        t["n"] += 1
        if c["outcome"] == "passed":
            t["passed"] += 1
        elif c["category"] == "defect":
            t["defect"] += 1
        elif c["outcome"]:
            t["other"] += 1
    from agentqa import readiness
    env = Environment(autoescape=select_autoescape(["html"]))
    out = env.from_string(TEMPLATE).render(
        project=project.name, base_url=project.base_url, generated=datetime.now().strftime("%d %b %Y %H:%M"),
        run=run, plan_approved=bool(plan and plan["approved"]),
        req_total=len(reqs), req_cov=sum(1 for r in rtm if r["cases"]),
        open_defects=len(open_def), sev_summary=sev_summary,
        test_issues=sum(1 for r in results.values() if r["category"] in ("test-issue", "environment")),
        open_q=store.scalar("SELECT COUNT(*) FROM questions WHERE status='open'"),
        screens=store.scalar("SELECT COUNT(DISTINCT path) FROM screens"),
        roles=store.scalar("SELECT COUNT(DISTINCT role) FROM screens"),
        defects=defects, rtm=rtm, questions=store.all("SELECT * FROM questions WHERE status='open' ORDER BY priority, id"),
        results=result_rows, by_type=sorted(by_type.values(), key=lambda t: t["type"]),
        ready=readiness.compute(project, store))
    html_path = project.reports_dir / "report.html"
    html_path.write_text(out, encoding="utf-8")
    rtm_path, _rtm_xlsx = reqs_agent.write_rtm(project, store)
    defects_csv = export_csv(project, store, include_drafts=True)
    live.emit("reporter", "write", f"Report ready: {sum(1 for r in rtm if r['cases'])}/{len(reqs)} requirements tested, "
              f"{len(open_def)} open defect(s)", report="reports/report.html", level="ok")
    _ = html  # escaping handled by Jinja autoescape
    return {"report": str(html_path), "rtm": str(rtm_path), "defects_csv": defects_csv}
