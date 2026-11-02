"""Project configuration (project.yaml) loading, defaults and validation."""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "project": "Untitled project",
    "base_url": "http://127.0.0.1:8000",
    "roles": {},
    "login": {
        "start": "/",             # where a tester starts looking for the login (the home page)
        "url": "/login",          # where the portal sends visitors who are not logged in
        "username_selector": None,  # optional fixed selectors (v0.4 and older); normally found on screen
        "password_selector": None,
        "submit_selector": None,
        "success_url_not_contains": None,
        "session_minutes": None,  # reuse a saved login while the portal accepts it; a number of minutes caps it
    },
    "assist": {
        "enabled": True,          # agents pause and ask you (OTP, CAPTCHA, where to click) when stuck
        "timeout_s": 600,         # how long an agent waits for an answer
        "terminal": True,         # also accept answers typed in the command window
    },
    "explore": {
        "start_paths": ["/"],
        "max_pages_per_role": 60,
        "max_instances_per_pattern": 3,
        "exclude_patterns": ["logout", "signout", "sign-out", "log-out", "delete", "remove", "destroy"],
        "include_anonymous": True,
        "timeout_ms": 15000,
    },
    "oracles": {
        "success_patterns": ["success", "submitted", "saved", "created", "thank you", "registered"],
        "error_patterns": ["error", "invalid", "required", "must", "not allowed", "please enter",
                           "cannot", "should be", "is not valid"],
        "denied_patterns": ["access denied", "not authorized", "not authorised", "unauthorized",
                            "forbidden", "permission denied", "you do not have permission"],
        "server_error_patterns": ["traceback (most recent call last)", "internal server error",
                                  "stack trace", "sqlstate", "nullpointerexception",
                                  "exception in thread"],
    },
    "policy": {
        # What to do when the SRS and the live app disagree:
        #   ask      - put a question in the clarification queue (no test until answered)
        #   srs_wins - treat the SRS as correct and test against it
        #   app_wins - treat the app as correct
        "divergence": "ask",
        # Pages visible only to some roles: ask whether other roles must be blocked.
        #   ask | deny | ignore
        "inferred_access": "ask",
        "console_errors_fail": False,
        "max_load_ms": None,
    },
    "execution": {
        "workers": "auto",       # parallel browsers: auto = 2 to 4 depending on CPU threads
        "headless": True,
        "trace_on_failure": True,
        "default_timeout_ms": 15000,
        "evidence": "all",       # all: a screenshot and step log for every test; failures: only for failed tests
        "video": False,          # record a video of every browser session (large)
    },
    "llm": {
        "enabled": False,
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen3:4b",
        "timeout_s": 240,
        "num_ctx": 8192,
        "max_chunks": 40,
        "polish_defects": False,
        "provider": "ollama",     # ollama (local, nothing leaves the computer) or gemini (Google; key on the Test data page)
        "gemini_model": "auto",   # auto picks the newest stable Gemini Flash model your key can use
        "api_key_secret": "GOOGLE_API_KEY",
        "redact": True,           # mask mobile numbers, emails and 12-digit numbers before sending to Gemini
        "send_screenshots": False,
    },
    "jira": {
        "enabled": False,
        "base_url": "",
        "project_key": "",
        "email": "",
        "token_env": "AGENTQA_JIRA_TOKEN",
        "issue_type": "Bug",
    },
    "api": {
        "enabled": True,          # test the JSON APIs the screens call (found in network traffic)
        "openapi": None,          # optional: path or URL of an OpenAPI file, e.g. /openapi.json
        "prefix": "/api/",        # only OpenAPI paths under this prefix are tested
        "max_ms": 2000,           # slowest acceptable API answer
        # Back ends on another address than the portal (an api. sub-domain, another port). Hosts on the same
        # domain as a portal are recognised by themselves; list others here, e.g. ["https://api.example.gov.in"]
        "hosts": [],
    },
    "visual": {
        "enabled": True,          # compare each screen with its approved snapshot
        "threshold": 0.002,       # share of pixels that may differ before it counts as a change
        "mask": [],               # CSS selectors to blank out (clocks, captchas, rotating banners)
        "full_page": True,
    },
    "accessibility": {
        "engine": "axe",          # axe (WCAG 2.2 AA rules) or basic
        "tags": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
        "fail_on": ["critical", "serious"],
    },
    "security": {
        "enabled": True,          # session, logout, CSRF and header checks (test environments only)
        "logout_url": "/logout",
    },
    "performance": {
        "enabled": True,          # short load check against the SRS response-time limit
        "users": 5,               # simultaneous users per check (keep low on a laptop)
        "seconds": 8,
        "pages": 3,               # busiest screens to check
        "max_error_rate": 0.01,
    },
    "functional": {
        "enabled": True,          # the Functional Test Analyst drafts manual-tester style cases (login, menus, forms)
        "login_tests": True,      # wrong mobile numbers, wrong OTPs, Resend OTP, wrong passwords, logout
        "unregistered_mobile": None,  # a number known to have no account (live portals: unset skips that case)
        "llm_cases": True,        # with a model on: extra cases for requirements nothing else covers
        "otp_expiry_s": None,     # how long an OTP lasts (else read from the SRS, e.g. 'valid for 5 minutes')
        "session_idle_s": None,   # idle time before a session ends (else read from the SRS)
        "max_wait_s": 90,         # longest real wait a test may make; longer waits need a clock hook or are Not Run
        "clock_hook": None,       # test-environment hook that moves the portal's clock: {url: ..., headers: {...}}
    },
    "visual_qa": {
        "enabled": True,          # intent and verify steps (from the Test Case Generation agent) use the Visual QA agent
        "ask_person": True,       # when there is no model, or it is stuck or unsure, ask on the live screen
        "ask_timeout_s": 180,     # how long to wait for that person before the step is Blocked
        "max_actions": 8,         # actions per intent step before it counts as stuck
    },
    "exploratory": {
        "enabled": True,          # part of the pipeline, after the Executor
        "max_steps_per_role": 20, # clicks and form submissions per role
        "probe_limit": 15,        # other roles' screens to try by typing their address
        "seed": 7,                # same seed, same walk: findings can be reproduced
        "submit_forms": True,     # fill data-entry forms with harmless markers (test environments only)
        "security_checks": True,  # passive: response headers, cookie flags, version disclosure
        # never submit a form whose button or action matches one of these (business actions)
        "never_submit": [r"\bdelete\b", r"\bremove\b", r"\bcancel\b", r"\bwithdraw", r"\bapprov", r"\breject",
                         r"\bverif", r"\bpay(ment)?\b", r"\btransfer\b", r"\bdeactivate", r"\blog ?out\b",
                         r"\bsign ?out\b", r"\bunsubscribe\b", r"\bclose account\b", r"\bforward\b", r"\bsanction"],
    },
    "live": {
        "screenshots": True,      # Live View screenshots; off makes runs about a third faster
        "quality": 50,            # JPEG quality of Live View screenshots
        "keep_sessions": 15,      # how many past runs to keep for replay
        "slowmo_ms": 400,         # pause between actions when showing real browser windows
    },
    "zap": {
        "enabled": "auto",        # auto: scan when ZAP is installed; true: must scan; false: never
        "path": None,             # folder or zap.bat/zap.sh; found automatically in the usual places
        "api_url": None,          # use a ZAP already running, e.g. http://127.0.0.1:8090 (key in api_key_env)
        "spider_minutes": 2,
        "max_pages_per_role": 40,
        "active": False,          # attack probes (SQL injection, XSS): test environments only
        "active_minutes": 5,
        "min_risk": "Medium",     # ZAP alerts at this risk or above become defect drafts
        "exclude": [],            # extra URL patterns never to scan
    },
    "trackers": {
        "jira": {"enabled": False, "base_url": "", "project_key": "", "email": "", "token_env": "AGENTQA_JIRA_TOKEN",
                 "issue_type": "Bug", "labels": ["agentqa"], "attach_evidence": True},
        "azure_devops": {"enabled": False, "org_url": "", "project": "", "token_env": "AGENTQA_ADO_TOKEN",
                         "work_item_type": "Bug", "attach_evidence": True},
        "sync": {"auto": False, "close_on_verify": True, "reopen_on_failure": True},
    },
    "inbox": {
        "enabled": False,         # start the mock inbox even when no login uses an OTP (for email tests)
        "host": "127.0.0.1",      # 0.0.0.0 lets a portal on another machine reach it
        "http_port": 8025,        # SMS webhook: POST /sms {"to", "text"}
        "smtp_port": 2525,        # SMTP sink for emails
        "url": None,              # an inbox already running elsewhere, e.g. http://qa-box:8025
    },
    "data": {
        "around": ["explore", "run", "exploratory"],
        "setup": [],              # HTTP or SQL steps before a run (see README: Test data)
        "cleanup": [],
    },
    "workflows": [],
}


