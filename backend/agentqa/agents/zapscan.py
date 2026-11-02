"""Security Scanner agent: OWASP ZAP baseline and logged-in scans.

ZAP is free and open source (Apache 2.0) and runs on this computer; no account or key is needed.
The agent starts ZAP in the background (or uses one already running), then:

  1. Baseline: ZAP's spider walks the portal as an anonymous visitor while ZAP's passive rules
     inspect every response (headers, cookies, error pages, information leaks, unsafe forms).
  2. Logged in: for every role, a browser with that role's saved login opens each screen the
     Explorer mapped, through ZAP, so ZAP also inspects the pages and API answers behind login.
  3. Active scan (off by default; test environments only): ZAP sends attack payloads such as
     SQL injection and cross-site scripting probes, within a time limit, never to logout or delete URLs.

Alerts are grouped by rule and screen. Medium and higher become defect drafts, sharing signatures
with AgentQA's own checks (missing headers, CSRF, XSS, error pages), so Triage merges a ZAP alert
with a failing test or exploratory finding about the same problem instead of filing it twice.

Install ZAP from https://www.zaproxy.org/download/ (it needs Java 17 or newer; the Windows
installer includes it). AgentQA looks in the usual install folders, or set zap.path.
"""
from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright

from agentqa import live
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import log, path_pattern, warn

AGENT = "security"
RISKS = ["Informational", "Low", "Medium", "High"]
SEV = {"High": "High", "Medium": "Medium", "Low": "Low"}
HEADER_RULES = {"10020", "10021", "10038", "10035", "10063", "90004"}
COOKIE_RULES = {"10010", "10011", "10054"}
DISCLOSURE_RULES = {"10036", "10037"}
XSS_RULES = {"40012", "40014", "40016", "40017", "40026"}
SQLI_RULES = {"40018", "40019", "40020", "40021", "40022", "40024", "40027"}


APP_ROOT = Path(__file__).resolve().parent.parent.parent      # the AgentQA folder (bundled tools live in tools/)


def bundled_java() -> Path | None:
    """The Java runtime the Windows installer can bundle next to ZAP (tools/jre)."""
    jre = APP_ROOT / "tools" / "jre"
    return jre if (jre / "bin" / ("java.exe" if os.name == "nt" else "java")).exists() else None


def candidates() -> list[Path]:
    home = Path.home()
    launcher = "zap.bat" if os.name == "nt" else "zap.sh"
    out = [Path(os.environ[v]) / launcher for v in ("ZAP_HOME", "ZAP_PATH") if os.environ.get(v)]
    out += sorted((APP_ROOT / "tools" / "zap").glob(f"*/{launcher}")) + [APP_ROOT / "tools" / "zap" / launcher]
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                out += [Path(base) / "ZAP" / "Zed Attack Proxy" / "zap.bat", Path(base) / "OWASP" / "Zed Attack Proxy" / "zap.bat"]
    else:
        out += [Path("/opt/zaproxy/zap.sh"), Path("/usr/share/zaproxy/zap.sh"), Path("/snap/bin/zaproxy"),
                Path("/Applications/ZAP.app/Contents/Java/zap.sh")]
        out += sorted(home.glob("ZAP*/zap.sh")) + sorted(Path("/opt").glob("ZAP*/zap.sh")) + sorted(Path("/opt").glob("*/ZAP*/zap.sh"))
    if shutil.which("zap.sh"):
        out.append(Path(shutil.which("zap.sh")))
    return out


def find_zap(cfg: dict) -> Path | None:
    z = cfg.get("zap") or {}
    if z.get("path"):
        p = Path(z["path"])
        if p.is_dir():
            p = p / ("zap.bat" if os.name == "nt" else "zap.sh")
        return p if p.exists() else None
    return next((p for p in candidates() if p.exists()), None)


def status(cfg: dict) -> dict:
    z = cfg.get("zap") or {}
    if z.get("api_url"):
        return {"available": True, "how": f"ZAP already running at {z['api_url']}"}
    p = find_zap(cfg)
    java = shutil.which("java") or bundled_java()
    if p:
        return {"available": True, "how": f"ZAP found at {p}", "path": str(p), "java": bool(java) or os.name == "nt"}
    return {"available": False, "how": "ZAP not found. Install it from https://www.zaproxy.org/download/ or set zap.path"}


