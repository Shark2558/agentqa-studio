"""The Anthropic adapter speaks through the official SDK but keeps the gateway's contract: models(), chat(), and
ProviderError kinds the router already understands. Checked against the local stand-in and a request-capturing
server, so no real key is needed here (M0.3 adds the real-provider run on top)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import free_port

from agentqa.ai import providers as P
from demo import mock_ai

MODEL = "claude-sonnet-5-5"
ASK = ("Reply with JSON only.", 'Return {"ok": true}')


def key(base: str, secret: str = "sk-ant-good-000000000000003") -> dict:
    return {"provider": "anthropic", "label": "Claude", "key": secret, "base_url": base + "/anthropic/v1", "model": MODEL}


@pytest.fixture
def stand_in():
    port = free_port()
    srv = mock_ai.serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()


class _Capture(BaseHTTPRequestHandler):
    """Records every Messages request (body and headers) and answers according to `mode`:
    ok · reject_newer (400 naming output_config) · reject_model_text (400 "not supported for this model") ·
    no_credit (Anthropic's 400 when the credit runs out) · garbage (200 text/html) · truncated (stop_reason
    max_tokens) · refusal."""
    bodies: list[dict] = []
    headers_seen: list[dict] = []
    mode = "ok"

    def log_message(self, *a):
        pass

    def _send(self, code: int, obj: dict | None = None, raw: bytes | None = None, ctype: str = "application/json") -> None:
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, message: str) -> None:
        self._send(400, {"type": "error", "error": {"type": "invalid_request_error", "message": message}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        _Capture.bodies.append(body)
        _Capture.headers_seen.append({k.lower(): v for k, v in self.headers.items()})
        newer = "output_config" in body or "fallbacks" in body
        if _Capture.mode == "reject_newer" and newer:
            return self._error("output_config: Extra inputs are not permitted")
        if _Capture.mode == "reject_model_text" and newer:
            return self._error("fallbacks is not supported for this model")
        if _Capture.mode == "no_credit":
            return self._error(mock_ai.ANTHROPIC_NO_CREDIT)
        if _Capture.mode == "garbage":
            return self._send(200, raw=b"<html>proxy says hi</html>", ctype="text/html")
        stop = {"truncated": "max_tokens", "refusal": "refusal"}.get(_Capture.mode, "end_turn")
        text = '{"ok": tr' if stop == "max_tokens" else '{"ok": true}'
        answer = {"id": "msg_test", "type": "message", "role": "assistant", "model": body.get("model"),
                  "content": [{"type": "text", "text": text}], "stop_reason": stop, "stop_sequence": None,
                  "usage": {"input_tokens": 5, "output_tokens": 3}}
        if stop == "refusal":
            answer["stop_details"] = {"type": "refusal", "category": "cyber", "explanation": ""}
        self._send(200, answer)


@pytest.fixture
def capture():
    _Capture.bodies, _Capture.headers_seen, _Capture.mode = [], [], "ok"
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Capture)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()


def capture_adapter(base: str) -> P.Adapter:
    return P.adapter({**key(base), "base_url": base + "/v1"}, timeout=5)


def test_client_strips_the_v1_suffix_and_leaves_retries_to_the_router(stand_in):
    # Arrange
    adapter = P.adapter(key(stand_in), timeout=5)

    # Act
    client = adapter.client()

    # Assert: the SDK appends /v1 itself; retries, cool-downs and failover belong to the gateway router
    assert isinstance(adapter, P.AnthropicAdapter)
    assert str(client.base_url).rstrip("/") == stand_in + "/anthropic"
    assert client.max_retries == 0


def test_models_and_chat_work_against_the_stand_in(stand_in):
    adapter = P.adapter(key(stand_in), timeout=5)
    assert MODEL in adapter.models()
    text = adapter.chat(MODEL, *ASK, 30, None)
    assert P.parse_json(text) == {"ok": True, "served_by": "000003", "model": MODEL}


def test_a_rate_limit_keeps_its_retry_after(stand_in):
    with pytest.raises(P.ProviderError) as limited:
        P.adapter(key(stand_in, "sk-ant-ratelimit-000000000001"), timeout=5).chat(MODEL, *ASK, 30, None)
    assert (limited.value.kind, limited.value.status, limited.value.retry_after) == ("rate_limit", 429, 30)


def test_a_rejected_key_is_dead_not_retried(stand_in):
    with pytest.raises(P.ProviderError) as rejected:
        P.adapter(key(stand_in, "sk-ant-invalid-000000000002"), timeout=5).chat(MODEL, *ASK, 30, None)
    assert rejected.value.kind == "invalid_key"


def test_an_unreachable_host_is_a_connection_error():
    with pytest.raises(P.ProviderError) as unreachable:
        P.adapter(key("http://127.0.0.1:9", "sk-ant-x"), timeout=2).chat(MODEL, *ASK, 30, None)
    assert unreachable.value.kind in ("connection", "timeout")   # Windows reports a closed loopback port as a timeout


def test_request_shape_follows_the_current_messages_api(capture):
    # Arrange
    adapter = capture_adapter(capture)

    # Act
    adapter.chat(MODEL, "system text", "user text", 30, b"\xff\xd8not-really-a-jpeg")
    body, headers = _Capture.bodies[-1], _Capture.headers_seen[-1]

    # Assert: no sampling parameters, room for adaptive thinking, image as a base64 block, refusal fallback on
    assert "temperature" not in body and "top_p" not in body
    assert body["max_tokens"] >= P.AnthropicAdapter.MIN_TOKENS
    assert body["system"] == "system text"
    assert body["fallbacks"] == "default" and body["output_config"] == {"effort": P.AnthropicAdapter.EFFORT}
    assert P.AnthropicAdapter.FALLBACK_BETA in headers.get("anthropic-beta", "")
    blocks = body["messages"][0]["content"]
    assert blocks[0]["type"] == "text" and blocks[0]["text"].startswith("user text")
    assert blocks[1]["type"] == "image" and blocks[1]["source"]["media_type"] == "image/jpeg"


def test_token_usage_is_kept_for_the_cost_record(capture):
    adapter = capture_adapter(capture)

    adapter.chat(MODEL, *ASK, 30, None)

    assert adapter.last_usage == {"input_tokens": 5, "output_tokens": 3}


@pytest.mark.parametrize("mode", ["reject_newer", "reject_model_text"])
def test_a_model_that_rejects_the_newer_fields_gets_a_plain_retry(capture, mode):
    # Arrange: the 400 may name the field directly, or say "... not supported for this model"
    _Capture.mode = mode
    adapter = capture_adapter(capture)

    # Act
    text = adapter.chat(MODEL, *ASK, 30, None)

    # Assert
    assert P.parse_json(text) == {"ok": True}
    first, second = _Capture.bodies
    assert "output_config" in first and "fallbacks" in first
    assert "output_config" not in second and "fallbacks" not in second


def test_an_empty_credit_is_billing_after_one_request_with_no_plain_retry(capture):
    _Capture.mode = "no_credit"

    with pytest.raises(P.ProviderError) as broke:
        capture_adapter(capture).chat(MODEL, *ASK, 30, None)

    assert (broke.value.kind, broke.value.status) == ("billing", 400)
    assert len(_Capture.bodies) == 1


def test_a_refusal_is_an_error_not_an_answer(capture):
    _Capture.mode = "refusal"

    with pytest.raises(P.ProviderError) as refused:
        capture_adapter(capture).chat(MODEL, *ASK, 30, None)

    assert refused.value.kind == "bad_request" and "cyber" in str(refused.value)


def test_an_answer_cut_off_at_max_tokens_is_bad_output_not_a_half_answer(capture):
    _Capture.mode = "truncated"

    with pytest.raises(P.ProviderError) as cut:
        capture_adapter(capture).chat(MODEL, *ASK, 30, None)

    assert cut.value.kind == "bad_output" and "max_tokens" in str(cut.value)


def test_a_non_json_200_from_a_proxy_is_a_provider_error_not_a_crash(capture):
    _Capture.mode = "garbage"

    with pytest.raises(P.ProviderError) as garbage:
        capture_adapter(capture).chat(MODEL, *ASK, 30, None)

    assert garbage.value.kind in ("bad_output", "unavailable")


def test_auto_prefers_the_current_claude_generation():
    adapter = P.adapter(key("http://127.0.0.1:9"), timeout=1)
    names = ["claude-3-5-haiku-20241022", "claude-opus-5-5", "claude-sonnet-4-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    assert adapter.pick(names) == "claude-sonnet-5-5"
    assert adapter.pick(["claude-haiku-5-5", "claude-opus-5-5"]) == "claude-haiku-5-5"
    assert adapter.pick(["claude-sonnet-4-5"]) == "claude-sonnet-4-5"
