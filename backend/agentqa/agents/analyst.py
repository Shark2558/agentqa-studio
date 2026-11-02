"""Functional Test Analyst: drafts functional test cases the way a manual tester writes them.

A tester does not stop at "the page loads". For every module they write positive, negative and
boundary cases with preconditions, steps, test data and an expected result, and then run them:

  Login       each way in (Citizen Login, Department Login...) exactly as AgentQA learnt it:
              valid login per role; mobile number blank, too short, letters, wrong first digit,
              not registered, too long; wrong and blank OTP; Resend OTP; OTP screen shows only the
              last digits; wrong, case-changed and blank passwords; unknown user; password masked;
              logout ends the session and Back does not bring it back.
  Navigation  every menu item, button, drop-down menu and pop-up the Explorer clicked: it opens the
              right page or shows the right choices.
  Forms       all mandatory fields valid; the empty form; each mandatory field left empty; wrong
              formats per kind of field (mobile, email, PIN code, name, date of birth, Aadhaar, PAN,
              numbers, file type); search with no match, special characters and an empty search.
  SRS         with a model switched on (local or Gemini), extra cases for requirements nothing above
              covers, built only from screens, buttons and fields that exist.

Cases are stored with the others (type 'functional') so the plan gate, generator, executor, triage,
reports and the Excel export treat them alike. Values from the Test data page are written as
tokens ({mobile}, {password:wrong}...) and resolved only at run time, so the generated tests never
contain a password or a real mobile number.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from agentqa import live
from agentqa.config import Project
from agentqa.store import Store
from agentqa.util import future_date, guess_semantic, norm, path_pattern, slug, tokens, valid_value, warn

RESEND = re.compile(r"\bre-?send\b|\bresend\b|\b(get|send) (a )?new (otp|code)\b|didn.?t (get|receive)", re.I)
SEARCH_NAME = re.compile(r"^(q|query|search|keyword|keywords|term|s|find)$|search", re.I)
LOGIN_WORDS = re.compile(r"\blog\s?-?in\b|\bsign\s?-?in\b", re.I)
LOGOUT_WORDS = re.compile(r"\blog\s?-?out\b|\bsign\s?-?out\b", re.I)
NO_RESULTS = [r"\bno\b[^.]{0,60}\b(match|matches|matched|found|results?|records?|items?|data|entries)\b",
              r"\b0\s+(results?|records?|items?|matches)\b", r"\bnothing (found|matches)\b", r"\bnot found\b",
              r"\bdid not match\b", r"\bno\s+(results?|records?|data)\b"]
MODULE_ORDER = ["Login", "Logout", "Navigation", "Forms", "Workflows", "Search", "Requirements"]

# wrong values a tester types, per kind of field: (value, what it is)
BAD_VALUES = {
    "mobile": [("987654321", "9 digits"), ("98765abcde", "letters"), ("5876543210", "a first digit of 5")],
    "email": [("qa.tester@", "no domain after @"), ("qa.tester.example.com", "no @ sign")],
    "pincode": [("69500", "5 digits"), ("69A001", "a letter"), ("095001", "a first digit of 0")],
    "name": [("Test123", "digits"), ("Test@#$", "special characters"), ("   ", "only spaces")],
    "aadhaar": [("12341234123", "11 digits"), ("1234abcd1234", "letters")],
    "pan": [("ABCDE12345", "the wrong pattern (10 characters, no letter at the end)")],
    "number": [("-1", "a negative number")],
    "address": [("   ", "only spaces")],
}


def _login_norm(text: str) -> str:
    text = re.sub(r"\blog\s?-?\s?out\b|\bsign\s?-?\s?out\b", "logout", text or "", flags=re.I)
    return re.sub(r"\blog\s?-?\s?in\b|\bsign\s?-?\s?in\b", "login", text, flags=re.I)


class Draft:
    """Collects cases in the order a tester would read them."""

    def __init__(self, project: Project, store: Store, existing: set[str]):
        self.project = project
        self.existing = existing
        self.cases: list[dict] = []
        self.keys: set[str] = set()
        self.reqs = [{"id": r["id"], "text": r["text"] or "", "norm": norm(_login_norm(r["text"] or "")),
                      "tok": tokens(_login_norm(r["text"] or ""))}
                     for r in store.all("SELECT id, text FROM requirements ORDER BY seq")]

    def req_ids(self, *topics: str, phrase: str | None = None) -> list[str]:
        out: list[str] = []
        for t in topics:
            want = tokens(_login_norm(t))
            if not want:
                continue
            hits = [r["id"] for r in self.reqs if want <= r["tok"]]
            if len(want) == 1 and len(hits) > 1:
                continue            # one word ('application') says too little
            out += hits[:3]
        if phrase:
            p = norm(_login_norm(phrase))
            if len(p.split()) >= 2:
                out += [r["id"] for r in self.reqs if f" {p} " in f" {r['norm']} "][:2]
        return list(dict.fromkeys(out))

    def add(self, key: str, title: str, module: str, role: str, path: str, steps: list[dict], *, scenario: str,
            expected: str, test_data: str = "", preconditions: str = "", priority: str = "P2",
            req_ids=(), rule_ids=(), page_role: str | None = None, fresh_login: bool = False, sig: str | None = None,
            defect_title: str | None = None, severity: str = "Medium", oracle: str = "tester") -> None:
        key = "func:" + key
        if key in self.keys:
            return
        self.keys.add(key)
        self.cases.append({
            "key": key, "type": "functional", "group": "functional", "title": title, "role": role, "path": path,
            "priority": priority, "rule_ids": sorted(set(rule_ids)), "req_ids": sorted(set(req_ids)), "oracle_source": oracle,
            "params": {"module": module, "scenario": scenario, "preconditions": preconditions,
                       "steps_text": [s["text"] for s in steps], "test_data": test_data, "expected": expected,
                       "steps": steps, "page_role": page_role or role, "fresh_login": fresh_login,
                       "sig": sig or key, "defect_title": defect_title or f"{title}: failed", "severity": severity}})


def _who(role: str) -> str:
    return "Visitor" if role == "anonymous" else role.replace("__peer", " (second account)").capitalize()


def _field_name(d: dict) -> str:
    return d.get("label") or d.get("name") or d.get("kind") or "the box"


# ---------------------------------------------------------------------------------------------
# Login: built from the steps AgentQA recorded when it logged in like a tester

def _convert(steps: list[dict], role: str) -> list[dict]:
    out = []
    for s in steps:
        if "goto" in s:
            out.append({"action": "goto", "path": s["goto"], "text": f"Open {s['goto']}" + (" (the home page)" if s["goto"] == "/" else "")})
        elif "click" in s:
            out.append({"action": "click", "target": s["click"], "text": f"Click '{s['click']}'"})
        elif "click_el" in s:
            d = s["click_el"]
            out.append({"action": "click_el", "el": d, "at": s.get("at") or {},
                        "text": f"Click the control a tester showed ({d.get('aria') or d.get('title') or d.get('elid') or d.get('tag')})"})
        elif "fill" in s:
            kind = s["value"].strip("{}")
            what = {"mobile": "the registered mobile number", "password": "the password", "username": "the username",
                    "email": "the registered email"}.get(kind, kind if s["value"].startswith("{") else f"'{s['value']}'")
            out.append({"action": "fill", "field": s["fill"], "value": s["value"], "account": role,
                        "secret": kind == "password", "text": f"Type {what} in '{_field_name(s['fill'])}'"})
        elif "otp" in s:
            out.append({"action": "fill_otp", "otp": s["otp"], "account": role, "text": "Type the OTP received by SMS"})
        elif "captcha" in s:
            out.append({"action": "captcha", "field": s["captcha"], "text": "Type the CAPTCHA (AgentQA asks you)"})
        elif "press" in s:
            out.append({"action": "press", "key": s["press"], "text": f"Press {s['press']}"})
        elif "click_at" in s:
            out.append({"action": "click_at", **s["click_at"], "text": "Click where you showed AgentQA"})
    return out


def _parts(steps: list[dict]) -> dict | None:
    """Split recorded login steps: reach the login page, identity boxes, submit, OTP, verify."""
    first = next((i for i, s in enumerate(steps) if "fill" in s or "otp" in s or "captcha" in s), None)
    if first is None:
        return None
    fills, i = [], first
    while i < len(steps) and ("fill" in steps[i] or "captcha" in steps[i]):
        fills.append(steps[i])
        i += 1
    submit = steps[i]["click"] if i < len(steps) and "click" in steps[i] else None
    otp_i = next((j for j in range(i, len(steps)) if "otp" in steps[j]), None)
    verify = None
    if otp_i is not None and otp_i + 1 < len(steps) and "click" in steps[otp_i + 1]:
        verify = steps[otp_i + 1]["click"]
    return {"prefix": steps[:first], "fills": fills, "submit": submit, "otp": steps[otp_i]["otp"] if otp_i is not None else None,
            "verify": verify}


def _secs(n: str, unit: str) -> int:
    u = unit.lower()
    return int(n) * (60 if u.startswith("min") else 3600 if u.startswith("h") else 1)


def _timers(project: Project, d: Draft) -> dict:
    """How long an OTP lasts and how long an idle session lives: from functional settings, else from the SRS."""
    f = project.cfg.get("functional") or {}
    out = {"otp": f.get("otp_expiry_s"), "otp_req": [], "idle": f.get("session_idle_s"), "idle_req": []}
    for r in d.reqs:
        m = re.search(r"\bOTP\b[^.]{0,80}?valid (?:for|up ?to) (\d+)\s*(minutes?|mins?|seconds?|secs?|hours?)", r["text"], re.I)
        if m:
            out["otp"] = out["otp"] or _secs(m.group(1), m.group(2))
            out["otp_req"].append(r["id"])
        m = re.search(r"session[^.]{0,60}?expire[sd]?[^.]{0,30}?after (\d+)\s*(minutes?|mins?|seconds?|secs?|hours?)", r["text"], re.I)
        if m:
            out["idle"] = out["idle"] or _secs(m.group(1), m.group(2))
            out["idle_req"].append(r["id"])
    return out


def _login_cases(d: Draft, project: Project) -> list[str]:
    """Returns the paths of the login pages (their forms are not tested again as ordinary forms)."""
    from agentqa import login_flow as lf
    vault = project.vault
    roles = list(project.roles())
    fcfg = project.cfg.get("functional") or {}
    groups: dict[str, list[str]] = {}
    parts: dict[str, dict] = {}
    for role in roles:
        steps = vault.login_steps(role) if vault.path.exists() else []
        p = _parts(steps) if steps else None
        if not p:
            continue
        parts[role] = p
        sig = json.dumps([s.get("click") or s.get("goto") for s in p["prefix"]]) + "|" + \
            ",".join(sorted(f["fill"].get("kind", "") for f in p["fills"] if "fill" in f))
        groups.setdefault(sig, []).append(role)
    login_paths: set[str] = set()
    for role in roles:
        for stage in ("credentials", "otp"):
            pth = (vault.login_screens(role).get(stage) or {}).get("path") if vault.path.exists() else None
            if pth:
                login_paths.add(pth)

    for members in groups.values():
        # the account used for the negative tests: one that needs no person to type an OTP, if there is one
        acct = next((r for r in members if not lf.needs_person(project, r)), members[0])
        p = parts[acct]
        acc = project.account(acct)
        method = lf._method(acc)
        opt = acc.get("login_option") or ""
        mod_who = opt or f"{_who(acct)} login"
        screens = vault.login_screens(acct)
        cred_path = (screens.get("credentials") or {}).get("path") or ""
        prefix = _convert(p["prefix"], acct)
        reach = " > ".join(s["text"].replace("Click ", "").strip("'") for s in prefix[1:]) or "the login page"
        pre_anon = f"Logged out. {mod_who} is reached from the home page: {reach}."
        submit = p["submit"]
        idents = [f for f in p["fills"] if "fill" in f]
        click_submit = [{"action": "click", "target": submit, "text": f"Click '{submit}'"}] if submit else \
            [{"action": "press", "key": "Enter", "text": "Press Enter"}]

        # ---- positive: each role logs in its own way ----
        for role in members:
            rp = parts[role]
            full = _convert(vault.login_steps(role), role)
            ask = lf.needs_person(project, role)
            steps = full + [{"action": "expect_logged_in", "text": "Check the dashboard opens and Logout is shown"},
                            {"action": "expect_session", "text": "Check a login session was created (session cookie or token)"}]
            title = f"{_who(role)} logs in with valid " + {"mobile_otp": "mobile number and OTP", "email_otp": "email and OTP",
                                                          "password_otp": "username, password and OTP"}.get(lf._method(project.account(role)), "username and password")
            expected = ("After " + (f"'{rp['submit']}'" if rp["submit"] else "submitting") + (" the OTP screen opens; after "
                        f"'{rp['verify']}'" if rp["otp"] else "") + f" the {_who(role)} home screen opens and Logout is shown.")
            if ask:   # one OTP from you covers the login and the logout check
                steps += _logout_steps(project, role, after_login=True)
                title += "; Logout ends the session"
                expected += " Logout returns to the public page; Back and reload do not show the dashboard again."
            role_topic = [role] + [a for a in project.role_aliases().get(role, []) if a != role]
            reqs = []
            for name in role_topic:
                reqs += d.req_ids(f"{name} login " + ("mobile otp" if lf._method(project.account(role)) == "mobile_otp" else "password"))
                if lf._method(project.account(role)) == "password_otp":
                    reqs += d.req_ids(f"{name} login otp")
            if ask:
                reqs += d.req_ids("logout")
            d.add(f"login:{role}:valid", title, "Login", role, cred_path, steps, scenario="Positive", expected=expected,
                  test_data=f"{_who(role)} account from the Test data page",
                  preconditions=f"Logged out. The {_who(role)} account is on the Test data page.",
                  priority="P1", req_ids=reqs, page_role="anonymous", fresh_login=True,
                  sig=f"func:login:{role}", defect_title=f"{_who(role)} cannot log in with valid details", severity="Critical")

        neg_reqs = d.req_ids("error invalid input")
        fail_ok = "An error message is shown and the user is not logged in."

        def neg(key, title, steps, data, expected=fail_ok, reqs=(), prio="P2", sig=None, dtitle=None, sev="Medium"):
            d.add(f"login:{acct}:{key}", title, "Login", acct, cred_path, prefix + steps, scenario="Negative", expected=expected,
                  test_data=data, preconditions=pre_anon, priority=prio, req_ids=list(reqs) + neg_reqs, page_role="anonymous",
                  fresh_login=True, sig=sig, defect_title=dtitle or f"{mod_who}: {title[0].lower() + title[1:]} - not handled",
                  severity=sev)

        if method in ("mobile_otp", "email_otp") and idents:
            f = idents[0]["fill"]
            kind = "mobile" if method == "mobile_otp" else "email"
            label = _field_name(f)
            no_otp = {"action": "expect_no_field", "kind": "otp", "text": "Check the OTP screen does not open",
                      "fail": "moved on to the OTP screen although the value must be refused"}
            err = {"action": "expect_error", "text": "Check an error message is shown"}
            reqs_bad = []
            for name in [acct] + project.role_aliases().get(acct, []):
                reqs_bad += d.req_ids(f"{name} login error {kind}")
            sigf = f"field:{cred_path}:{f.get('name') or kind}"
            if kind == "mobile":
                acc_mobile = re.sub(r"\D", "", str(acc.get("mobile") or ""))[-10:]
                bad = [("", "left empty", "Get OTP with the mobile number left empty shows an error"),
                       ("{mobile:drop_last}", "9 digits (the registered number without its last digit)",
                        "A 9-digit mobile number is refused with an error"),
                       ("{mobile:letters}", "letters in place of the last digits", "Letters in the mobile number are refused")]
                if re.fullmatch(r"[6-9]\d{9}", acc_mobile):
                    bad.append(("{mobile:bad_start}", "10 digits starting with 5 (Indian mobile numbers start with 6-9)",
                                "A mobile number starting with 5 is refused"))
                unreg = fcfg.get("unregistered_mobile") or ("9000000001" if lf.otp_source(project, acct) in ("inbox", "fixed") else None)
                if unreg:
                    bad.append((str(unreg), f"{unreg}, a valid number that has no account",
                                "A valid but unregistered mobile number is refused"))
            else:
                bad = [("", "left empty", "Get OTP with the email left empty shows an error"),
                       ("qa.tester@", "no domain after @", "An email without a domain is refused")]
            for value, data, title in bad:
                st = ([{"action": "fill", "field": f, "value": value, "account": acct, "text": f"Type {data} in '{label}'"}]
                      if value else [{"action": "note", "text": f"Leave '{label}' empty"}])
                neg(f"{kind}:{slug(data, 24)}", title, st + click_submit + [no_otp, err],
                    f"{label}: {data}", "An error message says the number is not valid; no OTP is sent and the OTP screen "
                    "does not open." if kind == "mobile" else fail_ok, reqs=reqs_bad, prio="P1" if value else "P2", sig=sigf,
                    dtitle=f"{mod_who} accepts an invalid {label.lower()} ({data.split(' (')[0]}) and moves on to the OTP step",
                    sev="High")
            # boundary: the box holds at most 10 digits
            ml = next((i.get("maxlength") for i in (screens.get("credentials") or {}).get("inputs", [])
                       if i.get("kind") == kind and (i.get("maxlength") or -1) > 0), None)
            if kind == "mobile" and ml:
                neg("mobile:maxlength", f"The {label} box takes at most {ml} digits",
                    [{"action": "expect_max_length", "field": f, "value": "{mobile:extra}", "account": acct, "max": int(ml),
                      "text": f"Type 11 digits in '{label}'"}],
                    f"{label}: 11 digits", f"Only {ml} digits stay in the box.", prio="P3",
                    dtitle=f"The {label} box on {mod_who} takes more than {ml} digits", sev="Low")
            if p["otp"]:
                ident = [{"action": "fill", "field": f, "value": "{" + kind + "}", "account": acct,
                          "text": f"Type the registered {kind} number in '{label}'" if kind == "mobile" else f"Type the registered email in '{label}'"}] + click_submit
                verify = [{"action": "click", "target": p["verify"], "text": f"Click '{p['verify']}'"}] if p["verify"] else \
                    [{"action": "press", "key": "Enter", "text": "Press Enter"}]
                otp_reqs = []
                for name in [acct] + project.role_aliases().get(acct, []):
                    otp_reqs += d.req_ids(f"{name} login otp")
                neg("otp:wrong", "A wrong OTP is refused", ident + [
                    {"action": "fill_otp", "otp": p["otp"], "account": acct, "value": "wrong", "text": "Type a wrong OTP (000000)"}]
                    + verify + [{"action": "expect_error", "text": "Check an error message is shown"},
                                {"action": "expect_logged_out", "text": "Check the user is not logged in"}],
                    "OTP: 000000 (not the code sent)", "An error says the OTP is invalid; the user stays on the OTP screen and is "
                    "not logged in.", reqs=otp_reqs, prio="P1", sig=f"func:login:{acct}:otp-wrong",
                    dtitle=f"{mod_who} accepts a wrong OTP", sev="Critical")
                neg("otp:blank", "Verify with the OTP left empty shows an error", ident + [
                    {"action": "note", "text": "Leave the OTP boxes empty"}] + verify + [
                    {"action": "expect_error", "text": "Check an error message is shown"},
                    {"action": "expect_logged_out", "text": "Check the user is not logged in"}],
                    "OTP: empty", reqs=otp_reqs, sig=f"func:login:{acct}:otp-blank",
                    dtitle=f"{mod_who} does not complain about an empty OTP")
                if kind == "mobile":
                    neg("otp:masked-number", "The OTP screen shows only the last digits of the mobile number", ident + [
                        {"action": "expect_field", "kind": "otp", "text": "Check the OTP screen opens"},
                        {"action": "expect_text", "value": "{mobile:last4}", "account": acct,
                         "text": "Check the screen names the last 4 digits of the number"},
                        {"action": "expect_no_text", "value": "{mobile}", "account": acct,
                         "text": "Check the full number is not shown"}],
                        "The registered mobile number", "The OTP screen says the OTP was sent to the number ending in its "
                        "last 4 digits, without showing the full number.", reqs=otp_reqs, prio="P3",
                        dtitle=f"{mod_who}: the OTP screen does not say where the OTP went, or shows the full number", sev="Low")
                timers = _timers(project, d)
                if timers["otp"]:
                    mins = f"{timers['otp'] // 60} minutes" if timers["otp"] >= 120 else f"{timers['otp']} seconds"
                    neg("otp:expired", f"An OTP used after it expires ({mins}) is refused", ident + [
                        {"action": "expect_field", "kind": "otp", "text": "Check the OTP screen opens"},
                        {"action": "wait", "seconds": timers["otp"], "why": f"let the OTP expire ({mins})",
                         "text": f"Wait until the OTP has expired ({mins})"},
                        {"action": "fill_otp", "otp": p["otp"], "account": acct, "text": "Type the OTP that was sent"}] + verify + [
                        {"action": "expect_error", "text": "Check an error says the OTP has expired or is invalid"},
                        {"action": "expect_logged_out", "text": "Check the user is not logged in"}],
                        f"The OTP sent, typed after {mins}", "The expired OTP is refused with an error and the user is not "
                        "logged in.", reqs=timers["otp_req"] + otp_reqs, prio="P1", sig=f"func:login:{acct}:otp-expired",
                        dtitle=f"{mod_who} accepts an OTP after it has expired", sev="High")
                resend = next((c for c in (screens.get("otp") or {}).get("clicks", []) if RESEND.search(c)), None)
                if resend:
                    neg("otp:resend", f"'{resend}' sends a new OTP", ident + [
                        {"action": "expect_field", "kind": "otp", "text": "Check the OTP screen opens"},
                        {"action": "click", "target": resend, "text": f"Click '{resend}'"},
                        {"action": "expect_new_message", "account": acct, "kind": "sms",
                         "text": "Check a new OTP SMS arrives (AgentQA asks you on a live portal)"}],
                        "The registered mobile number", "A new OTP is sent to the mobile number and the screen confirms it.",
                        reqs=d.req_ids("resend otp") + d.req_ids("request new otp"), prio="P1",
                        sig=f"func:login:{acct}:resend", dtitle=f"'{resend}' on the {mod_who} OTP screen does nothing "
                        "(no new OTP is sent)", sev="High")

        if method in ("password", "password_otp") and idents:
            fu = next((x["fill"] for x in idents if x["value"] in ("{username}", "{email}")), None)
            fp = next((x["fill"] for x in idents if x["value"] == "{password}"), None)
            if fu and fp:
                lu, lp = _field_name(fu), _field_name(fp)

                def creds(u, p_, ud, pd):
                    out = []
                    out.append({"action": "fill", "field": fu, "value": u, "account": acct, "text": f"Type {ud} in '{lu}'"} if u else
                               {"action": "note", "text": f"Leave '{lu}' empty"})
                    out.append({"action": "fill", "field": fp, "value": p_, "account": acct, "secret": True,
                                "text": f"Type {pd} in '{lp}'"} if p_ else {"action": "note", "text": f"Leave '{lp}' empty"})
                    return out
                refused = [{"action": "expect_error", "text": "Check an error message is shown"},
                           {"action": "expect_logged_out", "text": "Check the user is not logged in"}]
                pw_reqs = []
                for name in [acct] + project.role_aliases().get(acct, []):
                    pw_reqs += d.req_ids(f"{name} login password")
                sigp = f"func:login:{norm(mod_who)}:password"
                for key, title, (u, p_, ud, pd), data, prio in [
                    ("wrong-password", "A wrong password is refused", ("{username}", "{password:wrong}", "the username",
                     "a wrong password"), f"{lu}: valid; {lp}: wrong", "P1"),
                    ("case-password", "The password is case-sensitive", ("{username}", "{password:swapcase}", "the username",
                     "the password with upper and lower case swapped"), f"{lp}: right letters, wrong case", "P2"),
                    ("unknown-user", "An unknown username is refused", ("{username:unknown}", "{password}", "a username that "
                     "does not exist", "a password"), f"{lu}: aq.no.such.user", "P2"),
                    ("blank-both", "Sign in with both boxes empty shows an error", ("", "", "", ""), "both empty", "P2"),
                    ("blank-password", f"Sign in with '{lp}' empty shows an error", ("{username}", "", "the username", ""),
                     f"{lp}: empty", "P2"),
                    ("blank-username", f"Sign in with '{lu}' empty shows an error", ("", "{password}", "", "the password"),
                     f"{lu}: empty", "P2")]:
                    neg(key, title, creds(u, p_, ud, pd) + click_submit + refused, data, reqs=pw_reqs, prio=prio,
                        sig=f"{sigp}:{key}", dtitle=f"{mod_who}: {title[0].lower() + title[1:]} - not enforced",
                        sev="Critical" if key in ("wrong-password", "unknown-user") else "Medium")
                neg("password-masked", f"The {lp} box hides what is typed", [
                    {"action": "expect_masked", "field": fp, "text": f"Check '{lp}' shows dots, not the password"}],
                    "-", "The password box is a masked (password) box.", prio="P3", sig=f"{sigp}:masked",
                    dtitle=f"{mod_who} shows the password in plain text", sev="Medium")
            # an OTP after the password (e.g. officers): wrong OTP
            otp_role = next((r for r in members if parts[r]["otp"] and lf._method(project.account(r)) == "password_otp"), None)
            if otp_role:
                op = parts[otp_role]
                full = _convert(vault.login_steps(otp_role), otp_role)
                cut = next(i for i, s in enumerate(full) if s["action"] == "fill_otp")
                verify = full[cut + 1:cut + 2] or [{"action": "press", "key": "Enter", "text": "Press Enter"}]
                otp_reqs = []
                for name in [otp_role] + project.role_aliases().get(otp_role, []):
                    otp_reqs += d.req_ids(f"{name} login otp")
                d.add(f"login:{otp_role}:otp:wrong", f"{_who(otp_role)}: a wrong OTP after the password is refused", "Login",
                      otp_role, cred_path, full[:cut] + [
                          {"action": "fill_otp", "otp": op["otp"], "account": otp_role, "value": "wrong", "text": "Type a wrong OTP (000000)"}]
                      + verify + [{"action": "expect_error", "text": "Check an error message is shown"},
                                  {"action": "expect_logged_out", "text": "Check the user is not logged in"}],
                      scenario="Negative", expected="An error says the OTP is invalid; the user is not logged in.",
                      test_data="OTP: 000000", preconditions=pre_anon, priority="P1", req_ids=otp_reqs + neg_reqs,
                      page_role="anonymous", fresh_login=True, sig=f"func:login:{otp_role}:otp-wrong",
                      defect_title=f"{_who(otp_role)} login accepts a wrong OTP", severity="Critical")

        # ---- the session ends after the idle time the SRS gives (one role per way of logging in) ----
        timers = _timers(project, d)
        idle_role = next((r for r in members if not lf.needs_person(project, r)), None)
        if timers["idle"] and idle_role:
            mins = f"{timers['idle'] // 60} minutes" if timers["idle"] >= 120 else f"{timers['idle']} seconds"
            d.add(f"session:{idle_role}:idle", f"{_who(idle_role)}: the session ends after {mins} without activity", "Logout",
                  idle_role, "", [{"action": "login_as", "account": idle_role, "text": f"Log in as {_who(idle_role)}"},
                                  {"action": "expect_logged_in", "text": "Check the user is logged in"},
                                  {"action": "wait", "seconds": timers["idle"], "why": f"stay idle for {mins}",
                                   "text": f"Do nothing for {mins}"},
                                  {"action": "reload", "text": "Reload the page"},
                                  {"action": "expect_logged_out", "text": "Check the portal asks to log in again"}],
                  scenario="Session", expected=f"After {mins} without activity the session has ended and the portal asks "
                                               "to log in again.", test_data=f"{_who(idle_role)} account",
                  preconditions="Logged out.", priority="P2", req_ids=timers["idle_req"], page_role="anonymous",
                  fresh_login=True, sig=f"func:session:{idle_role}:idle",
                  defect_title=f"The {_who(idle_role)} session does not end after {mins} without activity", severity="High")

        # ---- logout, for roles whose login needs no person (the others are in the valid-login case) ----
        for role in members:
            if lf.needs_person(project, role):
                continue
            d.add(f"logout:{role}", f"{_who(role)}: Logout ends the session; Back does not bring it back", "Logout", role, "",
                  [{"action": "login_as", "account": role, "text": f"Log in as {_who(role)} (the recorded steps)"}]
                  + _logout_steps(project, role), scenario="Session",
                  expected="Logout returns to the public page and Login is offered again; Back and reload, or opening the "
                           "dashboard address, do not show the dashboard.",
                  test_data=f"{_who(role)} account", preconditions="Logged out.", priority="P1",
                  req_ids=d.req_ids("logout"), page_role="anonymous", fresh_login=True, sig=f"func:logout:{role}",
                  defect_title=f"Logout does not end the {_who(role)} session in the browser", severity="High")
    return sorted(login_paths)


def _logout_steps(project: Project, role: str, after_login: bool = False) -> list[dict]:
    meta = project.state / "auth" / f"{role}.session.json"
    landing = "/dashboard"
    try:
        landing = json.loads(meta.read_text(encoding="utf-8")).get("landing") or landing
    except (OSError, ValueError):
        pass
    if project.split_path(landing)[1] in ("", "/"):
        landing = project.qualify("/dashboard", project.app_of(role))
    home_path = project.qualify("/", project.app_of(role))
    home = [{"action": "expect_path", "path": home_path, "exact": True, "text": "Check the home page is shown"}] if \
        any("home" in (r["text"] or "").lower() and "logout" in _login_norm(r["text"] or "").lower()
            for r in _req_rows(project)) else []
    return [{"action": "click_logout", "text": "Click 'Logout'"},
            {"action": "expect_logged_out", "text": "Check Logout is gone and Login is offered"}] + home + [
            {"action": "back", "text": "Press the browser's Back button"},
            {"action": "reload", "text": "Reload the page"},
            {"action": "expect_logged_out", "text": "Check the dashboard is not shown again"},
            {"action": "goto", "path": landing, "text": f"Type {landing} in the address bar"},
            {"action": "expect_logged_out", "text": "Check the portal asks to log in"}]


_REQ_CACHE: dict[str, list] = {}


def _req_rows(project: Project) -> list[dict]:
    k = str(project.db_path)
    if k not in _REQ_CACHE:
        try:
            _REQ_CACHE[k] = Store(project.db_path).all("SELECT id, text FROM requirements")
        except Exception:  # noqa: BLE001
            _REQ_CACHE[k] = []
    return _REQ_CACHE[k]


# ---------------------------------------------------------------------------------------------
# Navigation: what the Explorer clicked and the menus it saw

def _navigation(d: Draft, project: Project, store: Store) -> None:
    excl = [x.lower() for x in project.cfg["explore"]["exclude_patterns"]]
    rows = store.all("SELECT role, path, title, status FROM screens")
    titles = {(s["role"], s["path"]): s["title"] for s in rows}
    status = {s["path"]: s["status"] or 0 for s in rows}

    def nav_sig(role: str, to: str) -> str:
        # a page that fails to load is one defect, however many tests reach it
        code = status.get(to, 0)
        return f"page:{to}" if code >= 500 else f"link:{to}" if code == 404 else f"func:nav:{role}:{to}"
    covered: set[tuple] = set()
    for j in store.all("SELECT * FROM journeys ORDER BY id"):
        role, target, kind = j["role"], j["target"] or "", j["kind"]
        clicks = [t.strip() for t in target.split(" > ") if t.strip()]
        if not clicks or any(LOGOUT_WORDS.search(c) for c in clicks):
            continue
        pre = "Logged out." if role == "anonymous" else f"Logged in as {_who(role)}."
        base = [{"action": "goto", "path": j["from_path"], "text": f"Open {j['from_path']}"}] + \
            [{"action": "click", "target": c, "text": f"Click '{c}'"} for c in clicks]
        if kind == "navigate" and j["to_path"]:
            to = j["to_path"].split("?")[0] or j["to_path"]
            if (role, clicks[-1].lower(), to) in covered:
                continue
            covered.add((role, clicks[-1].lower(), to))
            title = j["title"] or titles.get((role, to)) or to
            d.add(f"nav:{role}:{' > '.join(clicks)}:{to}", f"{_who(role)}: '{' > '.join(clicks)}' opens {title}", "Navigation",
                  role, j["from_path"], base + [
                      {"action": "expect_path", "path": to, "exact": True, "text": f"Check the address is {to}"},
                      {"action": "expect_page", "value": title, "text": f"Check the {title} page is shown"}],
                  scenario="Navigation", expected=f"The {title} page opens ({to}).", preconditions=pre,
                  priority="P2", req_ids=d.req_ids(title, phrase=title), sig=nav_sig(role, to),
                  defect_title=f"'{' > '.join(clicks)}' does not open {title} for {_who(role)}")
        elif kind in ("reveal", "dialog"):
            items = [t for t in (j["detail"] or {}).get("revealed", []) if t and "\n" not in t and len(t) <= 40
                     and not re.fullmatch(r"(cancel|close|x|×)", t.strip(), re.I)]
            if not items or (role, clicks[-1].lower(), "reveal") in covered:
                continue
            covered.add((role, clicks[-1].lower(), "reveal"))
            what = "a pop-up with" if kind == "dialog" else "a menu with"
            reqs = d.req_ids(f"{clicks[-1]} " + " ".join(items))
            if LOGIN_WORDS.search(clicks[-1]):
                reqs += d.req_ids("login button") + d.req_ids(" ".join(items))
            d.add(f"reveal:{role}:{' > '.join(clicks)}", f"{_who(role)}: '{clicks[-1]}' shows {what} " + ", ".join(items),
                  "Navigation", role, j["from_path"], base + [
                      {"action": "expect_visible", "value": t, "text": f"Check '{t}' is offered"} for t in items],
                  scenario="Navigation", expected=f"{what.capitalize()} {', '.join(items)} appears.", preconditions=pre,
                  priority="P1" if LOGIN_WORDS.search(clicks[-1]) else "P2", req_ids=reqs,
                  sig=f"func:reveal:{role}:{clicks[-1]}", defect_title=f"'{clicks[-1]}' does not offer " + ", ".join(items))
    # menu links: links that appear on two or more of the role's screens
    by_role: dict[str, dict[tuple, int]] = {}
    first_on: dict[tuple, str] = {}
    for s in store.all("SELECT role, path, links, status FROM screens ORDER BY id"):
        if (s["status"] or 0) >= 400:
            continue
        for ln in s["links"] or []:
            href = ln.get("href") or ""
            if not project.is_internal(href):
                continue
            to = project.rel(href).split("?")[0] or "/"
            text = (ln.get("text") or "").strip()
            if not text or len(text) > 40 or any(x in to.lower() for x in excl) or LOGOUT_WORDS.search(text):
                continue
            k = (text, to)
            by_role.setdefault(s["role"], {})[k] = by_role.setdefault(s["role"], {}).get(k, 0) + 1
            first_on.setdefault((s["role"],) + k, s["path"])
    for role, links in by_role.items():
        for (text, to), n in sorted(links.items(), key=lambda x: x[0][1]):
            if n < 2 or (role, text.lower(), to) in covered:
                continue
            covered.add((role, text.lower(), to))
            title = titles.get((role, to)) or text
            start = first_on[(role, text, to)]
            pre = "Logged out." if role == "anonymous" else f"Logged in as {_who(role)}."
            d.add(f"menu:{role}:{text}:{to}", f"{_who(role)}: the '{text}' link opens {title}", "Navigation", role, start, [
                {"action": "goto", "path": start, "text": f"Open {start}"},
                {"action": "click", "target": text, "text": f"Click '{text}' in the menu"},
                {"action": "expect_path", "path": to, "exact": True, "text": f"Check the address is {to}"},
                {"action": "expect_page", "value": title, "text": f"Check the {title} page is shown"}],
                scenario="Navigation", expected=f"The {title} page opens ({to}).", preconditions=pre, priority="P3",
                req_ids=d.req_ids(title, phrase=title), sig=nav_sig(role, to),
                defect_title=f"The '{text}' link does not open {title} for {_who(role)}")


# ---------------------------------------------------------------------------------------------
# Forms and search

def _forms(d: Draft, project: Project, store: Store, login_paths: list[str]) -> None:
    never = [re.compile(p, re.I) for p in (project.cfg.get("exploratory") or {}).get("never_submit") or []]
    rules = store.all("SELECT * FROM rules WHERE status IN ('Confirmed', 'Decided')")
    field_rules: dict[tuple, list] = {}
    for r in rules:
        for m in r.get("matched") or []:
            if m.get("name"):
                field_rules.setdefault((m["path"], m["name"]), []).append(r)
    seen: set[tuple] = set()
    screens = store.all("SELECT * FROM screens ORDER BY (role='anonymous') DESC, id")
    for s in screens:
        if (s["status"] or 0) >= 400 or path_pattern(s["path"]) != s["path"]:
            continue
        final = project.rel(s["final_url"] or "")
        if s["path"] in login_paths or (project.is_login_path(final) and not project.is_login_path(s["path"])):
            continue
        for fm in s["forms"] or []:
            fields = [f for f in fm["fields"] if f.get("name")]
            if not fields or any(f["type"] == "password" for f in fields):
                continue
            submit = (fm.get("submit_text") or "").strip()
            if submit and any(p.search(submit) for p in never):
                continue
            method = (fm.get("method") or "get").lower()
            text_fields = [f for f in fields if f["type"] in ("text", "search", "")]
            is_search = method == "get" and len(fields) <= 2 and text_fields and any(
                SEARCH_NAME.search(f["name"]) or SEARCH_NAME.search(f.get("label") or "") for f in text_fields)
            key = ("search" if is_search else fm.get("action") or s["path"], s["path"] if not is_search else "")
            if key in seen:
                continue
            seen.add(key)
            if is_search:
                _search_cases(d, s, fm, text_fields[0], submit)
            elif method == "post":
                _form_cases(d, project, s, fm, fields, submit, field_rules)


def _search_cases(d: Draft, s: dict, fm: dict, f: dict, submit: str) -> None:
    role, path = s["role"], s["path"]
    label = f.get("label") or f.get("placeholder") or "Search"
    pre = "Logged out." if role == "anonymous" else f"Logged in as {_who(role)}."
    go = [{"action": "goto", "path": path, "text": f"Open {path}"}]
    btn = [{"action": "click", "target": submit, "text": f"Click '{submit}'"}] if submit else \
        [{"action": "press", "key": "Enter", "text": "Press Enter"}]
    d.add(f"search:none:{path}", "Search for a word that matches nothing says so", "Search", role, path,
          go + [{"action": "fill", "field": f["name"], "value": "zqxv-no-such-item", "text": f"Type 'zqxv-no-such-item' in '{label}'"}]
          + btn + [{"action": "expect_no_server_error", "text": "Check the page works"},
                   {"action": "expect_any_text", "values": NO_RESULTS, "regex": True,
                    "text": "Check a 'no results' message is shown"}],
          scenario="Negative", expected="A message such as 'No results found' is shown.", test_data="zqxv-no-such-item",
          preconditions=pre, priority="P3", sig=f"func:search:none:{path}",
          defect_title="Search with no match shows no 'no results' message", severity="Low")
    d.add(f"search:special:{path}", "Search shows special characters as plain text", "Search", role, path,
          go + [{"action": "fill", "field": f["name"], "value": "<b>aq-test</b>", "text": f"Type '<b>aq-test</b>' in '{label}'"}]
          + btn + [{"action": "expect_no_server_error", "text": "Check the page works"},
                   {"action": "expect_text_literal", "value": "<b>aq-test</b>",
                    "text": "Check the words are shown exactly as typed, tags included"}],
          scenario="Negative", expected="The search term is shown as typed (<b>aq-test</b>), not turned into bold text.",
          test_data="<b>aq-test</b>", preconditions=pre, priority="P1",
          sig=f"xss:{path_pattern(urlparse(fm.get('action') or path).path or '/')}:{f['name']}",
          defect_title="Search shows typed HTML as part of the page (special characters are not escaped)", severity="High")
    d.add(f"search:empty:{path}", "An empty search does not cause an error", "Search", role, path,
          go + btn + [{"action": "expect_no_server_error", "text": "Check no error page appears"}],
          scenario="Boundary", expected="No error page; either a message or all items are shown.", test_data="empty",
          preconditions=pre, priority="P3", sig=f"func:search:empty:{path}",
          defect_title="An empty search breaks the page", severity="Medium")


def _form_cases(d: Draft, project: Project, s: dict, fm: dict, fields: list[dict], submit: str,
                field_rules: dict) -> None:
    role, path = s["role"], s["path"]
    page_name = s["title"] or path
    pre = ("Logged out." if role == "anonymous" else f"Logged in as {_who(role)}.") + f" {page_name} ({path}) is open."
    values: dict[str, str] = {}
    labels: dict[str, str] = {}
    required: list[dict] = []
    for f in fields:
        rs = [{"kind": r["kind"], "value": (r["decided_value"] if r["status"] == "Decided" and r["decided_value"] else r["value"]) or {}}
              for r in field_rules.get((path, f["name"]), [])]
        labels[f["name"]] = f.get("label") or f["name"]
        if f.get("required"):
            required.append(f)
        if not (f.get("required") or rs) and f["type"] != "select":
            continue
        v = valid_value(f, rs)
        if v is None or (f["type"] == "checkbox" and not f.get("required")):
            continue
        values[f["name"]] = v
    if not submit:
        return
    go = [{"action": "goto", "path": path, "text": f"Open {page_name} ({path})"}]
    btn = [{"action": "click", "target": submit, "text": f"Click '{submit}'"}]

    def fills(skip: str | None = None, override: tuple | None = None) -> list[dict]:
        out = []
        for name, v in values.items():
            if name == skip:
                out.append({"action": "note", "text": f"Leave '{labels[name]}' empty"})
                continue
            if override and name == override[0]:
                v = override[1]
            shown = "a small sample file" if str(v).startswith("@file:") else f"'{v}'"
            out.append({"action": "fill", "field": name, "value": v, "text": f"Enter {shown} in '{labels[name]}'"})
        return out

    data_all = "; ".join(f"{labels[k]}: {('sample file' if str(v).startswith('@file:') else v)}" for k, v in values.items())
    form_reqs = d.req_ids(page_name, phrase=page_name)
    neg_reqs = d.req_ids("error invalid input")
    if f"form_valid:{path}:{fm['index']}:{role}" not in d.existing:
        d.add(f"form:{path}:{fm['index']}:valid", f"{page_name}: submit with every mandatory field valid", "Forms", role, path,
              go + fills() + btn + [{"action": "expect_success", "text": "Check a success message is shown"}],
              scenario="Positive", expected="The form is accepted and a success message (and reference number, if any) is shown.",
              test_data=data_all, preconditions=pre, priority="P1", req_ids=form_reqs, sig=f"form:{path}",
              defect_title=f"Valid submission on {path} is not accepted", severity="High")
    if required:
        d.add(f"form:{path}:{fm['index']}:empty", f"{page_name}: submitting the empty form shows errors", "Forms", role, path,
              go + [{"action": "note", "text": "Leave every field empty"}] + btn + [
                  {"action": "expect_error", "text": "Check errors are shown for the mandatory fields"}],
              scenario="Negative", expected="The form is not submitted; each mandatory field is marked or explained.",
              test_data="all fields empty", preconditions=pre, priority="P2", req_ids=neg_reqs, sig=f"func:form-empty:{path}",
              defect_title=f"The empty {page_name} form is accepted", severity="High")
    for f in required:
        name = f["name"]
        if name not in values or f"field_reject:{path}:{name}:required" in d.existing:
            continue
        lab = labels[name]
        rule_reqs = [r["req_id"] for r in field_rules.get((path, name), [])]
        d.add(f"form:{path}:{name}:blank", f"{page_name}: '{lab}' is mandatory", "Forms", role, path,
              go + fills(skip=name) + btn + [{"action": "expect_error", "text": f"Check an error asks for '{lab}'"}],
              scenario="Negative", expected=f"The form is not submitted and '{lab}' is marked as required.",
              test_data=f"{lab}: empty; other fields valid", preconditions=pre, priority="P2",
              req_ids=rule_reqs + neg_reqs, sig=f"field:{path}:{name}",
              defect_title=f"{lab} on {path} accepts invalid input", severity="Medium")
    for f in fields:
        name = f["name"]
        if name not in values or any(k.startswith(f"field_reject:{path}:{name}:") for k in d.existing):
            continue
        sem = guess_semantic(f)
        text = (f.get("label") or "") + " " + name
        bad = list(BAD_VALUES.get(sem, []))
        if sem == "date" and re.search(r"birth|dob", text, re.I):
            bad = [(future_date(30), "a date in the future")]
        if f["type"] == "file":
            accept = [x.strip().lstrip(".").lower() for x in (f.get("accept") or "").split(",") if x.strip() and "/" not in x]
            bad = [("@file:sample.exe", "an .exe file")] if accept and "exe" not in accept else []
        if f["type"] in ("select", "checkbox", "radio", "hidden") or f.get("widget") in ("listbox", "richtext"):
            bad = []
        lab = labels[name]
        rule_reqs = [r["req_id"] for r in field_rules.get((path, name), [])]
        for value, what in bad:
            d.add(f"form:{path}:{name}:{slug(what, 20)}", f"{page_name}: '{lab}' with {what} is refused", "Forms", role, path,
                  go + fills(override=(name, value)) + btn + [{"action": "expect_error", "text": f"Check an error explains '{lab}'"}],
                  scenario="Negative", expected=f"The form is not submitted and an error explains what '{lab}' must contain.",
                  test_data=f"{lab}: '{value.replace('@file:', '')}' ({what}); other fields valid", preconditions=pre,
                  priority="P2", req_ids=rule_reqs + neg_reqs, sig=f"field:{path}:{name}",
                  defect_title=f"{lab} on {path} accepts invalid input", severity="Medium")


# ---------------------------------------------------------------------------------------------
# Requirements nothing else covers: drafted with the model, kept only if they use real screens

# ---------------------------------------------------------------------------------------------

def draft(project: Project, store: Store, existing: list[dict]) -> list[dict]:
    """Functional cases for the Designer. `existing` are the cases it already made (to avoid duplicates)."""
    if not (project.cfg.get("functional") or {}).get("enabled", True):
        return []
    d = Draft(project, store, {c["key"] for c in existing})
    live.emit("analyst", "start", "Drafting functional test cases like a manual tester: login, navigation, forms, search")
    login_paths: list[str] = []
    try:
        if (project.cfg.get("functional") or {}).get("login_tests", True):
            login_paths = _login_cases(d, project)
    except Exception as exc:  # noqa: BLE001
        warn(f"[analyst] login cases skipped: {exc}")
    _navigation(d, project, store)
    _forms(d, project, store, login_paths)
    try:
        from agentqa.agents import workflows
        wf_cases, _gaps = workflows.derive(project, store)
        for c in wf_cases:
            if c["key"] not in d.keys:
                d.keys.add(c["key"])
                d.cases.append(c)
    except Exception as exc:  # noqa: BLE001
        warn(f"[workflows] could not derive workflows: {exc}")
    by = {}
    for c in d.cases:
        by[c["params"]["module"]] = by.get(c["params"]["module"], 0) + 1
    live.emit("analyst", "summary", f"{len(d.cases)} functional case(s): " + ", ".join(f"{m} {k}" for m, k in by.items())
              , by_module=by, level="ok")
    for i, c in enumerate(d.cases):
        c["params"]["order"] = (MODULE_ORDER.index(c["params"]["module"]) if c["params"]["module"] in MODULE_ORDER else 9, i)
    return d.cases