class Zap:
    def __init__(self, url: str, key: str, proc: subprocess.Popen | None = None):
        self.url, self.key, self.proc = url.rstrip("/"), key, proc
        self.http = httpx.Client(timeout=60, trust_env=False)

    def call(self, path: str, **params):
        r = self.http.get(f"{self.url}/JSON/{path}/", params={**params, "apikey": self.key})
        if r.status_code >= 400:
            raise RuntimeError(f"ZAP {path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    def alive(self) -> bool:
        try:
            return "version" in self.call("core/view/version")
        except Exception:  # noqa: BLE001
            return False

    def stop(self) -> None:
        if self.proc:
            try:
                self.call("core/action/shutdown")
            except Exception:  # noqa: BLE001
                pass
            try:
                self.proc.wait(timeout=30)
            except Exception:  # noqa: BLE001
                self.proc.kill()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(project: Project) -> Zap:
    z = project.cfg.get("zap") or {}
    if z.get("api_url"):
        key = os.environ.get(z.get("api_key_env") or "") or z.get("api_key") or ""
        zap = Zap(z["api_url"], key)
        if not zap.alive():
            raise RuntimeError(f"No ZAP answers at {z['api_url']}")
        return zap
    launcher = find_zap(project.cfg)
    if not launcher:
        raise RuntimeError("OWASP ZAP is not installed. Get it from https://www.zaproxy.org/download/ "
                           "(Windows installer includes Java), or set zap.path in project.yaml.")
    port = int(z.get("port") or 0) or _free_port()
    key = secrets.token_hex(16)
    home = project.state / "zap-home"
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    cmd = [str(launcher), "-daemon", "-silent", "-host", "127.0.0.1", "-port", str(port), "-dir", str(home),
           "-config", f"api.key={key}", "-config", "api.addrs.addr.name=127.0.0.1",
           "-config", "connection.timeoutInSecs=30", "-config", "database.recoverylog=false"]
    if os.name == "nt":
        cmd = ["cmd", "/c"] + cmd
    logf = open(project.state / "logs" / "zap.log", "w", encoding="utf-8")  # noqa: SIM115
    env = {k: v for k, v in os.environ.items() if k not in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
    jre = bundled_java()
    if jre and not shutil.which("java"):
        env["JAVA_HOME"] = str(jre)
        env["PATH"] = str(jre / "bin") + os.pathsep + env.get("PATH", "")
    proc = subprocess.Popen(cmd, cwd=str(launcher.parent), stdout=logf, stderr=subprocess.STDOUT, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    zap = Zap(f"http://127.0.0.1:{port}", key, proc)
    end = time.time() + float(z.get("startup_timeout_s", 180))
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError(f"ZAP exited during start-up; see {project.state / 'logs' / 'zap.log'}")
        if zap.alive():
            return zap
        time.sleep(1.5)
    zap.stop()
    raise RuntimeError("ZAP did not start in time; see .agentqa/logs/zap.log")


def _wait(zap: Zap, view: str, scan_id: str, label: str, limit_s: float) -> None:
    end = time.time() + limit_s
    last = -1
    while time.time() < end:
        pct = int(zap.call(view, scanId=scan_id).get("status", 100))
        if pct != last and pct % 20 == 0:
            live.emit(AGENT, "progress", f"{label}: {pct}%", percent=pct)
            last = pct
        if pct >= 100:
            return
        time.sleep(2)
    live.emit(AGENT, "progress", f"{label}: time limit reached", level="warn")


def _sig(a: dict, base) -> tuple[str, str]:
    """`base` is the Project (several portals: paths come back as '@app/path') or a base URL."""
    pid, url = str(a.get("pluginId")), a.get("url") or ""
    rel = base.rel(url).split("?")[0] if hasattr(base, "rel") and base.is_internal(url) else (urlparse(url).path or "/")
    path = path_pattern(rel or "/")
    param = a.get("param") or ""
    if pid in HEADER_RULES:
        return "security:headers", "Security headers are missing"
    if pid in COOKIE_RULES:
        return f"security:cookie:{param or 'session'}", f"Cookie '{param}' lacks a security flag"
    if pid in DISCLOSURE_RULES:
        return "security:disclosure", "The server reveals its software version"
    if pid in XSS_RULES:
        return f"xss:{path}:{param}", f"Cross-site scripting through '{param}' on {path}"
    if pid in SQLI_RULES:
        return f"sqli:{path}:{param}", f"Possible SQL injection through '{param}' on {path}"
    if pid == "90022":
        return f"page:{path}", f"{path} shows an application error"
    if pid == "10202":
        return "security:csrf", "Forms that change data have no anti-forgery (CSRF) token"
    return f"zap:{pid}", f"{a.get('alert') or a.get('name')} (OWASP ZAP)"


def scan(project: Project, store: Store) -> dict:
    z = project.cfg.get("zap") or {}
    if z.get("enabled", "auto") is False:
        log("[security] skipped (zap.enabled is false)")
        return {"skipped": "disabled"}
    st = status(project.cfg)
    if not st["available"]:
        if z.get("enabled") is True:
            raise RuntimeError(st["how"])
        live.emit(AGENT, "start", f"Security scan skipped: {st['how']}", level="warn")
        log(f"[security] skipped: {st['how']}")
        store.set_meta("zap", {"skipped": st["how"], "at": now()})
        return {"skipped": st["how"]}
    run_id = datetime.now().strftime("Z-%Y%m%d-%H%M%S")
    base = project.base_url
    live.emit(AGENT, "start", f"Starting OWASP ZAP ({st['how']})", run_id=run_id)
    t0 = time.time()
    zap = start(project)
    version = zap.call("core/view/version").get("version")
    live.emit(AGENT, "observe", f"ZAP {version} is ready after {time.time() - t0:.0f} s; scanning {base}", level="ok")
    try:
        excl = list(z.get("exclude") or []) + [p for p in project.cfg["explore"].get("exclude_patterns", [])]
        for pat in excl:
            rx = f".*{pat}.*"
            for view in ("spider/action/excludeFromScan", "ascan/action/excludeFromScan"):
                try:
                    zap.call(view, regex=rx)
                except Exception:  # noqa: BLE001
                    pass
        bases = [a["base_url"] for a in project.applications().values()]
        zap.call("spider/action/setOptionMaxDuration", Integer=str(int(z.get("spider_minutes", 2))))
        for b in bases:          # 1. baseline: spider every portal as an anonymous visitor
            zap.call("core/action/accessUrl", url=b + "/", followRedirects="true")
            sid = zap.call("spider/action/scan", url=b + "/", recurse="true", subtreeOnly="true").get("scan")
            live.emit(AGENT, "navigate", f"ZAP spider: following every link on {b} as an anonymous visitor", path="/")
            _wait(zap, "spider/view/status", sid, "Spider", 60 * float(z.get("spider_minutes", 2)) / max(1, len(bases)) + 30)
        # 2. logged in: each role's browser goes through ZAP
        proxy = urlparse(zap.url)
        visited = 0
        roles = [r for r in (z.get("roles") or list(project.roles())) if project.auth_file(r).exists()]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, proxy={"server": f"http://{proxy.hostname}:{proxy.port}"},
                                         args=["--proxy-bypass-list=<-loopback>"])
            for role in roles + ["anonymous"]:
                ctx = browser.new_context(ignore_https_errors=True,
                                          storage_state=str(project.auth_file(role)) if role != "anonymous" else None)
                page = ctx.new_page()
                paths = [s["path"] for s in store.all("SELECT path, status FROM screens WHERE role=? ORDER BY id", [role])
                         if (s["status"] or 0) < 400][: int(z.get("max_pages_per_role", 40))]
                live.emit(AGENT, "role", f"Browsing {len(paths)} screen(s) as {role} through ZAP", role=role)
                for path in paths:
                    if any(p in path.lower() for p in excl):
                        continue
                    try:
                        page.goto(project.url(path), wait_until="load", timeout=20000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:  # noqa: BLE001
                            pass
                        visited += 1
                        live.shot(page, AGENT, "navigate", f"ZAP inspects {path} as {role}", role=role, path=path)
                    except Exception as exc:  # noqa: BLE001
                        warn(f"[security] {role} {path}: {exc}")
                ctx.close()
            browser.close()
        # passive scan queue
        end = time.time() + 180
        while time.time() < end and int(zap.call("pscan/view/recordsToScan").get("recordsToScan", 0)) > 0:
            time.sleep(1.5)
        # 3. optional active scan
        if z.get("active"):
            live.emit(AGENT, "action", f"Active scan for up to {z.get('active_minutes', 5)} minute(s): attack probes "
                      "against the test environment", level="warn")
            zap.call("ascan/action/setOptionMaxScanDurationInMins", Integer=str(int(z.get("active_minutes", 5))))
            for b in [a["base_url"] for aid_, a in project.applications().items() if not project.is_production(aid_)]:
                aid = zap.call("ascan/action/scan", url=b + "/", recurse="true").get("scan")
                _wait(zap, "ascan/view/status", aid, "Active scan", 60 * float(z.get("active_minutes", 5)) + 60)
        alerts = [a for b in bases for a in zap.call("alert/view/alerts", baseurl=b, start="0", count="5000").get("alerts", [])]
    finally:
        zap.stop()

    # ---- store alerts and turn them into findings ---------------------------------------
    store.exec("DELETE FROM zap_alerts")
    store.exec("DELETE FROM findings WHERE run_id LIKE 'Z-%'")
    min_risk = RISKS.index(str(z.get("min_risk", "Medium")).capitalize())
    groups: dict[str, dict] = {}
    seen_rows = set()
    for a in alerts:
        risk = a.get("risk") or "Informational"
        sig, title = _sig(a, project)
        key = (a.get("pluginId"), a.get("url"), a.get("param"))
        if key in seen_rows:
            continue
        seen_rows.add(key)
        store.insert("zap_alerts", {"run_id": run_id, "plugin_id": str(a.get("pluginId")), "alert": a.get("alert") or a.get("name"),
                                    "risk": risk, "confidence": a.get("confidence"), "url": a.get("url"),
                                    "method": a.get("method"), "param": a.get("param"), "evidence": (a.get("evidence") or "")[:400],
                                    "description": (a.get("description") or "")[:1500], "solution": (a.get("solution") or "")[:1500],
                                    "reference": (a.get("reference") or "")[:800], "cwe": str(a.get("cweid") or ""),
                                    "role": None, "sig": sig, "created_at": now()})
        if risk not in RISKS or RISKS.index(risk) < max(min_risk, 1):
            continue
        g = groups.setdefault(sig, {"title": title, "risk": risk, "urls": [], "alerts": set(), "solution": a.get("solution") or ""})
        if RISKS.index(risk) > RISKS.index(g["risk"]):
            g["risk"] = risk
        g["alerts"].add(a.get("alert") or a.get("name"))
        if a.get("url") not in g["urls"]:
            g["urls"].append(a.get("url"))
    for sig, g in groups.items():
        urls = g["urls"][:8]
        detail = (f"OWASP ZAP: {', '.join(sorted(g['alerts']))} on {len(g['urls'])} URL(s), e.g. "
                  + ", ".join(u.replace(base, "") or "/" for u in urls[:4]))
        store.insert("findings", {"run_id": run_id, "sig": sig, "severity": SEV.get(g["risk"], "Low"), "title": g["title"],
                                  "roles": [], "path": urlparse(urls[0]).path if urls else "/", "url": urls[0] if urls else base,
                                  "steps": "\n".join([f"Open {u}" for u in urls[:3]] + ["Inspect the response (OWASP ZAP alert: "
                                                                                          + ", ".join(sorted(g['alerts'])) + ")."]),
                                  "expected": (g["solution"] or "The response follows OWASP secure defaults.")[:600],
                                  "detail": detail, "evidence": [], "rule_id": None, "req_id": None, "created_at": now()})
    by_risk: dict[str, int] = {}
    for a in store.all("SELECT risk FROM zap_alerts WHERE run_id=?", [run_id]):
        by_risk[a["risk"]] = by_risk.get(a["risk"], 0) + 1
    summary = {"run_id": run_id, "version": version, "alerts": sum(by_risk.values()), "by_risk": by_risk,
               "findings": len(groups), "screens": visited, "active": bool(z.get("active")),
               "seconds": int(time.time() - t0), "at": now()}
    store.set_meta("zap_run", run_id)
    store.set_meta("zap", summary)
    live.emit(AGENT, "summary", f"ZAP raised {summary['alerts']} alert(s) ("
              + ", ".join(f"{n} {r.lower()}" for r, n in sorted(by_risk.items(), key=lambda kv: -RISKS.index(kv[0])))
              + f"); {len(groups)} at {RISKS[max(min_risk, 1)]} or above become defect drafts", **summary)
    return summary


if __name__ == "__main__":  # pragma: no cover
    print(status({}), file=sys.stderr)
