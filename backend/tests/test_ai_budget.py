"""M1.2 slice 3: the monthly budget — warning at the alert percentage, capped at the cap, one alert per state per
month (meta + a live event), month rollover resets. The client-level checks (no request reaches the stand-in at the
cap, hybrid keeps answering locally) live in test_ai_client.py."""
from __future__ import annotations

import json

import pytest

from agentqa import live
from agentqa.ai import budget as B
from agentqa.ai import usage as U
from agentqa.ai.settings import AiSettings
from agentqa.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "agentqa.db")


@pytest.fixture
def events(tmp_path, monkeypatch):
    """Live events written during the test, read back as dicts."""
    folder = tmp_path / "live"
    monkeypatch.setenv("AGENTQA_LIVE_DIR", str(folder))
    monkeypatch.setattr(live, "_LIVE", None)
    yield lambda: [json.loads(ln) for ln in (folder / "events-main.jsonl").read_text(encoding="utf-8").splitlines()] \
        if (folder / "events-main.jsonl").exists() else []
    monkeypatch.setattr(live, "_LIVE", None)


def spend(store, usd: float, at: str | None = None, agent: str = "casegen") -> None:
    """One cloud call that cost `usd` (prices: $1 in / $1 out per token for a made-up model, so tokens = dollars)."""
    row = {"provider": "openai", "label": "k", "key_id": "k", "model": "unit-price-model", "scope": "cloud", "tier": "cheap",
           "task": agent, "ms": 1, "input_tokens": int(round(usd * 1_000_000)), "output_tokens": 0}
    if at:
        row["at"] = at
    U.record(store, row, agent=agent, pipeline="P-1", prices={"openai": {"unit-price-model": [1.0, 1.0]}})


SETTINGS = AiSettings(mode="cloud", send_text=True, monthly_usd=10.0, alert_at_pct=80)


def test_status_is_ok_then_warning_then_capped(store):
    assert B.status(store, SETTINGS)["state"] == "ok"
    spend(store, 7.9)
    s = B.status(store, SETTINGS)
    assert s["state"] == "ok" and s["spent"] == pytest.approx(7.9) and s["cap"] == 10.0 and s["pct"] == 79
    spend(store, 0.1)
    assert B.status(store, SETTINGS)["state"] == "warning"                   # 80 % reached
    spend(store, 2.0)
    s = B.status(store, SETTINGS)
    assert s["state"] == "capped" and s["pct"] == 100 and "used up" in B.reason(s)


def test_pct_is_a_floor_so_100_means_capped(store):
    spend(store, 9.96)
    s = B.status(store, SETTINGS)
    assert s["state"] == "warning" and s["pct"] == 99


def test_one_alert_per_state_per_month(store, events):
    spend(store, 8.5)
    B.check(store, SETTINGS, project="Demo")
    B.check(store, SETTINGS, project="Demo")
    spend(store, 2.0)
    B.check(store, SETTINGS, project="Demo")
    B.check(store, SETTINGS, project="Demo")
    ev = [e for e in events() if e["agent"] == "ai" and e["kind"] == "cost"]
    assert [e["state"] for e in ev] == ["warning", "capped"]
    assert ev[1]["spent"] == pytest.approx(10.5) and ev[1]["cap"] == 10.0 and "Demo" in ev[1]["title"]
    assert store.get_meta(B.META_KEY) == {U.month_key(): ["warning", "capped"]}


def test_a_new_month_resets_the_alerts_and_the_spend(store, events):
    spend(store, 12.0, at="2026-09-02T09:00:00")
    assert B.check(store, SETTINGS, month="2026-09")["state"] == "capped"
    assert B.check(store, SETTINGS)["state"] == "ok"                          # this month: nothing spent yet
    spend(store, 12.0)
    assert B.check(store, SETTINGS)["state"] == "capped"
    assert [e["state"] for e in events() if e["kind"] == "cost"] == ["capped", "capped"]   # once per month each


def test_no_ai_modes_never_alert(store, events):
    spend(store, 50.0)
    off = AiSettings(mode="none", monthly_usd=10.0)
    assert B.check(store, off)["state"] == "capped" and events() == []       # the figure is shown, nobody is alerted
