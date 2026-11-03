"""Preflight for a new project: is the address reachable, and does it show a login page? One short GET; the page
itself is never returned, only the verdict and a plain-English fix when something is wrong.

Redirects are followed by hand so that every hop's host is checked: private LANs and loopback stay allowed
(owners test internal UAT sites), link-local / cloud-metadata / multicast addresses never are."""
from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

TIMEOUT_S = 6.0            # per socket operation
DEADLINE_S = 10.0          # for the whole check, redirects included
MAX_REDIRECTS = 5
MAX_BYTES = 256 * 1024
HOST_RE = re.compile(r"^(\[[0-9a-fA-F:.]+\]|[A-Za-z0-9._-]+)(:\d{1,5})?$")
BLOCKED_HOSTS = {"169.254.169.254", "100.100.100.200", "metadata.google.internal", "fd00:ec2::254"}
PASSWORD_BOX = re.compile(r"<input[^>]+type\s*=\s*['\"]?password", re.I)
LOGIN_LINK = re.compile(r"<a[^>]+href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(?:(?!</a>).)*?\b(log\s*in|sign\s*in|login)\b", re.I | re.S)
# Portals built as apps often use a button (with a data-* address or none) instead of a link
LOGIN_BUTTON = re.compile(r"<button\b([^>]*)>(?:(?!</button>).)*?\b(log\s*in|sign\s*in|login)\b", re.I | re.S)
URL_ATTR = re.compile(r"(?:href|data-\w+|formaction)\s*=\s*['\"]([^'\"]*(?:login|signin|sign-in|auth)[^'\"]*)['\"]", re.I)
FIXES = {
    "dns": "That name does not resolve. Check the spelling of the address, or whether it needs your office network or VPN.",
    "refused": "The site refused the connection. Is the application running, and is the port right?",
    "timeout": "No answer within ten seconds. The site may be down, slow, or only reachable from inside your network.",
    "tls": "The site's certificate is not trusted from here. Ask the team for the public address, or use http:// for a test server.",
    "redirects": "The address keeps redirecting. Open it in a browser and copy the final address.",
    "forbidden": "The site answered 403 Forbidden. AgentQA's address may need to be allowed by the firewall or WAF.",
    "notfound": "The site answered 404. Check the path, or use the home page address.",
    "server": "The site answered with a server error. Try again in a minute; if it stays, the environment is down.",
    "auth": "The site asks for HTTP authentication before showing anything. Add that account in the Accounts step.",
    "blocked": "That address belongs to the machine's own network plumbing (link-local or cloud metadata) and cannot be a test site.",
    "address": "That is not a valid web address. It should look like https://uat.example.gov.in, with no spaces.",
    "unreadable": "The site answered, but not in a way a browser would understand. Open it in a browser to check it is a web application.",
}


class Blocked(ValueError):
    """An address AgentQA must never fetch."""


def validate(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        str(httpx.URL(url.strip()))
    except (httpx.InvalidURL, UnicodeError, ValueError) as exc:          # "Invalid IPv6 URL" and friends
        raise ValueError(FIXES["address"]) from exc
    if parts.scheme not in ("http", "https") or not parts.netloc or not HOST_RE.match(parts.netloc) or ".." in parts.netloc:
        raise ValueError(FIXES["address"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def check_base_url(url: str) -> str:
    """A provider address the owner typed: http(s) only, a real host, never link-local or cloud metadata. Returns the
    cleaned address or raises ValueError with the plain-English fix. One choke point for the API and the old form."""
    clean = validate(url)
    try:
        check_host(clean)
    except Blocked as exc:
        raise ValueError(FIXES["blocked"]) from exc
    except httpx.HTTPError as exc:
        raise ValueError(FIXES["dns"]) from exc
    return clean.rstrip("/")


def check_host(url: str) -> None:
    """Blocked for link-local, multicast, unspecified, reserved and the well-known metadata addresses."""
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        raise ValueError(FIXES["address"])
    if host in BLOCKED_HOSTS:
        raise Blocked(host)
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise httpx.ConnectError(f"getaddrinfo failed for {host}") from exc
    for a in addresses:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved or str(ip) in BLOCKED_HOSTS:
            raise Blocked(host)


def _classify(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, httpx.TooManyRedirects):
        return "redirects"
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout, httpx.WriteTimeout)):
        return "timeout"
    if isinstance(exc, ssl.SSLError) or "certificate" in text or "ssl" in text or "tls" in text:
        return "tls"
    if "getaddrinfo" in text or "name or service" in text or "nodename" in text or "11001" in text:
        return "dns"
    if "refused" in text or "10061" in text:
        return "refused"
    if isinstance(exc, httpx.ConnectError):
        return "timeout"
    return "unreadable"


def _login(html: str, final_url: str) -> tuple[bool, str | None]:
    if PASSWORD_BOX.search(html):
        return True, urlsplit(final_url).path or "/"
    m = LOGIN_LINK.search(html)
    if m:
        href = m.group(1)
        return True, href if href.startswith("/") else urlsplit(href).path or href
    buttons = list(LOGIN_BUTTON.finditer(html))
    for b in buttons:                                  # prefer a login button that says where it goes
        attr = URL_ATTR.search(b.group(1))
        if attr:
            target = attr.group(1)
            return True, target if target.startswith("/") else urlsplit(target).path or None
    return bool(buttons), None


def _limited(chunks, started: float):
    """At most MAX_BYTES, and never past the deadline (a slow drip is a timeout, not a hang)."""
    seen = 0
    for chunk in chunks:
        if time.monotonic() - started > DEADLINE_S:
            raise httpx.ReadTimeout("the whole check took longer than the deadline")
        seen += len(chunk)
        yield chunk[: max(0, MAX_BYTES - (seen - len(chunk)))]
        if seen >= MAX_BYTES:
            return


def _fetch(url: str, started: float) -> tuple[int, str, bytes]:
    """GET with redirects followed by hand (each hop host-checked and deadline-checked)."""
    with httpx.Client(follow_redirects=False, timeout=TIMEOUT_S, headers={"User-Agent": "AgentQA-Studio preflight"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_host(url)
            if time.monotonic() - started > DEADLINE_S:
                raise httpx.ReadTimeout("deadline")
            with client.stream("GET", url) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = validate(urljoin(url, r.headers["location"]))
                    continue
                return r.status_code, str(r.url), b"".join(_limited(r.iter_bytes(), started))
    raise httpx.TooManyRedirects("too many redirects")


def _verdict(reachable: bool, fix: str | None, status=None, final_url=None, login=(False, None)) -> dict:
    return {"reachable": reachable, "status": status, "final_url": final_url, "login_detected": login[0],
            "login_url": login[1], "fix": fix}


def check(url: str) -> dict:
    """{"reachable", "status", "final_url", "login_detected", "login_url", "fix"}; ValueError for a non-web address."""
    url = validate(url)
    started = time.monotonic()
    try:
        status, final_url, body = _fetch(url, started)
    except Blocked:
        return _verdict(False, FIXES["blocked"])
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, UnicodeError) as exc:
        return _verdict(False, FIXES["address"] if isinstance(exc, (ValueError, UnicodeError)) and not isinstance(exc, httpx.HTTPError)
                        else FIXES[_classify(exc)])
    html = body.decode("utf-8", errors="replace")
    fix = (FIXES["auth"] if status == 401 else FIXES["forbidden"] if status == 403 else FIXES["notfound"] if status == 404
           else FIXES["server"] if status >= 500 else None)
    return _verdict(True, fix, status, final_url, _login(html, final_url))
