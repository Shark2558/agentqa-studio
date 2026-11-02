"""End-to-end check of the human-in-the-loop features, with a person simulated through the dashboard's own API.

    python tools/e2e_assist.py [--keep DIR]

It starts the demo portals in their hard mode: the portal opens in Malayalam, the way in is an unlabelled icon and
the mobile box has no recognisable name, so AgentQA cannot log in by itself. Then, exactly as a person would through
the dashboard (the same HTTP calls the page makes):

  1. English first: the Explorer switches the portal to English by itself and remembers how.
  2. Stuck: AgentQA asks; the person chooses "Let me take over", clicks the icon, Citizen Login, types the mobile
     number and the OTP (read from the SMS inbox) and presses Continue. Every action must refresh the screenshot.
  3. Remembered: the next login (saved session deleted) repeats the person's steps without asking anything.
  4. Pause: with Pause pressed, the next login hands the browser over; Continue lets it finish.
  5. Show how to log in (Test data page): the person logs in once in AgentQA's browser and types a password AgentQA
     did not have; the steps and the password (encrypted) are saved.

Exits 1 if any check fails.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CIT, DEPT, UI, INBOX = 8820, 8830, 8741, 8025
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""), flush=True)
    return bool(ok)


class Person:
    """Does what a tester does in the dashboard's help box, through the same HTTP calls."""

    def __init__(self, base: str):
        self.base = base
        self.c = httpx.Client(timeout=20)
        self.shots: list[bytes] = []

    def pending(self) -> list[dict]:
        return self.c.get(f"{self.base}/assist/pending").json()

    def wait(self, kind: str | None = None, timeout: float = 90, contains: str = "") -> dict | None:
        end = time.time() + timeout
        while time.time() < end:
            for q in self.pending():
                if (kind is None or q["kind"] == kind) and contains.lower() in q["question"].lower() \
                        and (q["shot"] or kind not in ("takeover", "navigate")):
                    return q                # a person sees the box once its screenshot is there
            time.sleep(0.5)
        return None

    def shot(self, q: dict) -> bytes:
        return self.c.get(f"http://127.0.0.1:{UI}{q['shot']}").content if q.get("shot") else b""

    def answer(self, q: dict, ans: dict) -> None:
        r = self.c.post(f"{self.base}/assist/{q['id']}", json=ans)
        r.raise_for_status()

    def _fresh(self, q: dict, before_v: int, timeout: float = 20) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            cur = next((x for x in self.pending() if x["id"] == q["id"]), None)
            if cur is None:
                return q
            if cur["shot_v"] > before_v:
                return cur
            time.sleep(0.4)
        return next((x for x in self.pending() if x["id"] == q["id"]), q)

    def cmd(self, q: dict, body: dict) -> dict:
        v = q["shot_v"]
        self.c.post(f"{self.base}/assist/{q['id']}/cmd", json=body).raise_for_status()
        time.sleep(1.0)
        q2 = self._fresh(q, v)
        self.shots.append(self.shot(q2))
        return q2

    def click(self, q: dict, text: str) -> dict:
        c = next((c for c in q["clickables"] if c["text"].strip().lower() == text.lower()), None)
        if c is None:
            raise AssertionError(f"'{text}' is not on the screen: {[x['text'] for x in q['clickables']]}")
        return self.cmd(q, {"kind": "click", "x": c["x"], "y": c["y"]})

    def field(self, q: dict, label: str) -> dict:
        f = next((f for f in q["fields"] if label.lower() in f["label"].lower()), None)
        if f is None:
            raise AssertionError(f"no box '{label}': {[x['label'] for x in q['fields']]}")
        return self.cmd(q, {"kind": "click", "x": f["x"], "y": f["y"]})

    def type(self, q: dict, text: str, secret: bool = False) -> dict:
        return self.cmd(q, {"kind": "type", "text": text, "secret": secret})


def otp_from_inbox(mobile: str, since: float, timeout: float = 30) -> str:
    import re
    end = time.time() + timeout
    while time.time() < end:
        msgs = httpx.get(f"http://127.0.0.1:{INBOX}/messages", params={"to": mobile, "kind": "sms", "since": since}).json()
        for m in reversed(msgs):
            code = re.search(r"\b(\d{6})\b", m.get("body") or m.get("text") or "")
            if code:
                return code.group(1)
        time.sleep(0.5)
    raise AssertionError("no OTP SMS arrived")


