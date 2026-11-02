"""Mock Jira and Azure DevOps for the demo: the small part of each REST API that AgentQA uses.

Run:  python -m agentqa demo-trackers --port 8900     (then open http://127.0.0.1:8900)

  Jira          base_url http://127.0.0.1:8900/jira          any email and token
  Azure DevOps  org_url  http://127.0.0.1:8900/ado/demo-org  project Demo, any token

The home page lists the issues and has buttons to play the developer: mark an issue fixed,
close it as Won't Fix, or reopen it. Data lives in memory and is lost on restart.
"""
from __future__ import annotations

import html
import time
from itertools import count

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

app = FastAPI(title="Mock trackers")
JIRA: dict[str, dict] = {}
ADO: dict[str, dict] = {}
_jira_n, _ado_n = count(1), count(101)
STATUS = {"To Do": "new", "In Progress": "indeterminate", "Done": "done"}
TRANSITIONS = [("11", "To Do"), ("21", "In Progress"), ("31", "Done"), ("41", "Reopen")]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- Jira REST v2 (subset)

@app.get("/jira/rest/api/2/myself")
def jira_me(request: Request):
    if "authorization" not in request.headers:
        return JSONResponse({"errorMessages": ["Unauthorized"]}, status_code=401)
    return {"name": "qa.bot", "displayName": "AgentQA bot (mock Jira)", "emailAddress": "qa.bot@example.com"}


@app.post("/jira/rest/api/2/issue")
async def jira_create(request: Request):
    body = await request.json()
    f = body.get("fields") or {}
    if not f.get("summary") or not (f.get("project") or {}).get("key"):
        return JSONResponse({"errors": {"summary": "required"}}, status_code=400)
    key = f"{f['project']['key']}-{next(_jira_n)}"
    JIRA[key] = {"key": key, "summary": f["summary"], "description": f.get("description", ""), "status": "To Do",
                 "resolution": None, "labels": f.get("labels") or [], "comments": [], "attachments": [], "created": _now()}
    return {"id": key.split("-")[1], "key": key, "self": f"/jira/rest/api/2/issue/{key}"}


@app.get("/jira/rest/api/2/issue/{key}")
def jira_get(key: str):
    i = JIRA.get(key)
    if not i:
        return JSONResponse({"errorMessages": ["Issue does not exist"]}, status_code=404)
    return {"key": key, "fields": {"summary": i["summary"], "status": {"name": i["status"], "statusCategory": {"key": STATUS[i["status"]]}},
                                   "resolution": {"name": i["resolution"]} if i["resolution"] else None}}


@app.post("/jira/rest/api/2/issue/{key}/comment")
async def jira_comment(key: str, request: Request):
    body = await request.json()
    JIRA[key]["comments"].append({"at": _now(), "body": body.get("body", "")})
    return {"id": str(len(JIRA[key]["comments"]))}


@app.post("/jira/rest/api/2/issue/{key}/attachments")
async def jira_attach(key: str, request: Request):
    form = await request.form()
    f = form.get("file")
    JIRA[key]["attachments"].append(getattr(f, "filename", "file"))
    return [{"filename": getattr(f, "filename", "file")}]


@app.get("/jira/rest/api/2/issue/{key}/transitions")
def jira_transitions(key: str):
    return {"transitions": [{"id": tid, "name": name,
                             "to": {"name": "To Do" if name == "Reopen" else name,
                                    "statusCategory": {"key": STATUS["To Do" if name == "Reopen" else name]}}}
                            for tid, name in TRANSITIONS]}


@app.post("/jira/rest/api/2/issue/{key}/transitions")
async def jira_do_transition(key: str, request: Request):
    tid = ((await request.json()).get("transition") or {}).get("id")
    name = dict(TRANSITIONS).get(tid)
    if not name:
        return JSONResponse({"errorMessages": ["bad transition"]}, status_code=400)
    JIRA[key]["status"] = "To Do" if name == "Reopen" else name
    JIRA[key]["resolution"] = "Done" if name == "Done" else None
    return Response(status_code=204)


# ---------------------------------------------------------------- Azure DevOps (subset)

@app.get("/ado/{org}/_apis/projects/{project}")
def ado_project(org: str, project: str):
    return {"id": "p1", "name": project}


@app.post("/ado/{org}/{project}/_apis/wit/workitems/{wtype}")
async def ado_create(org: str, project: str, wtype: str, request: Request):
    ops = await request.json()
    fields = {op["path"].split("/fields/")[1]: op["value"] for op in ops if op["path"].startswith("/fields/")}
    wid = str(next(_ado_n))
    ADO[wid] = {"id": wid, "type": wtype.lstrip("$"), "fields": {"System.State": "New", "System.Reason": "New", **fields},
                "history": [], "relations": [], "created": _now()}
    return {"id": int(wid), "fields": ADO[wid]["fields"]}


