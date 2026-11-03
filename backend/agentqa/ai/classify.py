"""What a provider's HTTP error means for the router: one failure kind (providers.KINDS names them; providers.DEAD,
COOL and RETRY_SAME say what the router does with each). Pure: no SDK, no I/O.

A 400 is `billing` only when that provider's own error fields say the account cannot pay (Anthropic's answer when
the credit ran out, 4 Nov 2026; plan m1-3-ai-switch-and-credit). A self-hosted server can echo the prompt inside a
400, and the application under test may well say "your credit balance is too low" or "insufficient funds" itself,
so those words anywhere else in the body never count.
"""
from __future__ import annotations

import json
import re

ERROR_BODY_CHARS = 600            # the adapters keep this much of an error body; nothing longer is parsed
OPENAI_BILLING_CODES = frozenset({"billing_hard_limit_reached", "billing_not_active", "insufficient_quota"})


def _error_object(text: str) -> dict:
    """The `error` object of a JSON error body, or {} when the body is not one."""
    try:
        data = json.loads((text or "")[:ERROR_BODY_CHARS])
    except (ValueError, RecursionError):
        return {}
    err = data.get("error") if isinstance(data, dict) else None
    return err if isinstance(err, dict) else {}


def _cannot_pay(provider: str, text: str) -> bool:
    """Whether a 400 from `provider` says, in its own error fields, that the account cannot pay."""
    err = _error_object(text)
    message = str(err.get("message") or "").lower()
    if provider == "anthropic":
        return err.get("type") == "billing_error" or message.startswith("your credit balance is too low")
    if provider == "openai":
        return bool({str(err.get("code") or ""), str(err.get("type") or "")} & OPENAI_BILLING_CODES)
    if provider == "gemini":
        return err.get("status") == "FAILED_PRECONDITION" and "enable billing" in message
    return False


def classify(status: int | None, text: str, provider: str = "") -> str:
    """The failure kind of one HTTP error. `provider` (the key's catalog id) turns on the credit rule for that
    provider's 400s; without it, as from an older caller, a 400 is never `billing`."""
    t = (text or "").lower()
    if status == 429:
        if re.search(r"insufficient_quota|billing|credit balance|payment|plan and billing", t):
            return "billing"
        if re.search(r"quota|per day|daily|resource_exhausted.*quota|exceeded your current", t):
            return "quota"
        return "rate_limit"
    if status in (401,):
        return "invalid_key"
    if status == 403:
        return "billing" if re.search(r"billing|credit|payment", t) else "invalid_key"
    if status == 402 or (status == 400 and _cannot_pay(provider, text)):
        return "billing"
    if status in (400, 404, 422) and re.search(r"model", t) and re.search(
            r"not found|does not exist|not supported|decommissioned|invalid model|unknown model|no such model|not available"
            r"|deprecated|is not a valid model", t):
        return "model"
    if status == 404:
        return "model" if "model" in t else "bad_request"
    if status in (400, 413, 422):
        return "bad_request"
    if status in (408, 500, 502, 503, 504, 520, 522, 524, 529):
        return "unavailable"
    return "unavailable" if (status or 0) >= 500 else "bad_request"