PEER = "__peer"

_TWO_LEVEL = {"co", "gov", "nic", "ac", "org", "net", "edu", "res", "mil", "com"}   # x.co.in, x.gov.in, x.co.uk


def _domain(host: str) -> str:
    """The registrable domain of a host name: citizen.example.gov.in -> example.gov.in; 127.0.0.1 -> 127.0.0.1."""
    parts = host.lower().split(".")
    if len(parts) <= 2 or all(p.isdigit() for p in parts):
        return host.lower()
    if parts[-2] in _TWO_LEVEL and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def workers(cfg: dict) -> int:
    """Parallel browsers for a run. 'auto': one per three CPU threads, at least 2 and at most 4
    (each browser needs about 300 MB; 4 suits a 6-core, 16 GB laptop)."""
    w = (cfg.get("execution") or {}).get("workers", "auto")
    if str(w).strip().lower() in ("auto", "", "none"):
        return max(2, min(4, (os.cpu_count() or 2) // 3))
    return max(1, int(w))


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Project:
    """A project workspace: project.yaml plus the .agentqa state folder."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.config_path = self.root / "project.yaml"
        if not self.config_path.exists():
            raise FileNotFoundError(f"No project.yaml in {self.root}. Run 'agentqa init' first.")
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        self.cfg = _merge(DEFAULTS, raw)
        self.cfg["base_url"] = str(self.cfg["base_url"]).rstrip("/")
        self.state = self.root / ".agentqa"
        self.state.mkdir(exist_ok=True)
        (self.state / "auth").mkdir(exist_ok=True)
        (self.state / "logs").mkdir(exist_ok=True)
        self.srs_dir = self.root / "srs"
        self.srs_dir.mkdir(exist_ok=True)
        self.tests_dir = self.root / "tests"
        self.runs_dir = self.root / "runs"
        self.reports_dir = self.root / "reports"
        for d in (self.runs_dir, self.reports_dir):
            d.mkdir(exist_ok=True)
        self.db_path = self.state / "agentqa.db"

    # ---- convenience accessors -------------------------------------------
    @property
    def name(self) -> str:
        return self.cfg["project"]

    @property
    def base_url(self) -> str:
        return self.cfg["base_url"]

    # ---- applications: one project may test several portals (a citizen portal, a department portal...) ----
    # A path on the first (primary) application is written as usual ('/apply'); a path on another one is
    # written with its id ('@department/clerk/queue'), so screens, cases and defects stay unambiguous.
    def applications(self) -> dict[str, dict]:
        if getattr(self, "_apps", None) is None:
            raw = self.cfg.get("applications") or {}
            if isinstance(raw, list):
                raw = {str(a.get("id") or a.get("name") or f"app{i}"): a for i, a in enumerate(raw)}
            if not raw:
                raw = {"main": {"name": self.name, "base_url": self.base_url}}
            apps = {}
            for i, (aid, a) in enumerate(raw.items()):
                a = dict(a or {})
                apps[str(aid)] = {"id": str(aid), "name": a.get("name") or str(aid), "description": a.get("description") or "",
                                  "base_url": str(a.get("base_url") or self.base_url).rstrip("/"),
                                  "module": a.get("module") or "", "environment": a.get("environment") or "",
                                  "auth": a.get("auth") or "", "priority": int(a.get("priority") or i + 1),
                                  "scope": {"include": list((a.get("scope") or {}).get("include") or []),
                                            "exclude": list((a.get("scope") or {}).get("exclude") or [])},
                                  "srs": list(a.get("srs") or []), "login": dict(a.get("login") or {}),
                                  "start_paths": list(a.get("start_paths") or [])}
            self._apps = apps
        return self._apps

    @property
    def primary_app(self) -> str:
        return next(iter(self.applications()))

    def split_path(self, path: str) -> tuple[str, str]:
        """'@department/clerk/queue' -> ('department', '/clerk/queue'); '/apply' -> (primary, '/apply')."""
        if path.startswith("@"):
            app, _, rest = path[1:].partition("/")
            if app in self.applications():
                return app, "/" + rest
        return self.primary_app, path if path.startswith("/") else "/" + path

    def qualify(self, path: str, app: str | None) -> str:
        if not app or app == self.primary_app or path.startswith("@") or path.startswith("http"):
            return path
        return f"@{app}{path if path.startswith('/') else '/' + path}"

    def url(self, path: str, app: str | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        a, p = self.split_path(self.qualify(path, app))
        return self.applications()[a]["base_url"] + p

    def rel(self, url: str) -> str:
        """A full URL as a (qualified) path; URLs outside every configured application come back unchanged."""
        for aid, a in sorted(self.applications().items(), key=lambda x: -len(x[1]["base_url"])):
            base = a["base_url"]
            if url == base or url.startswith(base + "/") or url.startswith(base + "?"):
                rest = url[len(base):] or "/"
                return self.qualify(rest if rest.startswith("/") else "/" + rest, aid)
        return url

    def is_internal(self, url: str) -> bool:
        return self.rel(url) != url

    def is_api_url(self, url: str) -> bool:
        """A back-end address that belongs to the portal although it is not one of its pages: a host listed in
        api.hosts, the same host on another port, or a sub-domain of the portal's domain (api.example.gov.in)."""
        if not url.startswith(("http://", "https://")):
            return False
        if self.is_internal(url):
            return True
        from urllib.parse import urlparse
        u = urlparse(url)
        hosts = [str(h).rstrip("/") for h in ((self.cfg.get("api") or {}).get("hosts") or [])]
        if any(url == h or url.startswith(h + "/") or url.startswith(h + "?") for h in hosts):
            return True
        for a in self.applications().values():
            b = urlparse(a["base_url"])
            if u.hostname and u.hostname == b.hostname:
                return True                      # same machine, another port
            if u.hostname and b.hostname and _domain(u.hostname) == _domain(b.hostname) and "." in _domain(b.hostname):
                return True                      # api.example.gov.in next to citizen.example.gov.in
        return False

    def app_of(self, role: str) -> str:
        if role == "anonymous":
            return self.primary_app
        a = self.account(role).get("app")
        return a if a in self.applications() else self.primary_app

    def login_cfg(self, app: str | None = None) -> dict:
        lg = dict(self.cfg.get("login") or {})
        lg.update((self.applications().get(app or self.primary_app) or {}).get("login") or {})
        return lg

    def login_start(self, role: str) -> str:
        app = self.app_of(role)
        return self.qualify(self.login_cfg(app).get("start") or "/", app)

    def is_login_path(self, path: str) -> bool:
        app, p = self.split_path(path.split("?")[0] if not path.startswith("http") else self.rel(path).split("?")[0])
        return p.startswith(self.login_cfg(app).get("url") or "/login")

    def is_production(self, path_or_app: str) -> bool:
        """Live production: AgentQA only reads there (no form submissions, workflows, attacks or load)."""
        app = path_or_app if path_or_app in self.applications() else self.split_path(path_or_app or "/")[0]
        return str(self.applications()[app].get("environment") or "").strip().lower() in ("production", "prod", "live")

    def in_scope(self, path: str) -> bool:
        app, p = self.split_path(path)
        sc = self.applications()[app]["scope"]
        if sc["include"] and not any(re.search(x, p) for x in sc["include"]):
            return False
        return not any(re.search(x, p) for x in sc["exclude"])

    @property
    def vault(self):
        """The encrypted test data vault (accounts, recorded logins, data sets, secrets)."""
        if getattr(self, "_vault", None) is None:
            from agentqa.vault import Vault
            self._vault = Vault(self.state)
        return self._vault

    def _vault_accounts(self) -> dict[str, dict]:
        try:
            return self.vault.accounts() if self.vault.path.exists() else {}
        except Exception:  # noqa: BLE001 - a vault from another computer must not stop the run
            return {}

    def roles(self) -> dict[str, dict]:
        """Roles from project.yaml plus roles defined only on the Test data page."""
        out = {r: (v or {}) for r, v in (self.cfg.get("roles") or {}).items()}
        for r in self._vault_accounts():
            if not r.endswith(PEER):
                out.setdefault(r, {})
        return out

    def role_password(self, role: str) -> str:
        spec = self.account(role)
        env_name = spec.get("password_env")
        if env_name and os.environ.get(env_name):
            return os.environ[env_name]
        if spec.get("password"):
            return str(spec["password"])
        raise KeyError(f"No password for role '{role}'. Enter it on the Test data page "
                       f"(or set {env_name or 'password_env'} in project.yaml).")

    def account(self, role: str) -> dict:
        """Login details for a role, or for its second user ('<role>__peer'): project.yaml, then the vault."""
        if role.endswith(PEER):
            spec = dict((self.roles().get(role[: -len(PEER)], {}) or {}).get("peer") or {})
        else:
            spec = dict(self.roles().get(role, {}) or {})
        for k, v in (self._vault_accounts().get(role) or {}).items():
            if v not in (None, "", []):
                spec[k] = v
        return spec

    def peers(self) -> list[str]:
        """Second accounts of a role, used to check users cannot read each other's records."""
        out = [f"{r}{PEER}" for r, spec in self.roles().items() if (spec or {}).get("peer")]
        return out + [r for r in self._vault_accounts() if r.endswith(PEER) and r not in out
                      and r[: -len(PEER)] in self.roles()]

    def auth_file(self, role: str) -> Path:
        return self.state / "auth" / f"{role}.json"

    def role_aliases(self) -> dict[str, list[str]]:
        """role key -> list of lowercase names the SRS may use for it."""
        out: dict[str, list[str]] = {}
        for key in self.roles():
            spec = self.account(key)
            names = {key.lower(), key.replace("_", " ").lower()}
            aliases = spec.get("aliases", []) or []
            for alias in (aliases.split(",") if isinstance(aliases, str) else aliases):
                if str(alias).strip():
                    names.add(str(alias).strip().lower())
            out[key] = sorted(names, key=len, reverse=True)
        return out


PROJECT_TEMPLATE = """# AgentQA Studio project configuration (v0.8 format)
project: {name}
base_url: {url}

# The portal(s) under test. Say whether each one is a test or production environment: on Production, AgentQA only
# reads (no form submissions, workflows, attacks or load). Add more portals on the Test data page.
applications:
  main:
    name: {name}
    base_url: {url}
    environment: Test / QA        # Development | Test / QA | UAT | Staging | Production
    login: {{start: /, url: /login}}   # where a tester starts, and where visitors not logged in are sent

# One entry per kind of user. Passwords, mobile numbers and OTP settings are entered on the Test data page (stored
# encrypted, never here). login_option is the button a tester clicks to choose this kind of login; method is
# password | mobile_otp | email_otp | password_otp | mfa | sso (left out, AgentQA infers it from the details).
roles:
  user:
    login_option: Login
    method: password
    aliases: [User]

explore:
  start_paths: ["/"]
  max_pages_per_role: 60
  exclude_patterns: [logout, signout, delete, remove]

api:
  enabled: true
  prefix: /api/
  max_ms: 2000
  hosts: []                 # back ends on another address, e.g. ["https://api.example.gov.in"]

policy:
  divergence: ask        # ask | srs_wins | app_wins
  inferred_access: ask   # ask | deny | ignore

execution:
  workers: auto          # parallel browsers: auto picks 2-4 from the CPU (4 on a Ryzen 5 with 16 GB)

exploratory:
  enabled: true          # curious-user walk after the scripted run
  max_steps_per_role: 20
  submit_forms: true     # set false on shared environments
"""


def init_project(root: str | Path, name: str, url: str) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cfg = root / "project.yaml"
    if not cfg.exists():
        cfg.write_text(PROJECT_TEMPLATE.format(name=name, url=url.rstrip("/")), encoding="utf-8")
    (root / "srs").mkdir(exist_ok=True)
    return cfg
