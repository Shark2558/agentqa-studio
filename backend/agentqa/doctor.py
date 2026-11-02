"""Pilot readiness check: is this computer, this test environment and this project.yaml ready for a run?

Each check says ok, warn (works, but something will be missing) or fail (a run will not work),
with the fix in plain words. It can also find the login form's fields by itself and write the
selectors into project.yaml (--apply), which is usually the first stumbling block on a real portal.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from urllib.parse import urlparse

import httpx

from agentqa import live
from agentqa.config import Project, workers as config_workers
from agentqa.store import Store, now

DETECT_JS = r"""() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const sel = e => {
    if (e.id) return '#' + CSS.escape(e.id);
    if (e.name) return `${e.tagName.toLowerCase()}[name="${e.name}"]`;
    const t = e.getAttribute('type'); return t ? `${e.tagName.toLowerCase()}[type=${t}]` : e.tagName.toLowerCase();
  };
  const pw = [...document.querySelectorAll('input[type=password]')].find(vis);
  const out = {password: pw ? sel(pw) : null, username: null, submit: null, captcha: [], otp: null};
  if (pw) {
    const scope = pw.closest('form') || document;
    const inputs = [...scope.querySelectorAll('input')].filter(vis);
    const before = inputs.slice(0, inputs.indexOf(pw)).filter(e => ['text', 'email', 'tel', ''].includes((e.getAttribute('type') || '').toLowerCase()));
    const user = before[before.length - 1] || inputs.find(e => /user|login|email|mobile/i.test(e.name + e.id));
    out.username = user ? sel(user) : null;
    const btn = [...scope.querySelectorAll('button[type=submit], input[type=submit], button:not([type])')].find(vis)
      || [...scope.querySelectorAll('button, [role=button]')].find(b => vis(b) && /log ?in|sign ?in|submit|continue/i.test(b.innerText || b.value || ''));
    out.submit = btn ? (btn.id ? '#' + CSS.escape(btn.id) : (btn.tagName === 'INPUT' ? 'input[type=submit]' : 'button[type=submit]')) : null;
  }
  const otp = [...document.querySelectorAll('input')].find(e => vis(e) && (e.autocomplete === 'one-time-code' || /otp|one.?time|verification.?code|passcode/i.test(e.name + ' ' + e.id + ' ' + (e.placeholder || ''))));
  out.otp = otp ? sel(otp) : null;
  if (document.querySelector('iframe[src*="recaptcha"], .g-recaptcha, iframe[src*="hcaptcha"], .h-captcha, [data-sitekey]')) out.captcha.push('reCAPTCHA or hCaptcha widget');
  if ([...document.querySelectorAll('img')].some(i => /captcha/i.test((i.alt || '') + (i.src || '') + (i.id || '')))) out.captcha.push('CAPTCHA image');
  if ([...document.querySelectorAll('input')].some(i => /captcha/i.test(i.name + i.id + (i.placeholder || '')))) out.captcha.push('CAPTCHA input field');
  return out;
}"""


def _c(name: str, status: str, detail: str, fix: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def run(project: Project, store: Store, apply: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    from agentqa import inbox
    cfg = project.cfg
    checks: list[dict] = []
    add = checks.append
    live.emit("doctor", "start", f"Pilot readiness check for {project.name}")

    # ---- this computer ---------------------------------------------------------------
    v = sys.version_info
    add(_c("Python", "ok" if v >= (3, 11) else "fail", f"Python {v.major}.{v.minor}.{v.micro}",
           "" if v >= (3, 11) else "Install Python 3.11 or newer"))
    free = shutil.disk_usage(project.root).free / 1e9
    add(_c("Free disk space", "ok" if free > 3 else "warn" if free > 1 else "fail", f"{free:.1f} GB free",
           "" if free > 3 else "Free some space: each run keeps screenshots of failures"))
    cpus = os.cpu_count() or 2
    workers = config_workers(cfg)
    add(_c("Parallel browsers", "ok" if workers <= max(2, cpus // 3) else "warn",
           f"{workers} browser(s) on {cpus} CPU thread(s)" + (" (auto)" if str(cfg["execution"].get("workers", "auto")) == "auto" else ""),
           "" if workers <= max(2, cpus // 3) else "Set execution.workers to auto, or 2 on a 16 GB laptop"))

    # ---- test environment -----------------------------------------------------------
    base = project.base_url
    host = urlparse(base).hostname or ""
    try:
        t = time.time()
        r = httpx.get(base, timeout=20, follow_redirects=True, verify=cfg.get("verify_tls", True))
        add(_c("Test environment answers", "ok" if r.status_code < 500 else "fail",
               f"{base} -> HTTP {r.status_code} in {int((time.time() - t) * 1000)} ms"))
        missing = [h for h in ("content-security-policy", "x-frame-options", "x-content-type-options") if h not in r.headers]
        if missing:
            add(_c("Security headers (quick look)", "warn", f"missing: {', '.join(missing)}",
                   "Expect a 'Security headers are missing' defect"))
    except Exception as exc:  # noqa: BLE001
        add(_c("Test environment answers", "fail", f"{base}: {exc}", "Check base_url, VPN and proxy settings"))
    test_like = any(k in host for k in ("uat", "test", "stag", "dev", "qa", "sandbox", "demo", "localhost", "127.0.0.1", "preprod"))
    add(_c("Not production", "ok" if test_like else "warn", f"host '{host}'",
           "" if test_like else "AgentQA submits forms and changes data: confirm this is a test environment"))

    # ---- login form, CAPTCHA, roles, OTP ---------------------------------------------
    lg = cfg["login"]
    detected = {}
    otp_roles = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            add(_c("Browser (Chromium)", "ok", f"Chromium {browser.version}"))
            from agentqa import login_flow
            page = browser.new_page()
            page.goto(project.url(lg.get("start") or "/"), wait_until="load", timeout=30000)
            from agentqa import language
            info = language.detect(page)
            if not language.is_english(info):
                ok = language.ensure_english(page, project, agent="doctor")
                add(_c("Language", "pass" if ok else "warn",
                       "The portal opens in another language; AgentQA switched it to English and will do so every time"
                       if ok else "The portal opens in another language and no switch to English was found",
                       "" if ok else "Show AgentQA the language switch when it asks, or set language.switch: false to "
                                     "test in the portal's own language."))
            detected = page.evaluate(DETECT_JS)
            live.shot(page, "doctor", "observe", "Opened the portal's home page", path=lg.get("start") or "/")
            page.close()
            roles = list(project.roles()) + project.peers()
            if not roles:
                add(_c("Roles", "fail", "no test accounts yet", "Add one account per role on the Test data page"))
            captcha_seen = bool(detected.get("captcha"))
            for role in roles:
                acc = project.account(role)
                method = login_flow._method(acc)
                if method in ("password", "password_otp"):
                    try:
                        project.role_password(role)
                    except KeyError as exc:
                        add(_c(f"Login as {role}", "fail", str(exc), "Enter the password on the Test data page"))
                        continue
                elif not (acc.get("mobile") or acc.get("email")):
                    add(_c(f"Login as {role}", "fail", "no mobile number or email for an OTP login",
                           "Enter it on the Test data page"))
                    continue
                if apply:
                    project.vault.set_login_steps(role, None)      # learn the way in again
                ctx = browser.new_context()
                p2 = ctx.new_page()
                try:
                    used = login_flow.login(p2, project, role, agent="doctor")
                    if used:
                        otp_roles.append(role)
                    steps = project.vault.login_steps(role)
                    who = acc.get("username") or login_flow._masked(acc.get("mobile") or acc.get("email") or "")
                    add(_c(f"Login as {role}", "ok", f"{who} logged in" + (" with an OTP" if used else "")
                           + (": " + " > ".join(login_flow.describe(steps)) if steps else "")))
                    ctx.storage_state(path=str(project.auth_file(role)))
                except Exception as exc:  # noqa: BLE001
                    try:
                        captcha_seen = captcha_seen or login_flow.scan(p2).get("captcha")
                    except Exception:  # noqa: BLE001
                        pass
                    add(_c(f"Login as {role}", "fail", str(exc)[:260],
                           "Check the account on the Test data page; when AgentQA asks where to click, show it once "
                           "and it remembers"))
                ctx.close()
            if captcha_seen:
                add(_c("CAPTCHA", "warn", "the portal shows a CAPTCHA",
                       "AgentQA asks you to type it at every login. Better: switch CAPTCHA off for the test "
                       "environment, or make it accept a fixed test value. AgentQA never tries to break one."))
            else:
                add(_c("CAPTCHA", "ok", "none seen on the way in"))
            browser.close()
    except Exception as exc:  # noqa: BLE001
        add(_c("Browser (Chromium)", "fail", str(exc)[:240], "Run setup.bat again (it installs Chromium)"))
    if otp_roles:
        store.set_meta("otp_roles", otp_roles)

    # ---- project content -------------------------------------------------------------
    srs = [f for f in project.srs_dir.iterdir() if f.is_file()]
    add(_c("SRS", "ok" if srs else "warn", f"{len(srs)} file(s): {', '.join(f.name for f in srs[:4])}" if srs else "none uploaded",
           "" if srs else "Upload the SRS (.docx, .pdf, .md or .txt); without it AgentQA tests only baseline rules"))
    peers = project.peers()
    add(_c("Second account per role", "ok" if peers else "warn",
           f"{len(peers)} role(s) have a second account" if peers else "no peer accounts",
           "" if peers else "Add roles.<role>.peer with a second test user to test record isolation between users"))
    local = host in ("localhost", "127.0.0.1")
    plain = [r for r, spec in project.roles().items() if (spec or {}).get("password")]
    add(_c("Passwords", "warn" if plain and not local else "ok",
           (f"plain passwords in project.yaml for: {', '.join(plain)}" + (" (fine for a local demo)" if local else ""))
           if plain else "kept in environment variables",
           "Use password_env so passwords never sit in files" if plain and not local else ""))
    if inbox.needed(project):
        cl = inbox.ensure(project)
        add(_c("Mock inbox", "ok" if cl and cl.alive() else "fail", f"listening at {inbox.client_url(cfg)}",
               "" if cl and cl.alive() else "Another program uses the inbox port; change inbox.http_port"))

    # ---- optional tools -------------------------------------------------------------
    from agentqa.agents import zapscan
    zs = zapscan.status(cfg)
    add(_c("OWASP ZAP (security scan)", "ok" if zs["available"] else "warn", zs["how"],
           "" if zs["available"] else "Optional: install ZAP to add the security scan stage"))
    from agentqa.integrations import trackers
    for r in trackers.test_connection(cfg):
        add(_c(f"Issue tracker ({r['system']})", "ok" if r["ok"] else "fail", r["detail"],
               "" if r["ok"] else "Check the URL, project and token environment variable"))
    if cfg["llm"].get("enabled"):
        try:
            from agentqa.llm import get_llm
            llm = get_llm(project, "check")
            ok = bool(llm and llm.available())
            if str(cfg["llm"].get("provider", "ollama")).lower() == "gemini":
                add(_c("AI model (Google Gemini)", "ok" if ok else "warn",
                       f"{llm.model if llm else 'no key'}; personal data is masked before sending" if ok
                       else "no Google API key, or the key does not work",
                       "" if ok else "Add the key on the Test data page (Secrets), or set llm.enabled: false"))
            else:
                add(_c("Local model", "ok" if ok else "warn", f"{cfg['llm']['model']} at {cfg['llm']['base_url']}",
                       "" if ok else "Start Ollama and pull the model, or set llm.enabled: false"))
        except Exception as exc:  # noqa: BLE001
            add(_c("Local model", "warn", str(exc)[:200]))

    n = {k: sum(1 for c in checks if c["status"] == k) for k in ("ok", "warn", "fail")}
    verdict = "Ready for a pilot" if not n["fail"] else f"Fix {n['fail']} blocking issue(s) first"
    out = {"checks": checks, "verdict": verdict, **n, "at": now(), "detected": detected}
    store.set_meta("doctor", out)
    live.emit("doctor", "summary", f"{verdict}: {n['ok']} ok, {n['warn']} to improve, {n['fail']} blocking",
              level="ok" if not n["fail"] else "bad")
    return out


def _apply_login(project: Project, sug: dict) -> None:
    import yaml

    from agentqa import yamledit
    lg = dict(project.cfg["login"])
    raw = yaml.safe_load(project.config_path.read_text(encoding="utf-8")) or {}
    block = dict(raw.get("login") or {})
    block.update({k: v for k, v in sug.items() if v})
    block.setdefault("url", lg.get("url", "/login"))
    yamledit.replace_top_block(project.config_path, "login", yaml.safe_dump({"login": block}, sort_keys=False,
                                                                            default_flow_style=False))
