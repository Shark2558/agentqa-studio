"""Demo Certificate Services Portal - a small multi-role web app with seeded bugs.

Run:  python -m uvicorn demo.portal.app:app --port 8800
Users: citizen1/Citizen@123, citizen2/Citizen@123, clerk1/Clerk@123, officer1/Officer@123, admin1/Admin@123

Seeded defects (what AgentQA should find against the demo SRS):
  B1  Approval Queue (/officer/queue) has no role check - any user, even anonymous, can open it.
  B2  Applicant Name allows 100 characters in the form and on the server; SRS says 50.
  B3  Mobile Number: server only checks length 10, so letters and a leading 0-5 are accepted.
  B4  Admin Reports page (/admin/reports) crashes with HTTP 500.
  B5  Help page links to /help/faq, which does not exist (404).
  B6  Home page image has no alt text; the search box has no label.
  B7  Certificate Type offers Income, Residence, Nativity; SRS says Income, Caste, Residence.
  B8  Search results show the query as raw HTML (reflected cross-site scripting). Not in the
      SRS: only the Exploratory Tester can find it.
  B9  My Applications runs a script with a JavaScript error (the Exploratory Tester sees it).
  B10 No security headers (Content-Security-Policy, X-Frame-Options, nosniff, Referrer-Policy).
  B11 GET /api/applications/{id} has no ownership check: any logged-in user can read another
      citizen's application, including mobile number and email (record isolation, IDOR).
  B12 GET /api/users only checks login, not the Administrator role, so every role can list users
      (the User Management screen itself is protected correctly).
  B13 Logging out only deletes the browser cookie. A copy of the old session cookie keeps working
      (sessions are signed cookies, never invalidated on the server).
  B14 POST forms carry no anti-CSRF token (the SameSite=Lax cookie only partly mitigates this).
  B15 Officer login OTP is not invalidated after use: the same code is sent again and accepted
      again until it expires (SRS: an OTP can be used only once).
  B16 Supporting Document: only the size is checked on the server; any file type is accepted
      (SRS: PDF, JPG or PNG only). The browser's accept attribute is the only filter.
  B17 Documents Attached (a custom multi-select) offers Driving Licence instead of Passport.
  B18 Citizen login accepts a 9-digit mobile number and moves on to the OTP step (SRS: a valid
      10-digit number starting with 6-9, otherwise an error).
  B19 Resend OTP on the citizen OTP screen does nothing (SRS: the citizen can request a new OTP).

v0.5 demo login, as on many government portals: the header has a Login button (not a link) that
opens a choice of Citizen Login (mobile number, Get OTP, six OTP boxes, Verify) and Department
Login (username and password; officers then get an OTP). Citizen menus are JavaScript buttons
(Services > Apply for Certificate / My Applications), so only a tester that clicks finds them.

v0.4 demo features: officer logins need a one-time password sent by SMS (posted to
DEMO_SMS_URL, AgentQA's mock inbox by default, and printed here); citizens get a
confirmation email (SMTP to DEMO_SMTP, default 127.0.0.1:2525); the application form has
a file upload, a custom date picker, a rich text editor and a custom multi-select; and
POST /test-support/reset (header X-Test-Key: demo-reset-key) restores the seed data, and
POST /test-support/clock {"advance_s": N} moves the portal's clock forward, so OTP expiry (5 minutes) and
idle-session expiry (15 minutes, DEMO_SESSION_IDLE) can be tested without waiting.

Set DEMO_VISUAL_CHANGE=1 to restyle the header and move the Apply button (shows visual testing).
Set DEMO_VERIFY_LABEL="Mark verified" to rename the Clerk's button (shows the Healer on workflows).
Set DEMO_FIXED=B4,B5,B16 to fix seeded bugs (shows defects verified as fixed and closed in Jira).
"""
from __future__ import annotations

import copy
import json
import os
import random
import re
import smtplib
import threading
import time
import urllib.request
from datetime import date
from email.message import EmailMessage
from itertools import count

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import DictLoader, Environment, select_autoescape
from starlette.middleware.sessions import SessionMiddleware

# Set DEMO_MOBILE_FIELD=mobile_no to simulate a UI change (used to demonstrate the Healer).
MOBILE = os.environ.get("DEMO_MOBILE_FIELD", "mobile")

USERS = {
    "citizen1": {"password": "Citizen@123", "role": "citizen", "name": "Asha Citizen", "mobile": "9847012345"},
    "citizen2": {"password": "Citizen@123", "role": "citizen", "name": "Vinod Citizen", "mobile": "9946098765"},
    "clerk1": {"password": "Clerk@123", "role": "clerk", "name": "Ravi Clerk"},
    "officer1": {"password": "Officer@123", "role": "officer", "name": "Meera Officer", "mobile": "9895000001"},
    "admin1": {"password": "Admin@123", "role": "admin", "name": "Arun Admin"},
}
SEED_APPS: dict[int, dict] = {
    1001: {"id": 1001, "applicant_name": "Asha Citizen", "mobile": "9847012345", "email": "asha@example.com",
           "pincode": "695001", "dob": "1988-02-11", "address": "12 Main Road, Model Town",
           "cert_type": "income", "status": "Submitted", "owner": "citizen1"},
    1002: {"id": 1002, "applicant_name": "Asha Citizen", "mobile": "9847012345", "email": "asha@example.com",
           "pincode": "695001", "dob": "1988-02-11", "address": "12 Main Road, Model Town",
           "cert_type": "residence", "status": "Approved", "owner": "citizen1"},
    1003: {"id": 1003, "applicant_name": "Vinod Citizen", "mobile": "9946098765", "email": "vinod@example.com",
           "pincode": "682001", "dob": "1979-07-30", "address": "4 Marine Drive, Kochi",
           "cert_type": "income", "status": "Submitted", "owner": "citizen2"},
}
APPS: dict[int, dict] = copy.deepcopy(SEED_APPS)
_ids = count(1004)
VISUAL = os.environ.get("DEMO_VISUAL_CHANGE") == "1"
VERIFY = os.environ.get("DEMO_VERIFY_LABEL", "Verify")
FIXED = {x.strip().upper() for x in os.environ.get("DEMO_FIXED", "").split(",") if x.strip()}
SMS_URL = os.environ.get("DEMO_SMS_URL", "http://127.0.0.1:8025/sms")
SMTP = os.environ.get("DEMO_SMTP", "127.0.0.1:2525")
RESET_KEY = os.environ.get("DEMO_RESET_KEY", "demo-reset-key")
OTPS: dict[str, dict] = {}
CLOCK = {"offset": 0.0}          # test-support clock: POST /test-support/clock moves it forward
OTP_TTL = 300                    # SRS FR-15: an OTP is valid for 5 minutes
SESSION_IDLE = float(os.environ.get("DEMO_SESSION_IDLE", "900"))   # SRS NFR-03: 15 minutes of inactivity
# Two portals over one back end, as on many government sites: citizens on the Citizen Portal, staff on the
# Department Portal (python -m demo.portal.serve). Run as a single app (uvicorn demo.portal.app:app), everything
# is on one site as before.
CITIZEN_URL = os.environ.get("DEMO_CITIZEN_URL", "http://127.0.0.1:8800").rstrip("/")
DEPT_URL = os.environ.get("DEMO_DEPT_URL", "http://127.0.0.1:8810").rstrip("/")
DEPT_ONLY = ("/department/", "/login/otp", "/clerk/", "/officer/", "/admin/", "/api/users")
CITIZEN_ONLY = ("/citizen/", "/apply", "/my-applications", "/applications/", "/api/applications", "/api/my-applications",
                "/search", "/help", "/static-logo")


