"""The project's monthly AI budget: spent so far, the cap, and whether cloud calls may still go out.

States: ok · warning (the alert percentage is reached) · capped (the cap is reached: Cloud mode drops to No AI,
Hybrid keeps the free local model). The owner is told once per state per month — a `meta` note in the project
store remembers which alerts went out, and the live view gets an `ai` / `cost` event.
"""
from __future__ import annotations

import threading

from agentqa import live
from agentqa.ai import usage as U
from agentqa.ai.settings import AiSettings

META_KEY = "ai_budget_alerts"
_ALERT_LOCK = threading.Lock()      # one alert per state per month across this process's workers


def status(store, settings: AiSettings, month: str | None = None) -> dict:
    month = month or U.month_key()
    spent = U.month_total(store, month)
    cap = float(settings.monthly_usd)
    pct = int(min(100, spent / cap * 100)) if cap > 0 else 100          # a floor: 100 means the cap is reached
    state = "capped" if spent >= cap else ("warning" if pct >= settings.alert_at_pct else "ok")
    return {"month": month, "spent": round(spent, 6), "cap": cap, "pct": pct, "alert_at_pct": settings.alert_at_pct,
            "state": state}


def reason(st: dict) -> str:
    """Plain English for the live view and the effective table."""
    if st["state"] == "capped":
        return (f"the monthly AI budget (${st['cap']:.2f}) is used up: cloud AI is off for this project until "
                f"next month, or until the cap is raised")
    if st["state"] == "warning":
        return f"{st['pct']} % of the monthly AI budget (${st['cap']:.2f}) is used"
    return f"${st['spent']:.2f} of ${st['cap']:.2f} used this month"


def check(store, settings: AiSettings, *, project: str = "", month: str | None = None) -> dict:
    """The status, plus one alert (meta + live event) the first time a month reaches warning or capped.
    Projects with AI off still get the figure but never an alert: nothing is being spent."""
    st = status(store, settings, month)
    if st["state"] == "ok" or not settings.enabled():
        return st
    with _ALERT_LOCK:
        sent = store.get_meta(META_KEY) or {}
        done = list(sent.get(st["month"]) or [])
        if st["state"] in done:
            return st
        store.set_meta(META_KEY, {**sent, st["month"]: done + [st["state"]]})
    who = f"{project}: " if project else ""
    live.emit("ai", "cost", f"{who}{reason(st)}", state=st["state"], spent=st["spent"], cap=st["cap"], pct=st["pct"],
              month=st["month"])
    return st
