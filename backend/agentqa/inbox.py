"""Mock inbox for test environments: catches the OTP SMS and emails a portal sends.

Point the portal's SMS gateway and SMTP server (in the test environment only) at AgentQA:

  HTTP  http://<this computer>:8025/sms     POST {"to": "...", "text": "..."}  (form fields and GET also work)
        http://<this computer>:8025/email   POST {"to": "...", "subject": "...", "text": "..."}
  SMTP  <this computer>:2525                any message; nothing is relayed

Messages are kept in the project's .agentqa/inbox.db. Logins and tests read one-time passwords and
confirmation emails from here, so OTP steps run unattended. Other OTP sources (a fixed test OTP, a
test-only API of the portal, or a TOTP secret for authenticator-app logins) need no inbox at all.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import sqlite3
import struct
import threading
import time
from email import message_from_bytes, policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

SCHEMA = """CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, to_addr TEXT,
from_addr TEXT, subject TEXT, body TEXT, otp TEXT, received_at REAL)"""
OTP_WORDS = re.compile(r"\b(otp|one[- ]time|code|password|passcode|pin|verification code|verify)\b", re.I)
NOT_OTP = re.compile(r"\b(application|app|ref(erence)?|id|no\.?|number|order|ticket|receipt|txn|transaction|case|amount|rs\.?|inr)\s*[:#.-]?\s*$", re.I)


def extract_otp(text: str, pattern: str | None = None) -> str | None:
    """The one-time code in a message: a 4-8 digit number, preferring one close to 'OTP' or 'code'."""
    if not text:
        return None
    if pattern:
        m = re.search(pattern, text)
        return (m.group(1) if m and m.groups() else m.group(0)) if m else None
    nums = [(m.start(), m.group(1)) for m in re.finditer(r"(?<![\d.,/-])(\d{4,8})(?![\d.,/-]?\d)", text)]
    if not nums:
        return None
    # a number labelled as something else (application 1019, ref 7788, order no. 1234) is never the OTP
    nums = [(i, n) for i, n in nums if not NOT_OTP.search(text[max(0, i - 18):i])]
    if not nums:
        return None
    words = [m.start() for m in OTP_WORDS.finditer(text)]
    near = [(min(abs(i - w) for w in words), n) for i, n in nums] if words else []
    near = [x for x in near if x[0] <= 60]
    if near:
        return min(near)[1]
    # no "OTP" or "code" near it: only a short message with a single number counts ("482913 - Demo portal")
    return nums[0][1] if len(nums) == 1 and len(text) <= 60 else None


def norm_addr(addr: str | None) -> str:
    a = (addr or "").strip().lower()
    a = re.sub(r"^.*<([^>]+)>.*$", r"\1", a)
    digits = re.sub(r"\D", "", a)
    if "@" not in a and len(digits) >= 10:
        return digits[-10:]          # +91 98950 00001 and 9895000001 are the same mobile
    return a


class InboxStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self._db() as db:
            db.execute(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def add(self, kind: str, to: str, body: str, subject: str = "", sender: str = "") -> dict:
        row = {"kind": kind, "to_addr": norm_addr(to), "from_addr": sender or "", "subject": subject or "",
               "body": body or "", "otp": extract_otp(f"{subject}\n{body}"), "received_at": time.time()}
        with self.lock, self._db() as db:
            cur = db.execute("INSERT INTO messages (kind, to_addr, from_addr, subject, body, otp, received_at) "
                             "VALUES (:kind, :to_addr, :from_addr, :subject, :body, :otp, :received_at)", row)
            row["id"] = cur.lastrowid
        return row

    def list(self, to: str | None = None, kind: str | None = None, since: float | None = None, limit: int = 100) -> list[dict]:
        q, args = "SELECT * FROM messages WHERE 1=1", []
        if to:
            q += " AND to_addr=?"
            args.append(norm_addr(to))
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if since:
            q += " AND received_at>=?"
            args.append(float(since))
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._db() as db:
            return [dict(r) for r in db.execute(q, args)]

    def clear(self) -> None:
        with self.lock, self._db() as db:
            db.execute("DELETE FROM messages")


# ---------------------------------------------------------------------------
# HTTP and SMTP servers
# ---------------------------------------------------------------------------

def _handler(store: InboxStore):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, data) -> None:
            raw = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _params(self) -> dict:
            u = urlparse(self.path)
            out = {k: v[0] for k, v in parse_qs(u.query).items()}
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                raw = self.rfile.read(n)
                ctype = self.headers.get("Content-Type") or ""
                if "json" in ctype:
                    try:
                        out.update(json.loads(raw or b"{}"))
                    except ValueError:
                        pass
                else:
                    out.update({k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()})
            return out

        def _store(self, kind: str) -> None:
            p = self._params()
            to = p.get("to") or p.get("mobile") or p.get("number") or p.get("phone") or p.get("recipient") or ""
            text = p.get("text") or p.get("message") or p.get("body") or p.get("msg") or p.get("content") or ""
            if not to or not text:
                return self._send(400, {"error": "need 'to' and 'text'"})
            row = store.add(kind, str(to), str(text), str(p.get("subject") or ""), str(p.get("from") or ""))
            self._send(200, {"ok": True, "id": row["id"]})

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path == "/health":
                return self._send(200, {"ok": True, "service": "agentqa-inbox"})
            if u.path in ("/sms", "/email"):
                return self._store(u.path[1:])
            if u.path == "/messages":
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                return self._send(200, store.list(q.get("to"), q.get("kind"), float(q["since"]) if q.get("since") else None,
                                                   int(q.get("limit") or 100)))
            self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path in ("/sms", "/email"):
                return self._store(u.path[1:])
            self._send(404, {"error": "not found"})

        def do_DELETE(self):  # noqa: N802
            if urlparse(self.path).path == "/messages":
                store.clear()
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
    return H


class _SMTP(asyncio.Protocol):
    def __init__(self, store: InboxStore):
        self.store, self.buf, self.rcpt, self.sender, self.data = store, b"", [], "", None

    def connection_made(self, transport):
        self.t = transport
        self.t.write(b"220 agentqa-inbox ESMTP ready\r\n")

    def data_received(self, data: bytes):
        self.buf += data
        while True:
            if self.data is not None:
                end = self.buf.find(b"\r\n.\r\n")
                if end < 0:
                    return
                raw, self.buf = self.buf[:end], self.buf[end + 5:]
                raw = raw.replace(b"\r\n..", b"\r\n.")
                self._deliver(raw)
                self.data = None
                self.t.write(b"250 OK: stored\r\n")
                continue
            if b"\r\n" not in self.buf:
                return
            line, self.buf = self.buf.split(b"\r\n", 1)
            cmd = line.decode("utf-8", "replace").strip()
            up = cmd.upper()
            if up.startswith("EHLO"):
                self.t.write(b"250-agentqa-inbox\r\n250-SIZE 20000000\r\n250 8BITMIME\r\n")
            elif up.startswith("HELO"):
                self.t.write(b"250 agentqa-inbox\r\n")
            elif up.startswith("MAIL FROM"):
                self.sender, self.rcpt = cmd.split(":", 1)[1].split()[0].strip("<>") if ":" in cmd else "", []
                self.t.write(b"250 OK\r\n")
            elif up.startswith("RCPT TO"):
                self.rcpt.append(cmd.split(":", 1)[1].strip().split()[0].strip("<>"))
                self.t.write(b"250 OK\r\n")
            elif up == "DATA":
                self.data = b""
                self.t.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
            elif up in ("RSET", "NOOP"):
                self.rcpt = [] if up == "RSET" else self.rcpt
                self.t.write(b"250 OK\r\n")
            elif up == "QUIT":
                self.t.write(b"221 Bye\r\n")
                self.t.close()
                return
            else:
                self.t.write(b"502 Command not implemented\r\n")

    def _deliver(self, raw: bytes) -> None:
        msg = message_from_bytes(raw, policy=policy.default)
        part = msg.get_body(preferencelist=("plain", "html")) if msg.is_multipart() else msg
        try:
            body = part.get_content() if part is not None else ""
        except Exception:  # noqa: BLE001
            body = raw.decode("utf-8", "replace")
        if part is not None and part.get_content_type() == "text/html":
            body = re.sub(r"<[^>]+>", " ", body)
        for to in self.rcpt or [str(msg.get("To") or "")]:
            self.store.add("email", to, str(body).strip(), str(msg.get("Subject") or ""), self.sender or str(msg.get("From") or ""))


class InboxServer:
    """HTTP and SMTP listeners on background threads (ends with the process)."""

    def __init__(self, db_path: Path, host: str = "127.0.0.1", http_port: int = 8025, smtp_port: int | None = 2525):
        self.store = InboxStore(db_path)
        self.host, self.http_port, self.smtp_port = host, http_port, smtp_port

    def start(self) -> "InboxServer":
        self.httpd = ThreadingHTTPServer((self.host, self.http_port), _handler(self.store))
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="inbox-http").start()
        if self.smtp_port:
            ready = threading.Event()
            self.smtp_error = None

            def run():
                loop = asyncio.new_event_loop()
                try:
                    srv = loop.run_until_complete(loop.create_server(lambda: _SMTP(self.store), self.host, self.smtp_port))
                    self.smtp_server = srv
                except OSError as exc:
                    self.smtp_error = exc
                    ready.set()
                    return
                ready.set()
                loop.run_forever()
            threading.Thread(target=run, daemon=True, name="inbox-smtp").start()
            ready.wait(5)
        return self

    def stop(self) -> None:
        self.httpd.shutdown()


# ---------------------------------------------------------------------------
# Client side: used by logins (agents) and by generated tests
# ---------------------------------------------------------------------------

class InboxClient:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def alive(self) -> bool:
        try:
            return httpx.get(f"{self.url}/health", timeout=1).status_code == 200
        except httpx.HTTPError:
            return False

    def messages(self, to: str | None = None, kind: str | None = None, since: float | None = None) -> list[dict]:
        params = {k: v for k, v in {"to": to, "kind": kind, "since": since}.items() if v}
        return httpx.get(f"{self.url}/messages", params=params, timeout=5).json()

    def wait(self, to: str, since: float, kind: str | None = None, timeout: float = 25,
             subject_contains: str | None = None) -> dict | None:
        end = time.time() + timeout
        while time.time() < end:
            for m in self.messages(to=to, kind=kind, since=since):
                if subject_contains and subject_contains.lower() not in (m["subject"] + " " + m["body"]).lower():
                    continue
                return m
            time.sleep(0.4)
        return None

    def wait_otp(self, to: str, since: float, timeout: float = 25, pattern: str | None = None) -> str | None:
        end = time.time() + timeout
        while time.time() < end:
            for m in self.messages(to=to, since=since):
                code = extract_otp(f"{m['subject']}\n{m['body']}", pattern) if pattern else m.get("otp")
                if code:
                    return code
            time.sleep(0.4)
        return None


_SERVERS: dict[int, InboxServer] = {}


def settings(cfg: dict) -> dict:
    ib = cfg.get("inbox") or {}
    return {"host": ib.get("host", "127.0.0.1"), "http_port": int(ib.get("http_port", 8025)),
            "smtp_port": ib.get("smtp_port", 2525), "url": ib.get("url")}


def client_url(cfg: dict) -> str:
    s = settings(cfg)
    host = "127.0.0.1" if s["host"] in ("0.0.0.0", "") else s["host"]
    return s["url"] or f"http://{host}:{s['http_port']}"


def ensure(project) -> InboxClient | None:
    """Make sure an inbox is listening (start one in this process if not) and return a client for it."""
    s = settings(project.cfg)
    client = InboxClient(client_url(project.cfg))
    if client.alive():
        return client
    if s["url"]:
        return client                     # an external inbox is configured; nothing to start here
    if s["http_port"] not in _SERVERS:
        try:
            _SERVERS[s["http_port"]] = InboxServer(project.state / "inbox.db", s["host"], s["http_port"],
                                                   int(s["smtp_port"]) if s["smtp_port"] else None).start()
        except OSError:
            return client
    return client


def needed(project) -> bool:
    """True when some role's OTP comes from the mock inbox (or the inbox is switched on for emails)."""
    lg = project.cfg.get("login") or {}
    default = (lg.get("otp") or {}).get("source")
    for r in list(project.roles()) + project.peers():
        if (project.account(r).get("otp_source") or default) == "inbox":
            return True
    return bool((project.cfg.get("inbox") or {}).get("enabled"))


