"""What the real Ollama taught the M1.2 acceptance (3 Nov 2026, qwen3:4b on a 4 GB GPU): the toy connection-test
prompt 'Return {"ok": true}' makes the small model emit junk and loop, and a looping model answers HTTP 500
"prediction aborted, token repeat limit reached", which must not cool the key down as if the server were out."""
from __future__ import annotations

import pytest

from agentqa.ai import providers as P

KEY = {"id": "k-ollama", "provider": "ollama", "label": "Ollama", "key": "", "base_url": "http://127.0.0.1:11434",
       "model": "qwen3:4b", "status": "active", "priority": 10}


def test_the_connection_test_asks_a_question_a_small_model_can_answer(monkeypatch):
    seen: dict = {}

    def fake_chat(self, model, system, user, max_tokens, image):
        seen.update(model=model, system=system, user=user, max_tokens=max_tokens)
        return '{"ok": true}'

    monkeypatch.setattr(P.OllamaAdapter, "models", lambda self: ["qwen3:4b"])
    monkeypatch.setattr(P.OllamaAdapter, "chat", fake_chat)
    res = P.test_key(KEY)
    assert res["ok"] and res["model"] == "qwen3:4b"
    assert "reachable" in seen["user"] and '{"ok": true}' in seen["user"]     # a question with the answer in it
    assert "one JSON object" in seen["system"] and seen["max_tokens"] >= 30


def test_a_prediction_abort_from_ollama_is_a_bad_answer_not_an_outage(monkeypatch):
    def fake_send(self, method, url, **kw):
        raise P.ProviderError("unavailable", 'HTTP 500: {"error":"prediction aborted, token repeat limit reached"}', 500)

    monkeypatch.setattr(P.OllamaAdapter, "_send", fake_send)
    with pytest.raises(P.ProviderError) as exc:
        P.OllamaAdapter(KEY, 30).chat("qwen3:4b", "sys", "user", 50, None)
    assert exc.value.kind == "bad_output"


def test_other_ollama_outages_still_count_as_unavailable(monkeypatch):
    def fake_send(self, method, url, **kw):
        raise P.ProviderError("unavailable", "HTTP 503: loading model", 503)

    monkeypatch.setattr(P.OllamaAdapter, "_send", fake_send)
    with pytest.raises(P.ProviderError) as exc:
        P.OllamaAdapter(KEY, 30).chat("qwen3:4b", "sys", "user", 50, None)
    assert exc.value.kind == "unavailable"
