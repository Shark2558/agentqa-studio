"""Two-way sync with Jira and Azure DevOps.

Out:  each defect a QA lead confirms becomes a Jira issue or an Azure DevOps Bug, with steps,
      expected and actual results, requirement IDs and up to three screenshots.
In:   when the developer marks it fixed, AgentQA re-tests it on the next run.
      Passes  -> AgentQA comments "verified fixed" and closes the issue (if allowed).
      Fails   -> AgentQA comments with the new evidence and reopens the issue.
      Closed as Won't Fix / Duplicate / Rejected -> the AgentQA defect is rejected and stays rejected.

project.yaml:

  trackers:
    jira:
      enabled: true
      base_url: https://yourorg.atlassian.net      # Jira Cloud, or your Jira Server/Data Center URL
      project_key: UR
      email: qa.lead@example.com                   # Cloud: email + API token; Server: leave empty, PAT as token
      token_env: AGENTQA_JIRA_TOKEN
      issue_type: Bug
    azure_devops:
      enabled: false
      org_url: https://dev.azure.com/yourorg
      project: Example Portal
      token_env: AGENTQA_ADO_TOKEN                  # personal access token with Work Items (Read & write)
      work_item_type: Bug
    sync:
      auto: false            # sync after every Triage (pipeline and CI)
      close_on_verify: true  # close the issue when the re-test passes
      reopen_on_failure: true
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import httpx

from agentqa import live
from agentqa.store import Store, now
from agentqa.util import log, warn

REJECTED = re.compile(r"won'?t (fix|do)|duplicate|cannot reproduce|can'?t reproduce|rejected|as designed|by design|"
                      r"not a (bug|defect)|obsolete|invalid|declined|out of scope", re.I)
SEV_ADO = {"Critical": "1 - Critical", "High": "2 - High", "Medium": "3 - Medium", "Low": "4 - Low"}
PRI_JIRA = {"Critical": "Highest", "High": "High", "Medium": "Medium", "Low": "Low"}


def _client(**kw) -> httpx.Client:
    # fresh connections (no keep-alive) and connect retries: trackers behind proxies often drop idle sockets
    return httpx.Client(timeout=30, transport=httpx.HTTPTransport(retries=2),
                        limits=httpx.Limits(max_keepalive_connections=0), **kw)


def _token(spec: dict) -> str:
    tok = os.environ.get(spec.get("token_env") or "") or spec.get("token")
    if not tok:
        raise RuntimeError(f"Set the {spec.get('token_env') or 'token_env'} environment variable to your API token")
    return str(tok)


def _description(d: dict, plain: bool = True) -> str:
    parts = [f"Severity: {d['severity']}  |  Priority: {d['priority']}  |  Role: {d['role'] or '-'}",
             f"URL: {d['url'] or '-'}", "", "Steps to reproduce:", d["steps"] or "-", "", "Expected result:",
             d["expected"] or "-", "", "Actual result:", d["actual"] or "-", "",
             f"Requirements: {', '.join(d['req_ids'] or []) or '-'}",
             f"Test cases: {', '.join(d['case_ids'] or []) or 'found by exploratory or security scanning'}",
             f"AgentQA defect: {d['id']}"]
    if plain:
        return "\n".join(parts)
    import html
    return "<br>".join(html.escape(x) for x in parts)


def _shots(project, d: dict, n: int = 3) -> list[Path]:
    out = []
    for e in d["evidence"] or []:
        p = Path(e.get("path") or "")
        if p.suffix.lower() in (".png", ".jpg", ".jpeg") and p.exists():
            out.append(p)
        if len(out) >= n:
            break
    return out


class Jira:
    system = "jira"

    def __init__(self, spec: dict):
        self.spec = spec
        self.base = str(spec["base_url"]).rstrip("/")
        tok = _token(spec)
        self.headers = {"Accept": "application/json"}
        if spec.get("email"):
            self.auth = (spec["email"], tok)
        else:
            self.auth = None
            self.headers["Authorization"] = f"Bearer {tok}"
        self.http = _client(headers=self.headers, auth=self.auth)

    def url_for(self, key: str) -> str:
        return f"{self.base}/browse/{key}"

    def test(self) -> str:
        r = self.http.get(f"{self.base}/rest/api/2/myself")
        r.raise_for_status()
        me = r.json()
        return f"Connected to Jira as {me.get('displayName') or me.get('name') or me.get('emailAddress')}"

    def create(self, project, d: dict) -> str:
        fields = {"project": {"key": self.spec["project_key"]}, "issuetype": {"name": self.spec.get("issue_type", "Bug")},
                  "summary": d["title"][:240], "description": _description(d),
                  "labels": list(self.spec.get("labels") or ["agentqa"])}
        if self.spec.get("set_priority"):
            fields["priority"] = {"name": (self.spec.get("priority_map") or PRI_JIRA).get(d["severity"], "Medium")}
        r = self.http.post(f"{self.base}/rest/api/2/issue", json={"fields": fields})
        if r.status_code >= 400:
            raise RuntimeError(f"Jira refused the issue: HTTP {r.status_code} {r.text[:300]}")
        key = r.json()["key"]
        for shot in _shots(project, d) if self.spec.get("attach_evidence", True) else []:
            with shot.open("rb") as fh:
                self.http.post(f"{self.base}/rest/api/2/issue/{key}/attachments", headers={"X-Atlassian-Token": "no-check"},
                               files={"file": (shot.name, fh, "image/png")})
        return key

    def state(self, key: str) -> dict:
        r = self.http.get(f"{self.base}/rest/api/2/issue/{key}", params={"fields": "status,resolution"})
        r.raise_for_status()
        f = r.json()["fields"]
        status = (f.get("status") or {})
        resolution = (f.get("resolution") or {}).get("name") or ""
        done = ((status.get("statusCategory") or {}).get("key") == "done")
        return {"status": status.get("name") or "", "done": done, "final": done, "resolution": resolution,
                "rejected": done and bool(REJECTED.search(resolution or status.get("name") or ""))}

    def comment(self, key: str, text: str) -> None:
        self.http.post(f"{self.base}/rest/api/2/issue/{key}/comment", json={"body": text}).raise_for_status()

    def _transition(self, key: str, want_done: bool) -> str | None:
        r = self.http.get(f"{self.base}/rest/api/2/issue/{key}/transitions")
        r.raise_for_status()
        best = None
        for t in r.json().get("transitions", []):
            cat = ((t.get("to") or {}).get("statusCategory") or {}).get("key")
            if want_done and cat == "done":
                best = best or t
                if re.search(r"close|done|verif", t.get("name", ""), re.I):
                    best = t
            if not want_done and cat != "done":
                if re.search(r"reopen", t.get("name", ""), re.I) or best is None:
                    best = t
        if not best:
            return None
        self.http.post(f"{self.base}/rest/api/2/issue/{key}/transitions", json={"transition": {"id": best["id"]}}).raise_for_status()
        return best.get("name")

    def close(self, key: str) -> str | None:
        return self._transition(key, True)

    def reopen(self, key: str) -> str | None:
        return self._transition(key, False)


class AzureDevOps:
    system = "azure_devops"

    def __init__(self, spec: dict):
        self.spec = spec
        self.org = str(spec["org_url"]).rstrip("/")
        self.project = str(spec["project"])
        tok = base64.b64encode(f":{_token(spec)}".encode()).decode()
        self.http = _client(headers={"Authorization": f"Basic {tok}", "Accept": "application/json"})
        self.api = f"{self.org}/{self.project}/_apis/wit"

    def url_for(self, key: str) -> str:
        return f"{self.org}/{self.project}/_workitems/edit/{key}"

    def test(self) -> str:
        r = self.http.get(f"{self.org}/_apis/projects/{self.project}", params={"api-version": "7.1"})
        r.raise_for_status()
        return f"Connected to Azure DevOps project {r.json().get('name', self.project)}"

    def _patch(self, wid: str, ops: list[dict]) -> dict:
        r = self.http.patch(f"{self.api}/workitems/{wid}", params={"api-version": "7.1"}, json=ops,
                            headers={"Content-Type": "application/json-patch+json"})
        r.raise_for_status()
        return r.json()

    def create(self, project, d: dict) -> str:
        ops = [{"op": "add", "path": "/fields/System.Title", "value": d["title"][:250]},
               {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.ReproSteps", "value": _description(d, plain=False)},
               {"op": "add", "path": "/fields/Microsoft.VSTS.Common.Severity", "value": SEV_ADO.get(d["severity"], "3 - Medium")},
               {"op": "add", "path": "/fields/System.Tags", "value": "; ".join(self.spec.get("tags") or ["AgentQA"])}]
        if self.spec.get("area_path"):
            ops.append({"op": "add", "path": "/fields/System.AreaPath", "value": self.spec["area_path"]})
        wtype = self.spec.get("work_item_type", "Bug")
        r = self.http.post(f"{self.api}/workitems/${wtype}", params={"api-version": "7.1"}, json=ops,
                           headers={"Content-Type": "application/json-patch+json"})
        if r.status_code >= 400:
            raise RuntimeError(f"Azure DevOps refused the work item: HTTP {r.status_code} {r.text[:300]}")
        wid = str(r.json()["id"])
        for shot in _shots(project, d) if self.spec.get("attach_evidence", True) else []:
            up = self.http.post(f"{self.api}/attachments", params={"fileName": shot.name, "api-version": "7.1"},
                                content=shot.read_bytes(), headers={"Content-Type": "application/octet-stream"})
            if up.status_code < 400:
                self._patch(wid, [{"op": "add", "path": "/relations/-",
                                   "value": {"rel": "AttachedFile", "url": up.json()["url"]}}])
        return wid

    def state(self, key: str) -> dict:
        r = self.http.get(f"{self.api}/workitems/{key}", params={"api-version": "7.1"})
        r.raise_for_status()
        f = r.json()["fields"]
        st, reason = f.get("System.State", ""), f.get("System.Reason", "")
        done = st in ("Resolved", "Closed", "Done", "Removed")
        # Resolved = the developer says it is fixed; Closed = a tester verified it (AgentQA does that step)
        return {"status": st, "done": done, "final": st in ("Closed", "Done", "Removed"), "resolution": reason,
                "rejected": done and (st == "Removed" or bool(REJECTED.search(reason)))}

    def comment(self, key: str, text: str) -> None:
        self._patch(key, [{"op": "add", "path": "/fields/System.History", "value": text.replace("\n", "<br>")}])

    def close(self, key: str) -> str | None:
        self._patch(key, [{"op": "add", "path": "/fields/System.State", "value": self.spec.get("closed_state", "Closed")}])
        return self.spec.get("closed_state", "Closed")

    def reopen(self, key: str) -> str | None:
        self._patch(key, [{"op": "add", "path": "/fields/System.State", "value": self.spec.get("active_state", "Active")}])
        return self.spec.get("active_state", "Active")


def trackers_cfg(cfg: dict) -> dict:
    t = dict(cfg.get("trackers") or {})
    legacy = cfg.get("jira") or {}
    if legacy.get("enabled") and not (t.get("jira") or {}).get("enabled"):
        t["jira"] = legacy                       # v0.3 projects kept Jira settings at the top level
    return t


def connect(cfg: dict, system: str | None = None):
    t = trackers_cfg(cfg)
    for name, cls in (("jira", Jira), ("azure_devops", AzureDevOps)):
        if (system in (None, name)) and (t.get(name) or {}).get("enabled"):
            return cls(t[name])
    return None


def configured(cfg: dict) -> list[str]:
    t = trackers_cfg(cfg)
    return [n for n in ("jira", "azure_devops") if (t.get(n) or {}).get("enabled")]


def _log(store: Store, system: str, d: dict, action: str, detail: str, ok: bool = True) -> None:
    store.insert("sync_log", {"at": now(), "system": system, "defect_id": d["id"], "external_key": d.get("external_key"),
                              "action": action, "detail": detail[:500], "ok": int(ok)})
    live.emit("triage", "sync", f"{system}: {action} {d.get('external_key') or ''} for {d['id']}: {detail[:160]}",
              level="ok" if ok else "bad")


def sync(project, store: Store, push: bool = True, pull: bool = True) -> dict:
    """Push confirmed defects, then pull issue states and report re-test results back."""
    cfg = project.cfg
    opts = (trackers_cfg(cfg).get("sync") or {})
    client = connect(cfg)
    if client is None:
        raise RuntimeError("No issue tracker is enabled (trackers.jira or trackers.azure_devops in project.yaml)")
    sysname = client.system
    run_id = store.get_meta("last_run")
    out = {"system": sysname, "created": 0, "fixed": 0, "verified": 0, "reopened": 0, "rejected": 0, "errors": 0}
    if push:
        for d in store.all("SELECT * FROM defects WHERE status='confirmed' AND (external_key IS NULL OR external_key='') ORDER BY seq"):
            try:
                key = client.create(project, d)
                store.update("defects", "id", d["id"], {"status": "exported", "external_key": key, "external_system": sysname,
                                                        "external_url": client.url_for(key), "external_status": "open",
                                                        "external_sync": {"last": "created", "run_id": run_id, "at": now()}})
                out["created"] += 1
                _log(store, sysname, {**d, "external_key": key}, "created", d["title"])
            except Exception as exc:  # noqa: BLE001
                out["errors"] += 1
                _log(store, sysname, d, "create failed", str(exc), ok=False)
    if pull:
        for d in store.all("SELECT * FROM defects WHERE external_key IS NOT NULL AND external_key != '' "
                           "AND (external_system IS NULL OR external_system=?) ORDER BY seq", [sysname]):
            key, sync_state = d["external_key"], d.get("external_sync") or {}
            try:
                st = client.state(key)
                changes: dict = {"external_status": st["status"]}
                if st["rejected"] and d["status"] != "rejected":
                    changes.update(status="rejected", notes=(d["notes"] or "") + f"\nClosed in {sysname} as '{st['resolution'] or st['status']}'.")
                    out["rejected"] += 1
                    _log(store, sysname, d, "rejected", f"closed as {st['resolution'] or st['status']}")
                elif d["status"] == "resolved" and sync_state.get("last") != "verified":
                    # AgentQA's latest run no longer reproduces it: report the re-test result
                    client.comment(key, f"AgentQA verified this as fixed in run {run_id}: the related test(s) "
                                        f"{', '.join(d['case_ids'] or []) or '(exploratory check)'} pass now.")
                    closed = client.close(key) if opts.get("close_on_verify", True) and not st.get("final", st["done"]) else None
                    changes["external_sync"] = {"last": "verified", "run_id": run_id, "at": now()}
                    if closed:
                        changes["external_status"] = closed
                    out["verified"] += 1
                    _log(store, sysname, d, "verified fixed", f"comment added{'; moved to ' + closed if closed else ''}")
                elif d["status"] == "reopened" and sync_state.get("last") != "reopened":
                    client.comment(key, f"AgentQA run {run_id} still reproduces this defect.\nActual: {(d['actual'] or '')[:800]}")
                    moved = client.reopen(key) if opts.get("reopen_on_failure", True) and st["done"] else None
                    changes.update(status="exported", external_sync={"last": "reopened", "run_id": run_id, "at": now()})
                    if moved:
                        changes["external_status"] = moved
                    out["reopened"] += 1
                    _log(store, sysname, d, "reopened", f"still failing in {run_id}{'; moved to ' + moved if moved else ''}")
                elif st["done"] and d["status"] == "exported":
                    changes.update(status="fixed", external_sync={"last": "fixed", "at": now()},
                                   notes=(d["notes"] or "") + f"\nMarked {st['status']} in {sysname}; re-tested on the next run.")
                    out["fixed"] += 1
                    _log(store, sysname, d, "marked fixed", f"{st['status']} {st['resolution']}".strip())
                elif not st["done"] and d["status"] == "fixed":
                    changes["status"] = "exported"
                store.update("defects", "id", d["id"], changes)
            except Exception as exc:  # noqa: BLE001
                out["errors"] += 1
                _log(store, sysname, d, "sync failed", str(exc), ok=False)
    store.set_meta("tracker_sync", {**out, "at": now()})
    log(f"  [{sysname}] {out['created']} created, {out['fixed']} marked fixed, {out['verified']} verified, "
        f"{out['reopened']} reopened, {out['rejected']} rejected, {out['errors']} error(s)")
    if out["errors"]:
        warn(f"{out['errors']} tracker operation(s) failed; see the Integrations page")
    return out


def test_connection(cfg: dict) -> list[dict]:
    res = []
    for name in configured(cfg):
        try:
            res.append({"system": name, "ok": True, "detail": connect(cfg, name).test()})
        except Exception as exc:  # noqa: BLE001
            res.append({"system": name, "ok": False, "detail": str(exc)[:300]})
    return res