def now() -> float:
    return time.time() + CLOCK["offset"]
DOCS = [("aadhaar", "Aadhaar"), ("ration", "Ration Card"), ("voter", "Voter ID"),
        ("passport" if "B17" in FIXED else "dl", "Passport" if "B17" in FIXED else "Driving Licence")]
MAX_UPLOAD = 2 * 1024 * 1024


def send_sms(to: str, text: str) -> None:
    print(f"[demo SMS to {to}] {text}", flush=True)
    try:
        req = urllib.request.Request(SMS_URL, data=json.dumps({"to": to, "text": text}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as exc:  # noqa: BLE001
        print(f"[demo SMS] gateway {SMS_URL} not reachable ({exc}); use the code printed above", flush=True)


def send_email(to: str, subject: str, body: str) -> None:
    def go():
        host, _, port = SMTP.partition(":")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = "noreply@demo-portal.example", to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(host, int(port or 25), timeout=5) as smtp:
                smtp.send_message(msg)
        except Exception as exc:  # noqa: BLE001
            print(f"[demo email] to {to} not sent ({exc}): {subject}", flush=True)
    threading.Thread(target=go, daemon=True).start()


def issue_otp(username: str) -> None:
    o = OTPS.get(username)
    fresh = "B15" in FIXED or not o or now() - o["at"] > OTP_TTL
    if fresh:  # B15: otherwise the old, already used code is sent again and stays valid
        o = OTPS[username] = {"code": f"{random.SystemRandom().randint(0, 999999):06d}", "at": now(), "used": False}
    send_sms(USERS[username]["mobile"], f"Your Demo Certificate Portal login OTP is {o['code']}. "
                                        f"It is valid for 5 minutes. Do not share it with anyone.")


def citizen_by_mobile(mobile: str) -> str | None:
    return next((u for u, v in USERS.items() if v["role"] == "citizen" and v.get("mobile") == mobile), None)


def check_otp(username: str, code: str) -> bool:
    o = OTPS.get(username)
    if not o or now() - o["at"] > OTP_TTL or code.strip() != o["code"]:
        return False
    if "B15" in FIXED:
        if o["used"]:
            return False
        o["used"] = True
    return True

LANG = os.environ.get("DEMO_LANG", "en")               # ml: the portal opens in Malayalam (switch to English in the header)
HARD_LOGIN = os.environ.get("DEMO_HARD_LOGIN") == "1"   # the way in is an unlabelled icon and the mobile box is unnamed
ML = {
    "Demo Certificate Portal": "ഡെമോ സർട്ടിഫിക്കറ്റ് പോർട്ടൽ", "Department Portal": "വകുപ്പ് പോർട്ടൽ", "Home": "ഹോം",
    "Help": "സഹായം", "Login": "ലോഗിൻ", "Logout": "ലോഗൗട്ട്", "Dashboard": "ഡാഷ്ബോർഡ്", "Services &#9662;": "സേവനങ്ങൾ &#9662;",
    "Apply for Certificate": "സർട്ടിഫിക്കറ്റിന് അപേക്ഷിക്കുക", "My Applications": "എന്റെ അപേക്ഷകൾ",
    "Verification Queue": "പരിശോധനാ ക്യൂ", "Approval Queue": "അംഗീകാര ക്യൂ", "User Management": "ഉപയോക്തൃ മാനേജ്മെന്റ്",
    "Reports": "റിപ്പോർട്ടുകൾ", "Staff Login": "ജീവനക്കാരുടെ ലോഗിൻ", "How do you want to log in?": "എങ്ങനെ ലോഗിൻ ചെയ്യണം?",
    "Citizen Login": "പൗര ലോഗിൻ", "Department Login": "വകുപ്പ് ലോഗിൻ", "Cancel": "റദ്ദാക്കുക",
    "Certificate Services": "സർട്ടിഫിക്കറ്റ് സേവനങ്ങൾ",
    "Apply for income, residence and other certificates online.": "വരുമാനം, താമസം, മറ്റ് സർട്ടിഫിക്കറ്റുകൾ എന്നിവയ്ക്ക് ഓൺലൈനായി അപേക്ഷിക്കുക.",
    "Search": "തിരയുക", "Please log in to continue.": "തുടരാൻ ദയവായി ലോഗിൻ ചെയ്യുക.", "Mobile Number": "മൊബൈൽ നമ്പർ",
    "Registered number": "രജിസ്റ്റർ ചെയ്ത നമ്പർ", "Get OTP": "OTP നേടുക", "Username": "ഉപയോക്തൃനാമം",
    "Password": "പാസ്‌വേഡ്", "Sign in": "സൈൻ ഇൻ", "One-time password": "ഒറ്റത്തവണ പാസ്‌വേഡ്",
    "Verify &amp; Login": "പരിശോധിച്ച് ലോഗിൻ ചെയ്യുക", "Resend OTP": "OTP വീണ്ടും അയയ്ക്കുക",
    "For staff of the certificate department: verification, approval and administration. Log in with your department username and password.":
        "സർട്ടിഫിക്കറ്റ് വകുപ്പിലെ ജീവനക്കാർക്ക്: പരിശോധന, അംഗീകാരം, ഭരണം. നിങ്ങളുടെ വകുപ്പ് ഉപയോക്തൃനാമവും പാസ്‌വേഡും ഉപയോഗിച്ച് ലോഗിൻ ചെയ്യുക.",
}


def to_malayalam(html: str) -> str:
    """The page as a Malayalam-first portal shows it (the text people read; addresses and form names stay)."""
    def one(m):
        seg = m.group(1)
        key = re.sub(r"\s+", " ", seg.strip())
        return ">" + seg.replace(seg.strip(), ML[key]) + "<" if key in ML else m.group(0)
    return re.sub(r">([^<>]+)<", one, html)


BASE = """<!doctype html><html lang="{{ lang }}"><head><meta charset="utf-8">
<title>{% block title %}Demo Certificate Portal{% endblock %}</title>
<style>body{font-family:system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1b1f24}
header{background:{{ '#5b2a86' if visual else '#14365f' }};color:#fff;padding:12px 24px;display:flex;gap:18px;align-items:center}
header a{color:#fff;text-decoration:none}main{max-width:860px;margin:24px auto;background:#fff;padding:24px;border-radius:8px}
label{display:block;margin-top:12px;font-weight:600}input,select,textarea{padding:8px;width:100%;max-width:420px;box-sizing:border-box}
.error{background:#fdecea;color:#8a1c12;padding:10px;border-radius:6px;margin:8px 0}
.ok{background:#e6f4ea;color:#1e5c2e;padding:10px;border-radius:6px;margin:8px 0}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left}
button{margin-top:16px;padding:9px 18px;background:#14365f;color:#fff;border:0;border-radius:6px}
.dp{position:relative;max-width:420px}.dp-cal{position:absolute;z-index:5;background:#fff;border:1px solid #bbb;border-radius:8px;padding:8px;box-shadow:0 6px 18px rgba(0,0,0,.15);width:260px}
.dp-cal .nav{display:flex;gap:6px;align-items:center;margin-bottom:6px}.dp-cal select{width:auto;padding:4px}
.dp-cal .days{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}.dp-cal .days button{margin:0;padding:6px 0;background:#eef2f7;color:#1b1f24;border-radius:4px}
.dp-cal .days button:hover{background:#14365f;color:#fff}
.rte{max-width:420px;border:1px solid #bbb;border-radius:6px}.rte-bar{display:flex;gap:4px;padding:4px;border-bottom:1px solid #ddd;background:#f6f7f9}
.rte-bar button{margin:0;padding:3px 9px;background:#fff;color:#1b1f24;border:1px solid #ccc}.rte-body{min-height:70px;padding:8px;outline:none}
.ms{max-width:420px;display:flex;flex-wrap:wrap;gap:6px;padding:6px;border:1px solid #bbb;border-radius:6px}
.ms [role=option]{padding:4px 10px;border:1px solid #9aa;border-radius:99px;cursor:pointer;user-select:none}
.ms [role=option][aria-selected=true]{background:#14365f;color:#fff;border-color:#14365f}.hint{font-size:12px;color:#555}
.hdr-btn{margin:0;padding:6px 12px;background:#fff;color:#14365f;font-weight:600}.menu{position:relative}
#svc-menu{position:absolute;top:34px;left:0;background:#fff;border:1px solid #ccc;border-radius:6px;display:flex;flex-direction:column;min-width:200px;z-index:9}
#svc-menu[hidden]{display:none}#svc-menu button{margin:0;background:#fff;color:#14365f;text-align:left;border-radius:0}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.45);display:grid;place-items:center;z-index:20}.modal[hidden]{display:none}
.modal .box{background:#fff;padding:24px;border-radius:10px;min-width:320px}.link{background:none;color:#14365f;text-decoration:underline}
.otp-boxes{display:flex;gap:8px}.otp-boxes input{width:44px;text-align:center;font-size:20px;padding:8px}</style>
</head><body><header><strong>{{ 'Department Portal' if portal == 'department' else 'Demo Certificate Portal' }}</strong>
<nav aria-label="Main">{% if user %}
 {% if user.role == 'citizen' %}<a href="/dashboard">Dashboard</a>
 <span class="menu"><button type="button" class="hdr-btn" id="svc-btn" aria-haspopup="true" aria-expanded="false" aria-controls="svc-menu">Services &#9662;</button>
 <span id="svc-menu" role="menu" hidden><button type="button" role="menuitem" data-go="/apply">Apply for Certificate</button><button type="button" role="menuitem" data-go="/my-applications">My Applications</button></span></span>{% endif %}
 {% if user.role == 'clerk' %}<a href="/dashboard">Dashboard</a> <a href="/clerk/queue">Verification Queue</a>{% endif %}
 {% if user.role == 'officer' %}<a href="/dashboard">Dashboard</a> <a href="/officer/queue">Approval Queue</a>{% endif %}
 {% if user.role == 'admin' %}<a href="/dashboard">Dashboard</a> <a href="/admin/users">User Management</a> <a href="/admin/reports">Reports</a>{% endif %}
 {% if portal != 'department' %}<a href="/help">Help</a>{% endif %} <a href="/logout">Logout</a>
{% elif portal == 'department' %}<a href="/">Home</a> <a href="/department/login">Staff Login</a>
{% elif hard %}<a href="/">Home</a> <a href="/help">Help</a> <button type="button" class="hdr-btn" id="login-open" aria-haspopup="dialog" title="My account">&#128100;</button>
{% else %}<a href="/">Home</a> <a href="/help">Help</a> <button type="button" class="hdr-btn" id="login-open" aria-haspopup="dialog">Login</button>{% endif %}
 {% if lang == 'ml' %}<a href="/lang/en" lang="en" hreflang="en">English</a>{% else %}<a href="/lang/ml" lang="ml" hreflang="ml">മലയാളം</a>{% endif %}</nav></header>
<div class="modal" id="login-choice" role="dialog" aria-modal="true" aria-labelledby="lc-title" hidden><div class="box">
<h2 id="lc-title">Login</h2><p>How do you want to log in?</p>
<button type="button" data-go="{{ citizen_url }}/citizen/login">Citizen Login</button> <button type="button" data-go="{{ dept_url }}/department/login">Department Login</button>
<button type="button" class="link" data-close>Cancel</button></div></div>
<main>{% block body %}{% endblock %}</main>
<script>
document.querySelectorAll('[data-go]').forEach(b => b.addEventListener('click', () => { location.href = b.dataset.go; }));
const lo = document.getElementById('login-open'), lc = document.getElementById('login-choice');
if (lo) lo.addEventListener('click', () => { lc.hidden = false; lc.querySelector('[data-go]').focus(); });
document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => { lc.hidden = true; }));
const sb = document.getElementById('svc-btn'), sm = document.getElementById('svc-menu');
if (sb) sb.addEventListener('click', () => { sm.hidden = !sm.hidden; sb.setAttribute('aria-expanded', String(!sm.hidden)); });
</script></body></html>"""

T = {
    "base.html": BASE,
    "home.html": """{% extends "base.html" %}{% block title %}Home - Demo Certificate Portal{% endblock %}{% block body %}
<h1>Certificate Services</h1><img src="/static-logo.svg" width="64" height="64">
<p>Apply for income, residence and other certificates online.</p>
<form action="/search" method="get"><input name="q" placeholder="Search services"><button type="submit">Search</button></form>
{% endblock %}""",
    "search.html": """{% extends "base.html" %}{% block title %}Search{% endblock %}{% block body %}
<h1>Search results</h1><p>No services match "{{ q|safe }}".</p>{% endblock %}""",
    "login.html": """{% extends "base.html" %}{% block title %}Login{% endblock %}{% block body %}
<h1>Login</h1><p>Please log in to continue.</p>
<button type="button" data-go="{{ citizen_url }}/citizen/login">Citizen Login</button> <button type="button" data-go="{{ dept_url }}/department/login">Department Login</button>{% endblock %}""",
    "dept_home.html": """{% extends "base.html" %}{% block title %}Department Portal{% endblock %}{% block body %}
<h1>Department Portal</h1><p>For staff of the certificate department: verification, approval and administration.
Log in with your department username and password.</p><p><a href="/department/login">Staff Login</a></p>{% endblock %}""",
    "dept_login.html": """{% extends "base.html" %}{% block title %}Department Login{% endblock %}{% block body %}
<h1>Department Login</h1>{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
<form method="post" action="/department/login"><label for="username">Username</label><input id="username" name="username" required>
<label for="password">Password</label><input id="password" name="password" type="password" required>
<button type="submit">Sign in</button></form>{% endblock %}""",
    "citizen_login.html": """{% extends "base.html" %}{% block title %}Citizen Login{% endblock %}{% block body %}
<h1>Citizen Login</h1>{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
{% if info %}<div class="ok" role="status">{{ info }}</div>{% endif %}
{% if not tail %}<form method="post" action="/citizen/login">
{% if hard %}<label for="rn">Registered number</label><input id="rn" name="rn" inputmode="numeric" maxlength="10" value="{{ mobile }}">
{% else %}<label for="mobile_no">Mobile Number</label><input id="mobile_no" name="mobile_no" type="tel" inputmode="numeric" maxlength="10" placeholder="10-digit mobile number" value="{{ mobile }}">{% endif %}
<button type="submit">Get OTP</button></form>
{% else %}<p>Enter the 6-digit OTP sent to your mobile number ending {{ tail }}.</p>
<form method="post" action="/citizen/login/verify" id="otp-form"><label id="otp-label">One-time password</label>
<div class="otp-boxes" role="group" aria-labelledby="otp-label">{% for i in range(6) %}<input class="otp-box" inputmode="numeric" maxlength="1" aria-label="OTP digit {{ i + 1 }}" autocomplete="{{ 'one-time-code' if i == 0 else 'off' }}">{% endfor %}</div>
<input type="hidden" name="otp" id="otp">
<button type="submit">Verify &amp; Login</button> <button type="button" id="resend" class="link">Resend OTP</button></form>
<form method="post" action="/citizen/login/resend" id="resend-form" hidden></form>
<script>
const boxes = [...document.querySelectorAll('.otp-box')], hid = document.getElementById('otp');
boxes.forEach((b, i) => b.addEventListener('input', () => { b.value = b.value.replace(/\\D/g, '').slice(0, 1); if (b.value && boxes[i + 1]) boxes[i + 1].focus(); hid.value = boxes.map(x => x.value).join(''); }));
boxes[0].addEventListener('paste', e => { const t = (e.clipboardData.getData('text') || '').replace(/\\D/g, ''); if (t) { e.preventDefault(); boxes.forEach((b, i) => b.value = t[i] || ''); hid.value = t.slice(0, 6); } });
document.getElementById('otp-form').addEventListener('submit', () => { hid.value = boxes.map(x => x.value).join(''); });
{% if resend_works %}document.getElementById('resend').addEventListener('click', () => document.getElementById('resend-form').submit());{% endif %}
</script>{% endif %}{% endblock %}""",
    "dashboard.html": """{% extends "base.html" %}{% block title %}Dashboard{% endblock %}{% block body %}
<h1>Welcome, {{ user.name }}</h1><p>Your role: {{ user.role|capitalize }}</p>
<p id="signed-in"></p>{% if user.role == 'citizen' %}<p id="app-count"></p>{% endif %}
<script>
fetch('/api/me').then(r => r.json()).then(me => { document.getElementById('signed-in').textContent = 'Signed in as ' + me.username; });
{% if user.role == 'citizen' %}fetch('/api/my-applications').then(r => r.json()).then(list => {
  document.getElementById('app-count').textContent = 'You have ' + list.length + ' application(s) on record.'; });{% endif %}
</script>{% endblock %}""",
    "apply.html": """{% extends "base.html" %}{% block title %}Apply for Certificate{% endblock %}{% block body %}
<h1>Apply for Certificate</h1>
{% for e in errors %}<div class="error" role="alert">{{ e }}</div>{% endfor %}
{% if done %}<div class="ok" role="status">Application submitted successfully. Application ID: <span id="app-id">{{ done }}</span></div>{% endif %}
<form method="post" action="/apply" id="apply-form" enctype="multipart/form-data">
<label for="applicant_name">Applicant Name</label><input id="applicant_name" name="applicant_name" maxlength="100" required value="{{ v.applicant_name }}">
<label for="{{ mobile_field }}">Mobile Number</label><input id="{{ mobile_field }}" name="{{ mobile_field }}" type="tel" maxlength="10" required value="{{ v.mobile }}">
<label for="email">Email Address</label><input id="email" name="email" type="email" maxlength="100" value="{{ v.email }}">
<label for="pincode">PIN Code</label><input id="pincode" name="pincode" pattern="[0-9]{6}" maxlength="6" required value="{{ v.pincode }}">
<label for="dob_display">Date of Birth</label>
<div class="dp"><input id="dob_display" placeholder="DD/MM/YYYY" readonly required autocomplete="off" aria-haspopup="dialog" class="datepicker" value="{{ v.dob_display }}">
<input type="hidden" id="dob" name="dob" value="{{ v.dob }}"><div class="dp-cal" hidden role="dialog" aria-label="Choose date of birth"></div></div>
<label for="cert_type">Certificate Type</label><select id="cert_type" name="cert_type" required>
<option value="">-- Select --</option><option value="income">Income</option><option value="residence">Residence</option><option value="nativity">Nativity</option></select>
<label id="docs-label">Documents Attached</label>
<div class="ms-wrap"><div class="ms" id="docs_select" role="listbox" aria-multiselectable="true" aria-labelledby="docs-label" aria-required="true" tabindex="0">
{% for val, text in docs %}<div role="option" data-value="{{ val }}" aria-selected="{{ 'true' if val in v.docs else 'false' }}">{{ text }}</div>{% endfor %}</div>
<select name="docs" id="docs" multiple hidden>{% for val, text in docs %}<option value="{{ val }}" {{ 'selected' if val in v.docs }}>{{ text }}</option>{% endfor %}</select>
<div class="hint">Choose one or more.</div></div>
<label id="purpose-label">Purpose of Certificate</label>
<div class="rte"><div class="rte-bar"><button type="button" data-cmd="bold" aria-label="Bold"><b>B</b></button><button type="button" data-cmd="italic" aria-label="Italic"><i>I</i></button></div>
<div id="purpose_editor" class="rte-body" contenteditable="true" role="textbox" aria-multiline="true" aria-labelledby="purpose-label" aria-required="true">{{ v.purpose }}</div>
<input type="hidden" id="purpose" name="purpose" value="{{ v.purpose }}"></div>
<label for="address">Address</label><textarea id="address" name="address" maxlength="200" required>{{ v.address }}</textarea>
<label for="document">Supporting Document (optional)</label><input id="document" name="document" type="file" accept=".pdf,.jpg,.jpeg,.png">
<div class="hint">PDF, JPG or PNG, up to 2 MB.</div>
<label><input type="checkbox" name="declaration" required style="width:auto"> I declare the information is true</label>
{% if visual %}<p><button type="submit" style="margin-top:28px;background:#5b2a86">Submit Application</button></p>{% else %}<button type="submit">Submit Application</button>{% endif %}</form>
<script>
(() => {
  const pad = n => String(n).padStart(2, '0');
  const disp = document.getElementById('dob_display'), hid = document.getElementById('dob'), cal = document.querySelector('.dp-cal');
  const fromDisp = t => { const m = /^(\\d{2})\\/(\\d{2})\\/(\\d{4})$/.exec(t.trim()); return m ? `${m[3]}-${m[2]}-${m[1]}` : ''; };
  const sync = () => { hid.value = fromDisp(disp.value); };
  disp.addEventListener('change', sync); disp.addEventListener('input', sync); disp.addEventListener('blur', sync);
  function draw(y, m) {
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    let yo = ''; for (let k = new Date().getFullYear() + 5; k >= 1920; k--) yo += `<option ${k === y ? 'selected' : ''}>${k}</option>`;
    cal.innerHTML = `<div class="nav"><select class="m" aria-label="Month">${months.map((t, i) => `<option value="${i}" ${i === m ? 'selected' : ''}>${t}</option>`).join('')}</select>
      <select class="y" aria-label="Year">${yo}</select></div><div class="days"></div>`;
    const days = cal.querySelector('.days'), n = new Date(y, m + 1, 0).getDate();
    for (let d = 1; d <= n; d++) { const b = document.createElement('button'); b.type = 'button'; b.textContent = d;
      b.onclick = () => { disp.value = `${pad(d)}/${pad(m + 1)}/${y}`; sync(); cal.hidden = true; }; days.appendChild(b); }
    cal.querySelector('.m').onchange = e => draw(y, +e.target.value); cal.querySelector('.y').onchange = e => draw(+e.target.value, m);
  }
  disp.addEventListener('click', () => { const v = hid.value ? new Date(hid.value) : new Date(1990, 0, 1); draw(v.getFullYear(), v.getMonth()); cal.hidden = false; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') cal.hidden = true; });
  document.addEventListener('click', e => { if (!e.target.closest('.dp')) cal.hidden = true; });
  // rich text editor
  const ed = document.getElementById('purpose_editor'), ph = document.getElementById('purpose');
  const save = () => { ph.value = ed.innerHTML.trim() === '<br>' ? '' : ed.innerHTML.trim(); };
  ed.addEventListener('input', save); ed.addEventListener('blur', save);
  document.querySelectorAll('.rte-bar button').forEach(b => b.addEventListener('click', () => { document.execCommand(b.dataset.cmd); ed.focus(); save(); }));
  // multi-select chips
  const sel = document.getElementById('docs');
  document.querySelectorAll('#docs_select [role=option]').forEach(o => o.addEventListener('click', () => {
    const on = o.getAttribute('aria-selected') !== 'true'; o.setAttribute('aria-selected', on);
    [...sel.options].find(x => x.value === o.dataset.value).selected = on;
  }));
  document.getElementById('apply-form').addEventListener('submit', () => { sync(); save(); });
})();
</script>{% endblock %}""",
    "otp.html": """{% extends "base.html" %}{% block title %}Verify OTP{% endblock %}{% block body %}
<h1>Verify one-time password</h1>{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
<p>Enter the 6-digit OTP sent to your registered mobile number ending {{ tail }}.</p>
<form method="post" action="/login/otp"><label for="otp">One-time password</label><input id="otp" name="otp" inputmode="numeric" maxlength="6" autocomplete="one-time-code" required>
<button type="submit">Verify OTP</button></form>{% endblock %}""",
    "mine.html": """{% extends "base.html" %}{% block title %}My Applications{% endblock %}{% block body %}
<h1>My Applications</h1><table><tr><th>ID</th><th>Type</th><th>Status</th><th>Details</th></tr>
{% for a in apps %}<tr><td>{{ a.id }}</td><td>{{ a.cert_type|capitalize }}</td><td class="status" data-id="{{ a.id }}">{{ a.status }}</td><td><a href="/applications/{{ a.id }}">View {{ a.id }}</a></td></tr>{% endfor %}
</table><p id="summary"></p>
<script>document.getElementById('summary').textContent = 'You have ' + appCount + ' application(s).';</script>{% endblock %}""",
    "queue.html": """{% extends "base.html" %}{% block title %}{{ heading }}{% endblock %}{% block body %}
<h1>{{ heading }}</h1><table><tr><th>ID</th><th>Applicant</th><th>Type</th><th>Status</th><th>Action</th></tr>
{% for a in apps %}<tr><td>{{ a.id }}</td><td>{{ a.applicant_name }}</td><td>{{ a.cert_type|capitalize }}</td><td>{{ a.status }}</td>
<td><form method="post" action="{{ action }}/{{ a.id }}"><button type="submit" name="go" value="1">{{ verb }} {{ a.id }}</button></form></td></tr>{% endfor %}
</table>{% if not apps %}<p>No applications waiting.</p>{% endif %}{% endblock %}""",
    "users.html": """{% extends "base.html" %}{% block title %}User Management{% endblock %}{% block body %}
<h1>User Management</h1><table><thead><tr><th>Username</th><th>Name</th><th>Role</th></tr></thead><tbody id="users"></tbody></table>
<script>
fetch('/api/users').then(r => r.json()).then(list => {
  const tb = document.getElementById('users');
  for (const u of list) { const tr = document.createElement('tr');
    for (const k of ['username', 'name', 'role']) { const td = document.createElement('td'); td.textContent = u[k]; tr.appendChild(td); }
    tb.appendChild(tr); }
});
</script>{% endblock %}""",
    "details.html": """{% extends "base.html" %}{% block title %}Application {{ app_id }}{% endblock %}{% block body %}
<h1>Application {{ app_id }}</h1><dl id="details"><dt>Status</dt><dd>Loading...</dd></dl>
<p><a href="/my-applications">Back to My Applications</a></p>
<script>
fetch('/api/applications/{{ app_id }}').then(r => r.json()).then(a => {
  const dl = document.getElementById('details'); dl.innerHTML = '';
  for (const [k, label] of [['cert_type', 'Certificate type'], ['status', 'Status'], ['applicant_name', 'Applicant'], ['mobile', 'Mobile'], ['email', 'Email']]) {
    const dt = document.createElement('dt'); dt.textContent = label; const dd = document.createElement('dd'); dd.textContent = a[k] || '-';
    dl.appendChild(dt); dl.appendChild(dd); }
});
</script>{% endblock %}""",
    "help.html": """{% extends "base.html" %}{% block title %}Help{% endblock %}{% block body %}
<h1>Help</h1><p>Need help? Read the <a href="/help/faq">frequently asked questions</a> or
<a href="/help/contact">contact the helpdesk</a>.</p>{% endblock %}""",
    "faq.html": """{% extends "base.html" %}{% block title %}FAQ{% endblock %}{% block body %}
<h1>Frequently asked questions</h1><p>How long does approval take? Usually five working days.</p>{% endblock %}""",
    "contact.html": """{% extends "base.html" %}{% block title %}Contact Helpdesk{% endblock %}{% block body %}
<h1>Contact Helpdesk</h1><p>Call 1800-000-0000 (demo number).</p>{% endblock %}""",
    "denied.html": """{% extends "base.html" %}{% block title %}Access denied{% endblock %}{% block body %}
<h1>Access denied</h1><p>You are not authorized to view this page.</p>{% endblock %}""",
    "notfound.html": """{% extends "base.html" %}{% block title %}Not found{% endblock %}{% block body %}
<h1>Page not found</h1>{% endblock %}""",
}

env = Environment(loader=DictLoader(T), autoescape=select_autoescape())
app = FastAPI(title="Demo Certificate Portal")
app.add_middleware(SessionMiddleware, secret_key="demo-only-secret", same_site="lax")


def user_of(request: Request) -> dict | None:
    u = request.session.get("u")
    if u in USERS:
        seen = float(request.session.get("seen") or now())
        if now() - seen > SESSION_IDLE:          # idle too long: the session has expired
            request.session.clear()
            return None
        request.session["seen"] = now()
    return {**USERS[u], "username": u} if u in USERS else None


def portal_of(request: Request) -> str:
    return request.scope.get("portal", "single")


def page(name: str, request: Request, status: int = 200, **ctx) -> HTMLResponse:
    portal = portal_of(request)
    links = {"citizen_url": CITIZEN_URL if portal != "single" else "", "dept_url": DEPT_URL if portal != "single" else ""}
    lang = request.cookies.get("lang") or LANG
    html = env.get_template(name).render(user=user_of(request), mobile_field=MOBILE, visual=VISUAL, portal=portal, **links,
                                         lang=lang, hard=HARD_LOGIN, **ctx)
    if lang == "ml":
        html = to_malayalam(html)
    return HTMLResponse(html, status_code=status)


@app.get("/lang/{code}")
def set_language(request: Request, code: str):
    back = request.headers.get("referer") or "/"
    if not back.startswith(str(request.base_url).rstrip("/")):
        back = "/"
    r = RedirectResponse(back, status_code=303)
    r.set_cookie("lang", "ml" if code == "ml" else "en", path="/", samesite="lax", httponly=True)
    return r


def need(request: Request, *roles: str):
    u = user_of(request)
    if u is None:
        to = "/department/login?next=" if portal_of(request) == "department" else "/login?next="
        return RedirectResponse(to + request.url.path, status_code=303)
    if roles and u["role"] not in roles:
        return page("denied.html", request, status=403)
    return None


@app.get("/static-logo.svg")
def logo():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="30" fill="#14365f"/></svg>'
    return HTMLResponse(svg, media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return page("dept_home.html" if portal_of(request) == "department" else "home.html", request)


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    return page("search.html", request, q=q)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page("login.html", request)


@app.get("/department/login", response_class=HTMLResponse)
def dept_login_form(request: Request):
    return page("dept_login.html", request)


def _citizen_page(request: Request, status: int = 200, **ctx) -> HTMLResponse:
    return page("citizen_login.html", request, status=status, resend_works="B19" in FIXED, **ctx)


@app.get("/citizen/login", response_class=HTMLResponse)
def citizen_login_form(request: Request):
    request.session.pop("pending_citizen", None)
    return _citizen_page(request)


@app.post("/citizen/login", response_class=HTMLResponse)
def citizen_send_otp(request: Request, mobile_no: str = Form(""), rn: str = Form("")):
    m = (mobile_no or rn).strip()
    valid = re.fullmatch(r"[6-9]\d{9}", m) if "B18" in FIXED else re.fullmatch(r"\d{9,10}", m)  # B18: 9 digits pass
    if not valid:
        return _citizen_page(request, status=400, mobile=m, error="Enter a valid 10-digit mobile number")
    user = citizen_by_mobile(m)
    if not user:
        if len(m) == 9:   # B18: the bad number goes on to the OTP step (no SMS can arrive)
            request.session["pending_citizen"] = "-"
            return _citizen_page(request, tail=m[-4:], info="OTP sent")
        return _citizen_page(request, status=404, mobile=m, error="This mobile number is not registered")
    request.session.clear()
    request.session["pending_citizen"] = user
    issue_otp(user)
    return _citizen_page(request, tail=m[-4:], info="OTP sent")


@app.post("/citizen/login/resend", response_class=HTMLResponse)
def citizen_resend(request: Request):
    user = request.session.get("pending_citizen")
    if user not in USERS:
        return RedirectResponse("/citizen/login", status_code=303)
    OTPS.pop(user, None)
    issue_otp(user)
    return _citizen_page(request, tail=USERS[user]["mobile"][-4:], info="A new OTP has been sent")


@app.post("/citizen/login/verify", response_class=HTMLResponse)
def citizen_verify(request: Request, otp: str = Form("")):
    user = request.session.get("pending_citizen")
    if not user:
        return RedirectResponse("/citizen/login", status_code=303)
    if user not in USERS or not check_otp(user, otp):
        tail = USERS[user]["mobile"][-4:] if user in USERS else "----"
        return _citizen_page(request, status=401, tail=tail, error="Invalid OTP. Please try again.")
    request.session.clear()
    request.session["u"] = user
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/department/login")
def login(request: Request, username: str = Form(""), password: str = Form("")):
    u = USERS.get(username)
    if not u or u["password"] != password or u["role"] == "citizen":
        return page("dept_login.html", request, status=401, error="Invalid username or password")
    if u["role"] == "officer":
        request.session.clear()
        request.session["pending"] = username
        issue_otp(username)
        return RedirectResponse("/login/otp", status_code=303)
    request.session["u"] = username
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/login/otp", response_class=HTMLResponse)
def otp_form(request: Request):
    pending = request.session.get("pending")
    if pending not in USERS:
        return RedirectResponse("/department/login", status_code=303)
    return page("otp.html", request, tail=USERS[pending]["mobile"][-4:])


@app.post("/login/otp")
def otp_verify(request: Request, otp: str = Form("")):
    pending = request.session.get("pending")
    if pending not in USERS:
        return RedirectResponse("/login", status_code=303)
    if not check_otp(pending, otp):
        return page("otp.html", request, status=401, error="Invalid or expired OTP", tail=USERS[pending]["mobile"][-4:])
    request.session.clear()
    request.session["u"] = pending
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return need(request) or page("dashboard.html", request)


EMPTY = {**{k: "" for k in ("applicant_name", "mobile", "email", "pincode", "dob", "dob_display", "address", "purpose")},
         "docs": []}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


@app.get("/apply", response_class=HTMLResponse)
def apply_form(request: Request):
    return need(request, "citizen") or page("apply.html", request, errors=[], done=None, v=EMPTY, docs=DOCS)


@app.post("/apply", response_class=HTMLResponse)
async def apply(request: Request):
    denied = need(request, "citizen")
    if denied:
        return denied
    form = await request.form()
    get = lambda k: str(form.get(k) or "")  # noqa: E731
    applicant_name, mobile, email, pincode = get("applicant_name"), get(MOBILE), get("email"), get("pincode")
    dob, cert_type, address, declaration = get("dob"), get("cert_type"), get("address"), get("declaration")
    purpose, docs = get("purpose"), [str(x) for x in form.getlist("docs")]
    upload = form.get("document")
    dob_display = "/".join(reversed(dob.split("-"))) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob) else ""
    v = dict(applicant_name=applicant_name, mobile=mobile, email=email, pincode=pincode, dob=dob, address=address,
             dob_display=dob_display, purpose=purpose, docs=docs)
    errors = []
    if not applicant_name.strip():
        errors.append("Applicant Name is required")
    elif len(applicant_name) > 100:  # B2: SRS says 50
        errors.append("Applicant Name must be at most 100 characters")
    if not mobile.strip():
        errors.append("Mobile Number is required")
    elif len(mobile) != 10:  # B3: no digit or 6-9 check
        errors.append("Mobile Number must be 10 digits")
    if email and (len(email) > 100 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", email)):
        errors.append("Email Address is invalid")
    if not re.fullmatch(r"\d{6}", pincode or ""):
        errors.append("PIN Code must be 6 digits")
    if not dob:
        errors.append("Date of Birth is required")
    else:
        try:
            if date.fromisoformat(dob) > date.today():
                errors.append("Date of Birth cannot be in the future")
        except ValueError:
            errors.append("Date of Birth is invalid")
    if cert_type not in ("income", "residence", "nativity"):
        errors.append("Certificate Type is required")
    allowed_docs = {d for d, _ in DOCS}
    if not docs:
        errors.append("Select at least one document in Documents Attached")
    elif any(d not in allowed_docs for d in docs):
        errors.append("Documents Attached has an invalid choice")
    if not _plain(purpose):
        errors.append("Purpose of Certificate is required")
    elif len(_plain(purpose)) > 300:
        errors.append("Purpose of Certificate must be at most 300 characters")
    filename = ""
    if upload is not None and getattr(upload, "filename", ""):
        data = await upload.read()
        filename = upload.filename
        if len(data) > MAX_UPLOAD:
            errors.append("Supporting Document must be at most 2 MB")
        elif "B16" in FIXED and not re.search(r"\.(pdf|jpe?g|png)$", filename, re.I):  # B16: type not checked
            errors.append("Supporting Document must be a PDF, JPG or PNG file")
    if not address.strip():
        errors.append("Address is required")
    elif len(address) > 200:
        errors.append("Address must be at most 200 characters")
    if not declaration:
        errors.append("Please accept the declaration")
    if errors:
        return page("apply.html", request, status=422, errors=errors, done=None, v=v, docs=DOCS)
    app_id = next(_ids)
    APPS[app_id] = {**{k: v[k] for k in ("applicant_name", "mobile", "email", "pincode", "dob", "address")},
                    "id": app_id, "cert_type": cert_type, "status": "Submitted", "owner": request.session["u"],
                    "documents": docs, "purpose": _plain(purpose), "attachment": filename}
    if email:
        send_email(email, f"Application {app_id} received",
                   f"Dear {applicant_name},\n\nYour application {app_id} for a {cert_type} certificate has been "
                   f"received and is waiting for verification.\n\nDemo Certificate Portal")
    return page("apply.html", request, errors=[], done=app_id, v=EMPTY, docs=DOCS)


@app.get("/my-applications", response_class=HTMLResponse)
def mine(request: Request):
    denied = need(request, "citizen")
    if denied:
        return denied
    apps = [a for a in APPS.values() if a["owner"] == request.session["u"]]
    return page("mine.html", request, apps=apps)


@app.get("/clerk/queue", response_class=HTMLResponse)
def clerk_queue(request: Request):
    denied = need(request, "clerk")
    if denied:
        return denied
    apps = [a for a in APPS.values() if a["status"] == "Submitted"]
    return page("queue.html", request, heading="Verification Queue", apps=apps, action="/clerk/verify", verb=VERIFY)


@app.post("/clerk/verify/{app_id}")
def clerk_verify(request: Request, app_id: int):
    denied = need(request, "clerk")
    if denied:
        return denied
    if app_id in APPS and APPS[app_id]["status"] == "Submitted":
        APPS[app_id]["status"] = "Verified"
    return RedirectResponse("/clerk/queue", status_code=303)


@app.get("/officer/queue", response_class=HTMLResponse)
def officer_queue(request: Request):
    # B1: role check forgotten
    apps = [a for a in APPS.values() if a["status"] == "Verified"]
    return page("queue.html", request, heading="Approval Queue", apps=apps, action="/officer/approve", verb="Approve")


@app.post("/officer/approve/{app_id}")
def officer_approve(request: Request, app_id: int):
    denied = need(request, "officer")
    if denied:
        return denied
    if app_id in APPS and APPS[app_id]["status"] == "Verified":
        APPS[app_id]["status"] = "Approved"
    return RedirectResponse("/officer/queue", status_code=303)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    return need(request, "admin") or page("users.html", request)


@app.get("/admin/reports", response_class=HTMLResponse)
def admin_reports(request: Request):
    denied = need(request, "admin")
    if denied:
        return denied
    if "B4" in FIXED:
        counts = {st: sum(1 for a in APPS.values() if a["status"] == st) for st in ("Submitted", "Verified", "Approved")}
        rows = "".join(f"<tr><td>{k}</td><td>{n}</td></tr>" for k, n in counts.items())
        return HTMLResponse(env.from_string('{% extends "base.html" %}{% block title %}Reports{% endblock %}{% block body %}'
                                            '<h1>Reports</h1><table><tr><th>Status</th><th>Applications</th></tr>'
                                            + rows + '</table>{% endblock %}').render(user=user_of(request), visual=VISUAL))
    totals = {"Approved": 0}
    return HTMLResponse(str(1 / totals["Approved"]))  # B4: ZeroDivisionError -> 500


# ---- JSON API used by the screens ------------------------------------------------------

PUBLIC_FIELDS = ("id", "cert_type", "status")


def api_user(request: Request):
    u = user_of(request)
    if u is None:
        return None, JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return u, None


@app.get("/api/me")
def api_me(request: Request):
    u, err = api_user(request)
    return err or {"username": u["username"], "name": u["name"], "role": u["role"]}


@app.get("/api/my-applications")
def api_my_applications(request: Request):
    u, err = api_user(request)
    if err:
        return err
    if u["role"] != "citizen":
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return [{k: a[k] for k in PUBLIC_FIELDS} for a in APPS.values() if a["owner"] == u["username"]]


@app.get("/api/applications/{app_id}")
def api_application(request: Request, app_id: int):
    u, err = api_user(request)
    if err:
        return err
    a = APPS.get(app_id)
    if not a:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    # B11: no ownership check - any logged-in user can read any application
    return {k: v for k, v in a.items() if k != "owner"}


@app.get("/api/users")
def api_users(request: Request):
    u, err = api_user(request)
    if err:
        return err
    # B12: login is checked, the Administrator role is not
    return [{"username": k, "name": v["name"], "role": v["role"]} for k, v in USERS.items()]


@app.get("/applications/{app_id}", response_class=HTMLResponse)
def application_page(request: Request, app_id: int):
    return need(request) or page("details.html", request, app_id=app_id)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    return page("help.html", request)


@app.get("/help/faq", response_class=HTMLResponse)
def faq(request: Request):
    if "B5" not in FIXED:
        return page("notfound.html", request, status=404)  # B5: the Help page links to a page that does not exist
    return page("faq.html", request)


@app.get("/help/contact", response_class=HTMLResponse)
def contact(request: Request):
    return page("contact.html", request)


# ---- two portals over one back end ------------------------------------------------------

class PortalGate:
    """Serves one portal: its own pages only (others answer 404) and its own session cookie."""

    def __init__(self, inner, portal: str):
        self.inner, self.portal = inner, portal
        self.cookie = "dsession" if portal == "department" else "session"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        path = scope.get("path", "/")
        other = DEPT_ONLY if self.portal == "citizen" else CITIZEN_ONLY
        if any(path.startswith(x) for x in other) and not path.startswith("/test-support"):
            html = env.get_template("notfound.html").render(user=None, portal=self.portal, citizen_url=CITIZEN_URL,
                                                            dept_url=DEPT_URL, visual=VISUAL).encode()
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/html; charset=utf-8"), (b"content-length", str(len(html)).encode())]})
            return await send({"type": "http.response.body", "body": html})
        scope = dict(scope, portal=self.portal)
        if self.cookie != "session":
            headers = []
            for k, v in scope["headers"]:
                if k == b"cookie":
                    parts = [c.strip() for c in v.decode("latin-1").split(";") if c.strip()]
                    parts = [c for c in parts if not c.startswith("session=")]
                    parts = ["session=" + c.split("=", 1)[1] if c.startswith(self.cookie + "=") else c for c in parts]
                    v = "; ".join(parts).encode("latin-1")
                headers.append((k, v))
            scope["headers"] = headers

        async def send2(msg):
            if msg["type"] == "http.response.start" and self.cookie != "session":
                msg = dict(msg, headers=[(k, v.replace(b"session=", self.cookie.encode() + b"=", 1)
                                          if k.lower() == b"set-cookie" and v.startswith(b"session=") else v)
                                         for k, v in msg["headers"]])
            await send(msg)
        return await self.inner(scope, receive, send2)


citizen_portal = PortalGate(app, "citizen")
department_portal = PortalGate(app, "department")


# ---- test support (test environments only; not linked from any page) -------------------

@app.post("/test-support/reset", include_in_schema=False)
def test_reset(request: Request):
    if request.headers.get("x-test-key") != RESET_KEY:
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    global _ids
    APPS.clear()
    APPS.update(copy.deepcopy(SEED_APPS))
    _ids = count(1004)
    OTPS.clear()
    CLOCK["offset"] = 0.0
    return {"reset": True, "applications": len(APPS)}


@app.post("/test-support/clock", include_in_schema=False)
async def test_clock(request: Request):
    """Move the portal's clock forward (OTP expiry and idle-session tests without waiting)."""
    if request.headers.get("x-test-key") != RESET_KEY:
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    body = await request.json()
    CLOCK["offset"] += float(body.get("advance_s") or 0)
    return {"offset_s": CLOCK["offset"]}


@app.get("/test-support/otp", include_in_schema=False)
def test_otp(request: Request, user: str = ""):
    if request.headers.get("x-test-key") != RESET_KEY:
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    o = OTPS.get(user)
    return {"user": user, "otp": o["code"] if o else None}


@app.exception_handler(404)
async def not_found(request: Request, exc):  # noqa: ARG001
    return page("notfound.html", request, status=404)