@app.get("/ado/{org}/{project}/_apis/wit/workitems/{wid}")
def ado_get(org: str, project: str, wid: str):
    w = ADO.get(wid)
    return {"id": int(wid), "fields": w["fields"]} if w else JSONResponse({"message": "not found"}, status_code=404)


@app.patch("/ado/{org}/{project}/_apis/wit/workitems/{wid}")
async def ado_patch(org: str, project: str, wid: str, request: Request):
    w = ADO[wid]
    for op in await request.json():
        if op["path"] == "/fields/System.History":
            w["history"].append({"at": _now(), "text": op["value"]})
        elif op["path"].startswith("/fields/"):
            w["fields"][op["path"].split("/fields/")[1]] = op["value"]
        elif op["path"].startswith("/relations"):
            w["relations"].append(op["value"])
    return {"id": int(wid), "fields": w["fields"]}


@app.post("/ado/{org}/{project}/_apis/wit/attachments")
async def ado_attach(org: str, project: str, request: Request, fileName: str = "file"):  # noqa: N803
    await request.body()
    return {"id": fileName, "url": f"/ado/{org}/{project}/_apis/wit/attachments/{fileName}"}


# ---------------------------------------------------------------- developer's view

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Mock Jira and Azure DevOps</title>
<style>body{font:14px system-ui,sans-serif;margin:24px;color:#0f1e3d;background:#f4f7fc}h1{font-size:20px}
table{border-collapse:collapse;width:100%;background:#fff}td,th{border-bottom:1px solid #e2e8f3;padding:8px;text-align:left;vertical-align:top}
th{background:#eff5ff}button{margin:2px;padding:4px 10px;border:1px solid #1d4ed8;background:#fff;color:#1d4ed8;border-radius:6px;cursor:pointer}
.st{font-weight:600}.c{font-size:12px;color:#5d6c88;white-space:pre-wrap}</style></head><body>
<h1>Mock issue trackers (demo)</h1><p>Play the developer: mark an issue fixed and run AgentQA again; it re-tests and reports back here.</p>
<h2>Jira</h2><table><tr><th>Key</th><th>Summary</th><th>Status</th><th>Comments</th><th></th></tr>{jira}</table>
<h2>Azure DevOps</h2><table><tr><th>ID</th><th>Title</th><th>State</th><th>History</th><th></th></tr>{ado}</table></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    def btns(system, key):
        return "".join(f'<form method="post" action="/ui/{system}/{key}/{a}" style="display:inline"><button>{label}</button></form>'
                       for a, label in (("fix", "Mark fixed"), ("wontfix", "Won't fix"), ("reopen", "Reopen")))
    j = "".join(f"<tr><td>{k}</td><td>{html.escape(i['summary'])}</td><td class='st'>{i['status']}"
                f"{' (' + i['resolution'] + ')' if i['resolution'] else ''}</td><td class='c'>"
                + "\n".join(html.escape(c['at'] + ': ' + c['body'][:200]) for c in i["comments"]) + f"</td><td>{btns('jira', k)}</td></tr>"
                for k, i in JIRA.items()) or "<tr><td colspan=5>No issues yet.</td></tr>"
    a = "".join(f"<tr><td>{k}</td><td>{html.escape(w['fields'].get('System.Title', ''))}</td><td class='st'>{w['fields']['System.State']}"
                f" ({w['fields'].get('System.Reason', '')})</td><td class='c'>"
                + "\n".join(html.escape(h['at'] + ': ' + h['text'][:200]) for h in w["history"]) + f"</td><td>{btns('ado', k)}</td></tr>"
                for k, w in ADO.items()) or "<tr><td colspan=5>No work items yet.</td></tr>"
    return PAGE.replace("{jira}", j).replace("{ado}", a)


@app.post("/ui/{system}/{key}/{action}")
def ui_action(system: str, key: str, action: str):
    if system == "jira" and key in JIRA:
        i = JIRA[key]
        i["status"], i["resolution"] = {"fix": ("Done", "Fixed"), "wontfix": ("Done", "Won't Fix"),
                                        "reopen": ("To Do", None)}[action]
    elif system == "ado" and key in ADO:
        f = ADO[key]["fields"]
        f["System.State"], f["System.Reason"] = {"fix": ("Resolved", "Fixed"), "wontfix": ("Resolved", "Won't Fix"),
                                                 "reopen": ("Active", "Reactivated")}[action]
    return RedirectResponse("/", status_code=303)


@app.get("/api/state")
def state():
    return {"jira": JIRA, "ado": ADO}