# ---------------------------------------------------------------------------
# One-time passwords for logins
# ---------------------------------------------------------------------------

def totp(secret_b32: str, at: float | None = None, digits: int = 6, step: int = 30) -> str:
    key = base64.b32decode(secret_b32.replace(" ", "").upper() + "=" * (-len(secret_b32.replace(" ", "")) % 8))
    counter = int((at or time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def get_otp(project, role: str, since: float) -> str:
    """The OTP for a login that started at `since`, from the configured source."""
    import os
    otp = (project.cfg.get("login") or {}).get("otp") or {}
    acc = project.account(role)
    source = acc.get("otp_source") or otp.get("source", "inbox")
    if source == "fixed":
        value = acc.get("otp_fixed") or otp.get("fixed")
        if not value:
            raise RuntimeError("login.otp.source is 'fixed' but no 'fixed' OTP is set")
        return str(value)
    if source == "totp":
        env = acc.get("totp_secret_env") or otp.get("totp_secret_env")
        secret = os.environ.get(env or "") or acc.get("totp_secret")
        if not secret:
            raise RuntimeError(f"Set the {env or 'totp_secret_env'} environment variable to {role}'s TOTP secret")
        return totp(secret)
    if source == "api":
        api = otp.get("api") or {}
        url = project.url(str(api.get("url", "")).format(username=acc.get("username", ""), mobile=acc.get("mobile", ""),
                                                         email=acc.get("email", ""), role=role))
        end = time.time() + float(otp.get("timeout_s", 25))
        while time.time() < end:
            r = httpx.get(url, headers=api.get("headers") or {}, timeout=10)
            data = r.json()
            for part in str(api.get("json_path", "otp")).split("."):
                data = data.get(part) if isinstance(data, dict) else None
            if data:
                return str(data)
            time.sleep(0.5)
        raise RuntimeError(f"The OTP API {url} returned no code")
    to = acc.get("mobile") or acc.get("email") or acc.get("username")
    client = ensure(project)
    code = client.wait_otp(str(to), since - 2, timeout=float(otp.get("timeout_s", 25)), pattern=otp.get("pattern")) \
        if client else None
    if not code:
        raise RuntimeError(f"No OTP reached the mock inbox for {role} ({to}) within {otp.get('timeout_s', 25)} s. "
                           f"Point the portal's SMS gateway or SMTP at {client_url(project.cfg)} (see README: OTP).")
    return code
