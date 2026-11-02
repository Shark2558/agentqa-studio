"""Shared helpers: text matching, test data generation, logging."""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from difflib import SequenceMatcher

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "by", "with", "be", "is", "are",
    "shall", "should", "must", "will", "can", "may", "able", "system", "user", "users", "page",
    "screen", "field", "fields", "all", "any", "their", "his", "her", "its", "this", "that", "as",
    "at", "from", "into", "only", "it", "who", "which", "via", "using", "use", "allow", "allowed",
    "provide", "provided", "option", "functionality", "feature", "access", "view", "see", "open",
    "portal", "application's", "within", "under", "over", "also", "new", "existing", "online",
    "me", "my", "your", "our", "please",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr, flush=True)


def norm(text: str | None) -> str:
    text = (text or "").replace("_", " ").replace("-", " ")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9 ]", " ", text)).strip().lower()


def stem(word: str) -> str:
    for suffix in ("ations", "ation", "ings", "ing", "ies", "es", "s", "ed"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            base = word[: -len(suffix)]
            return base + ("y" if suffix == "ies" else "")
    return word


def tokens(text: str | None, keep_stop: bool = False) -> set[str]:
    words = norm(text).split()
    return {stem(w) for w in words if keep_stop or (w not in STOPWORDS and len(w) > 1)}


def similarity(a: str | None, b: str | None) -> float:
    """0..1 similarity between two short labels (field names, titles)."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = tokens(na, keep_stop=True), tokens(nb, keep_stop=True)
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    return max(seq, jac)


def containment(needle: str | None, haystack: str | None) -> float:
    """Share of the needle's meaningful tokens that appear in the haystack."""
    tn, th = tokens(needle), tokens(haystack)
    if not tn:
        return 0.0
    return len(tn & th) / len(tn)


def path_pattern(path: str) -> str:
    """/application/123/view -> /application/{n}/view (to cap crawl explosion)."""
    path = re.sub(r"/\d+(?=/|$)", "/{n}", path)
    path = re.sub(r"/[0-9a-f]{8,}(?=/|$)", "/{id}", path)
    return re.sub(r"=\d+", "={n}", path)


# ---- test data -------------------------------------------------------------

def field_text(field: dict) -> str:
    return " ".join(str(field.get(k) or "") for k in ("label", "name", "id", "placeholder")).lower()


def guess_semantic(field: dict) -> str:
    """Best guess at what a form field holds, from its type, name and label."""
    ftype = (field.get("type") or "").lower()
    text = field_text(field)
    if ftype in ("email",) or "email" in text or "e mail" in text:
        return "email"
    if ftype == "tel" or any(k in text for k in ("mobile", "phone", "contact no", "contact number")):
        return "mobile"
    if any(k in text for k in ("pin code", "pincode", "pin_code", "postal", "zip")):
        return "pincode"
    if ftype == "date" or "date" in text or "dob" in text:
        return "date"
    if ftype == "number":
        return "number"
    if "aadhaar" in text or "aadhar" in text:
        return "aadhaar"
    if "pan" in text.split():
        return "pan"
    if "name" in text:
        return "name"
    if field.get("tag") == "textarea" or "address" in text:
        return "address"
    return "text"


def valid_value(field: dict, rules: list[dict] | None = None) -> str | None:
    """A value that should pass every known constraint on this field."""
    rules = rules or []
    tag = field.get("tag")
    ftype = (field.get("type") or "").lower()
    if tag == "select":
        opts = [o for o in field.get("options") or [] if (o.get("value") or "").strip()]
        return opts[0]["value"] if opts else None
    if ftype in ("checkbox", "radio"):
        return "on"
    if ftype == "file":
        types = next((r["value"].get("types") for r in rules if r["kind"] == "file_types" and r.get("value")), None)
        accept = [x.strip().lstrip(".").lower() for x in (field.get("accept") or "").split(",") if x.strip() and "/" not in x]
        ext = (types or accept or ["pdf"])[0].replace("jpeg", "jpg")
        return f"@file:document.{ext}" if (rules or field.get("required")) else None
    if ftype in ("hidden", "submit", "button", "image", "reset"):
        return None
    sem = guess_semantic(field)
    value = {
        "email": "qa.tester@example.com",
        "mobile": "9876543210",
        "pincode": "695001",
        "date": "1990-05-15",
        "number": "10",
        "aadhaar": "123412341234",
        "pan": "ABCDE1234F",
        "name": "Test User",
        "address": "12 Test Street, Test Nagar",
        "text": "Test value",
    }[sem]
    if ftype == "number":
        lo, hi = field.get("min"), field.get("max")
        for r in rules:
            if r["kind"] == "numeric_range":
                lo, hi = r["value"].get("min", lo), r["value"].get("max", hi)
        try:
            if lo not in (None, "") and hi not in (None, ""):
                value = str(int((float(lo) + float(hi)) // 2))
            elif lo not in (None, ""):
                value = str(int(float(lo)))
        except ValueError:
            pass
    # respect length limits from the app and the SRS
    max_len = _int(field.get("maxlength"))
    min_len = _int(field.get("minlength"))
    for r in rules:
        v = r.get("value") or {}
        if r["kind"] == "max_length":
            max_len = min(max_len or 10**6, int(v["max"]))
        if r["kind"] == "min_length":
            min_len = max(min_len or 0, int(v["min"]))
        if r["kind"] == "exact_length" and sem not in ("mobile", "pincode", "aadhaar"):
            value = ("Test" * 20)[: int(v["length"])]
    if min_len and len(value) < min_len and sem in ("name", "address", "text"):
        value = (value + " " + "x" * min_len)[:max(min_len, len(value))]
    if max_len and len(value) > max_len:
        value = value[:max_len]
    return value


def future_date(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _int(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s[:n] or "x"
