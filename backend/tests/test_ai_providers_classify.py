"""C5 (M1.3 Phase C): an account out of credit is `billing`, so the router stops asking that key until it is edited or
re-tested; every other 400 keeps its kind. The Anthropic body is the one the owner's Cloud run got on 4 Nov 2026.
Only the provider's own error object counts: a self-hosted server can echo the prompt inside a 400, and the
application under test may say "insufficient funds" or "your credit balance is too low" itself."""
from __future__ import annotations

import json

import pytest

from agentqa.ai import providers as P

ANTHROPIC_NO_CREDIT = ('{"type":"error","error":{"type":"invalid_request_error","message":"Your credit balance is too low '
                       'to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."},'
                       '"request_id":"req_011CggcA8ehb7FLKxTccp8sd"}')
OPENAI_HARD_LIMIT = ('{"error":{"message":"Billing hard limit has been reached","type":"invalid_request_error",'
                     '"param":null,"code":"billing_hard_limit_reached"}}')
GEMINI_NO_FREE_TIER = ('{"error":{"code":400,"message":"Gemini API free tier is not available in your country. Please '
                       'enable billing on your project in Google AI Studio.","status":"FAILED_PRECONDITION"}}')


def echo(text: str) -> str:
    """A validation 400 as vLLM-style servers write it: the offending input is copied into the message."""
    return json.dumps({"object": "error", "type": "BadRequestError", "code": 400,
                       "message": f"[{{'type': 'string_type', 'loc': ('body', 'messages', 1), 'input': '{text}'}}]"})


def test_anthropics_credit_balance_400_is_billing_and_billing_is_dead():
    assert P.classify(400, ANTHROPIC_NO_CREDIT, "anthropic") == "billing"
    assert "billing" in P.DEAD


@pytest.mark.parametrize("provider,body", [
    ("openai", OPENAI_HARD_LIMIT),
    ("openai", '{"error":{"message":"Your account is not active, please check your billing details on our website.",'
               '"type":"billing_not_active","code":null}}'),
    ("openai", '{"error":{"message":"You exceeded your current quota.","type":"insufficient_quota",'
               '"code":"insufficient_quota"}}'),
    ("gemini", GEMINI_NO_FREE_TIER),
    ("anthropic", '{"type":"error","error":{"type":"billing_error","message":"There is an issue with your billing"}}'),
])
def test_openai_gemini_and_anthropic_typed_billing_400s_are_billing(provider, body):
    assert P.classify(400, body, provider) == "billing"


@pytest.mark.parametrize("provider,body", [
    ("openai_compatible", ANTHROPIC_NO_CREDIT),                  # another provider's wording does not count
    ("", ANTHROPIC_NO_CREDIT),                                   # nor without a provider
    ("gemini", OPENAI_HARD_LIMIT),
    ("openai_compatible", echo("Insufficient funds: your credit balance is too low for this transfer")),
    ("openai", echo("billing_hard_limit_reached")),              # the code only counts in the error's own fields
    ("anthropic", '{"type":"error","error":{"type":"invalid_request_error","message":"messages.1: the page says '
                  'Your credit balance is too low"}}'),
    ("gemini", '{"error":{"code":400,"message":"Please enable billing words on a page","status":"INVALID_ARGUMENT"}}'),
    ("anthropic", "HTTP 400 Your credit balance is too low (not JSON)"),
    ("anthropic", '["not", "an", "error", "object"]'),
    ("anthropic", "null"),
    ("anthropic", '{"error": null}'),
    ("anthropic", '{"error": "Your credit balance is too low"}'),
    ("anthropic", '{"error": {"message": null}}'),
    ("openai", '{"error": {"code": 400, "type": null, "message": "billing_hard_limit_reached"}}'),
    ("gemini", '{"error": {"status": "FAILED_PRECONDITION", "message": 7}}'),
])
def test_billing_words_outside_the_providers_own_error_fields_are_not_billing(provider, body):
    assert P.classify(400, body, provider) == "bad_request"


@pytest.mark.parametrize("body,kind", [
    ('{"type":"error","error":{"type":"invalid_request_error","message":"prompt is too long: 215000 tokens > 200000 '
     'maximum"}}', "bad_request"),
    ('{"error":{"message":"Invalid value for \'temperature\': must be between 0 and 2","type":"invalid_request_error"}}',
     "bad_request"),
    ('{"error":{"message":"Output blocked by content filtering policy"}}', "bad_request"),
    ('{"error":{"message":"response_format json_object is not supported"}}', "bad_request"),
    ('{"error":"invalid think value"}', "bad_request"),
    ('{"error":{"message":"The model `claude-9` does not exist"}}', "model"),
])
@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini", "ollama", ""])
def test_ordinary_400s_keep_their_kind(body, kind, provider):
    assert P.classify(400, body, provider) == kind


@pytest.mark.parametrize("status,body,kind", [
    (429, '{"error":{"type":"rate_limit_exceeded"}}', "rate_limit"),
    (429, '{"error":{"type":"insufficient_quota"}}', "billing"),
    (402, '{"error":"Insufficient Balance"}', "billing"),
    (403, '{"error":"billing is not enabled"}', "billing"),
    (403, '{"error":"forbidden"}', "invalid_key"),
    (401, ANTHROPIC_NO_CREDIT, "invalid_key"),
    (503, "", "unavailable"),
])
def test_other_statuses_keep_their_kind(status, body, kind):
    assert P.classify(status, body, "anthropic") == kind
    assert P.classify(status, body) == kind