def log_in_as_citizen(person: Person, q: dict, mobile: str) -> None:
    """The person's own steps: icon, Citizen Login, mobile, Get OTP, the OTP, Verify."""
    q = person.click(q, "\U0001F464")
    q = person.click(q, "Citizen Login")
    q = person.field(q, "Registered number")
    q = person.type(q, mobile)
    since = time.time() - 1
    q = person.click(q, "Get OTP")
    code = otp_from_inbox(mobile, since)
    q = person.field(q, "OTP digit 1")
    q = person.type(q, code, secret=True)
    q = person.click(q, "Verify & Login")
    person.answer(q, {"done": True})


def run_agentqa(proj: Path, *args: str, env: dict) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "agentqa", *args, "-p", str(proj)], cwd=str(ROOT), env=env,
                            stdin=subprocess.DEVNULL, stdout=open(proj / f"e2e-{args[0]}.log", "a"), stderr=subprocess.STDOUT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", help="folder for the test project (kept afterwards)")
    a = ap.parse_args()
    work = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="aq-e2e-"))
    if work.exists():
        shutil.rmtree(work)
    projects = work / "projects"
    proj = projects / "demo"
    (proj / "srs").mkdir(parents=True)
    cfg = (ROOT / "demo" / "project.yaml").read_text(encoding="utf-8")
    cfg = cfg.replace("127.0.0.1:8800", f"127.0.0.1:{CIT}").replace("127.0.0.1:8810", f"127.0.0.1:{DEPT}")
    (proj / "project.yaml").write_text(cfg, encoding="utf-8")
    env = {**os.environ, "AGENTQA_HOME": str(work / "home"), "AGENTQA_PROJECTS": str(projects),
           "DEMO_LANG": "ml", "DEMO_HARD_LOGIN": "1", "DEMO_CITIZEN_URL": f"http://127.0.0.1:{CIT}",
           "DEMO_DEPT_URL": f"http://127.0.0.1:{DEPT}", "PYTHONIOENCODING": "utf-8"}
    os.environ.update({k: env[k] for k in ("AGENTQA_HOME", "AGENTQA_PROJECTS")})
    portal = subprocess.Popen([sys.executable, "-m", "demo.portal.serve", "--port", str(CIT), "--dept-port", str(DEPT)],
                              cwd=str(ROOT), env=env, stdout=open(work / "portal.log", "w"), stderr=subprocess.STDOUT)
    from agentqa.config import Project
    from agentqa.inbox import InboxServer
    from agentqa.store import Store
    p = Project(proj)
    inbox = InboxServer(work / "inbox.db", "127.0.0.1", INBOX, None).start()
    import uvicorn
    from agentqa.web.app import app
    ui = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=UI, log_level="warning"))
    threading.Thread(target=ui.run, daemon=True).start()
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{CIT}/").status_code == 200 and ui.started:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    person = Person(f"http://127.0.0.1:{UI}/p/demo")
    mobile = str(p.account("citizen").get("mobile"))
    try:
        # ---- 1 + 2: English first, stuck, the person takes over ------------------------------------------
        print("1-2. First login: AgentQA cannot find the way in by itself")
        job = run_agentqa(proj, "explore", "--roles", "citizen", env=env)
        q = person.wait("navigate", 120)
        check("AgentQA asks when it cannot find the login", q is not None, q and q["question"])
        if q:
            first = person.shot(q)
            check("the question shows a screenshot of the screen as it is now", first[:3] == b"\xff\xd8\xff" and len(first) > 5000)
            lang = json.loads((proj / ".agentqa" / "language.json").read_text(encoding="utf-8")) \
                if (proj / ".agentqa" / "language.json").exists() else {}
            check("the portal opened in Malayalam and AgentQA switched it to English by itself",
                  lang.get("citizen", {}).get("click") == "English", json.dumps(lang, ensure_ascii=False))
            person.answer(q, {"takeover": True})
            t = person.wait("takeover", 30)
            check("choosing 'Let me take over' hands over the browser", t is not None)
            log_in_as_citizen(person, t, mobile)
            distinct = len({hashlib_of(x) for x in person.shots})
            check("the screenshot refreshed after every action", distinct >= len(person.shots) - 1,
                  f"{distinct} different screenshots for {len(person.shots)} actions")
        job.wait(240)
        check("the first exploration finishes after the person's help", job.returncode == 0, f"exit {job.returncode}")
        p = Project(proj)
        steps = p.vault.login_steps("citizen")
        check("the person's steps are saved as the citizen login", any(s.get("click") == "\U0001F464" for s in steps)
              and any(s.get("value") == "{mobile}" for s in steps) and any("otp" in s for s in steps),
              " > ".join(json.dumps(s, ensure_ascii=False) for s in steps))
        s = Store(p.db_path)
        screens = s.scalar("SELECT COUNT(*) FROM screens WHERE role='citizen'")
        check("the Explorer then mapped the citizen's screens", (screens or 0) >= 3, f"{screens} screen(s)")
        menu_en = s.scalar("SELECT COUNT(*) FROM screens WHERE role='citizen' AND title LIKE '%Dashboard%'")
        check("the screens were read in English", (menu_en or 0) >= 1)

        # ---- 3: remembered ---------------------------------------------------------------------------
        print("3. Second login: the saved session is deleted; AgentQA must repeat the steps without asking")
        for f in (proj / ".agentqa" / "auth").glob("citizen*"):
            f.unlink()
        n_before = s.scalar("SELECT COUNT(*) FROM assist")
        job = run_agentqa(proj, "explore", "--roles", "citizen", env=env)
        job.wait(240)
        asked = s.scalar("SELECT COUNT(*) FROM assist") - n_before
        ok_login = s.one("SELECT result, detail FROM auth_log WHERE role='citizen' ORDER BY id DESC LIMIT 1")
        check("the second login needed nobody: no question was asked", job.returncode == 0 and asked == 0,
              f"{asked} question(s), last login: {ok_login and ok_login['detail']}")

        # ---- 4: pause --------------------------------------------------------------------------------
        print("4. Pause: the next login hands the browser over at its first step")
        for f in (proj / ".agentqa" / "auth").glob("citizen*"):
            f.unlink()
        person.c.post(f"http://127.0.0.1:{UI}/p/demo/pause").raise_for_status()
        check("Pause is shown as on", person.c.get(f"http://127.0.0.1:{UI}/p/demo/paused").json()["paused"])
        job = run_agentqa(proj, "explore", "--roles", "citizen", env=env)
        t = person.wait("takeover", 90, contains="Paused")
        check("a paused agent hands its browser over", t is not None, t and t["question"])
        if t:
            person.answer(t, {"done": True})
        job.wait(240)
        check("after Continue the agent finishes on its own", job.returncode == 0, f"exit {job.returncode}")
        check("Continue clears the pause", not person.c.get(f"http://127.0.0.1:{UI}/p/demo/paused").json()["paused"])

        # ---- 5: show how to log in (teach), with a password AgentQA did not have ----------------------
        print("5. Show how to log in: the clerk's password is unknown; the person types it")
        acc = p.vault.account("clerk")
        p.vault.set_account("clerk", {"password": "not-the-password"}, keep_secrets=False)
        p.vault.set_login_steps("clerk", None)
        r = person.c.post(f"http://127.0.0.1:{UI}/p/demo/testdata/account/clerk/teach", follow_redirects=False)
        check("the Test data page starts 'Show how to log in'", r.status_code == 303)
        t = person.wait("takeover", 90, contains="log in as clerk")
        check("the box asks the person to log in as clerk", t is not None)
        if t:
            t = person.click(t, "Staff Login") if any(c["text"] == "Staff Login" for c in t["clickables"]) else t
            if not any("Username" in f["label"] for f in t["fields"]):
                t = person.click(t, "\U0001F464")
                t = person.click(t, "Department Login")
            t = person.field(t, "Username")
            t = person.type(t, "clerk1")
            t = person.field(t, "Password")
            t = person.type(t, "Clerk@123", secret=True)
            t = person.click(t, "Sign in")
            person.answer(t, {"done": True})
        end = time.time() + 120
        while time.time() < end and s.one("SELECT status FROM jobs ORDER BY id DESC LIMIT 1")["status"] == "running":
            time.sleep(1)
        p = Project(proj)
        steps = p.vault.login_steps("clerk")
        check("the clerk's login steps were learned from the person",
              any(x.get("value") == "{password}" for x in steps) and any(x.get("value") == "{username}" for x in steps),
              " > ".join(json.dumps(x) for x in steps))
        check("the password the person typed was kept (encrypted) for the clerk",
              p.vault.account("clerk").get("password") == "Clerk@123")
        raw = (proj / ".agentqa" / "vault.json").read_text(encoding="utf-8") + \
            "".join(f.read_text(encoding="utf-8", errors="replace") for f in (proj / ".agentqa" / "logs").glob("*.log"))
        check("the typed password is in no log and not in clear text in the vault", "Clerk@123" not in raw)
        _ = acc

        # ---- 6: show AgentQA around (navigation help during exploration) -----------------------------
        print("6. Show AgentQA around: a page the crawler is kept from is shown by the person, mapped and remembered")
        # a crawl too short to reach /help/contact by itself (two pages), so only a person can get the Explorer there
        cfg2 = (proj / "project.yaml").read_text(encoding="utf-8")
        import re as _re
        cfg2 = _re.sub(r"max_pages_per_role:\s*\d+", "max_pages_per_role: 2", cfg2) if "max_pages_per_role" in cfg2 \
            else cfg2 + "\nexplore:\n  max_pages_per_role: 2\n"
        (proj / "project.yaml").write_text(cfg2, encoding="utf-8")
        p = Project(proj)
        s = Store(p.db_path)
        s.exec("DELETE FROM screens WHERE path LIKE '%contact%'")
        r = person.c.post(f"http://127.0.0.1:{UI}/p/demo/appmap/teach-nav", data={"role": "citizen"}, follow_redirects=False)
        check("the App map page starts 'Show AgentQA around'", r.status_code == 303, f"HTTP {r.status_code}")
        t = person.wait("takeover", 120, contains="showing me around")
        check("the box hands the person the citizen's browser", t is not None, t and t["question"])
        if t:
            t = person.cmd(t, {"kind": "goto", "path": "/help"})
            link = next((c["text"] for c in t["clickables"] if c["text"].strip().lower().startswith("contact")), None)
            t = person.click(t, link) if link else person.cmd(t, {"kind": "goto", "path": "/help/contact"})
            person.answer(t, {"done": True})
        end = time.time() + 240
        while time.time() < end and s.one("SELECT status FROM jobs ORDER BY id DESC LIMIT 1")["status"] == "running":
            time.sleep(1)
        job_row = s.one("SELECT status FROM jobs ORDER BY id DESC LIMIT 1")
        check("the walk-through finishes and the Explorer re-maps the role", job_row["status"] == "done", job_row["status"])
        p = Project(proj)
        hints = p.vault.nav_hints("citizen")
        check("the way to the shown page is remembered for the citizen", any("contact" in (h.get("to") or "") for h in hints),
              json.dumps(hints, ensure_ascii=False)[:200])
        mapped = s.scalar("SELECT COUNT(*) FROM screens WHERE role='citizen' AND path LIKE '%contact%'")
        check("the shown page is now on the app map", (mapped or 0) >= 1, f"{mapped} screen(s)")
        # the next exploration must reach it alone, with nobody there
        s.exec("DELETE FROM screens WHERE path LIKE '%contact%'")
        n_before = s.scalar("SELECT COUNT(*) FROM assist")
        job = run_agentqa(proj, "explore", "--roles", "citizen", env=env)
        job.wait(240)
        mapped2 = s.scalar("SELECT COUNT(*) FROM screens WHERE role='citizen' AND path LIKE '%contact%'")
        check("the next exploration reaches the shown page by itself, asking nobody",
              job.returncode == 0 and (mapped2 or 0) >= 1 and s.scalar("SELECT COUNT(*) FROM assist") == n_before,
              f"exit {job.returncode}, {mapped2} screen(s)")
    finally:
        ui.should_exit = True
        portal.terminate()
        inbox.stop() if hasattr(inbox, "stop") else None
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed" + (f"; project kept in {work}" if a.keep else ""))
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if failed else 0)


def hashlib_of(b: bytes) -> str:
    import hashlib
    return hashlib.sha1(b).hexdigest()


if __name__ == "__main__":
    main()
