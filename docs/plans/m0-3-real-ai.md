# Plan — M0.3 Real-AI validation 🔒

**Milestone:** M0.3 (PRD §9, Phase 0; FR-AI-7, FR-AI-8). **Marker:** 🔒 — touches the AI gateway and real credentials.
**Owner approval:** the owner started this slice on 3 Nov 2026 knowing it needs his Anthropic key (and Ollama).

## Goal

Prove, for the first time ever, that the engine's AI gateway works against real providers (v0.8 only ever saw local
stand-ins), move the Anthropic adapter onto the official SDK with current models, and run one real Requirement
Writer pass whose grounding check passes. Record what each call cost.

## Acceptance (from the PRD)

- `python -m agentqa ai-test` passes on at least Anthropic, Gemini and Ollama with real credentials.
  *Reality on this machine:* no Gemini key is known to exist and Ollama is not installed; the owner decides which of
  the two optional providers to add. Anthropic is mandatory.
- One Requirement Writer run with a real model on the demo project; its grounding check (numbers/roles the model
  added are flagged) passes.
- Anthropic adapter uses the official `anthropic` SDK; "strong/balanced/cheap" defaults are `claude-opus-5-5` /
  `claude-sonnet-5-5` / `claude-haiku-5-5` (the per-agent tier table itself is M1.2; here the `auto` model preference
  moves to the current generation).

## Design

- **Adapter:** `AnthropicAdapter` keeps the gateway's contract (`models()`, `chat()`, raise `ProviderError(kind, …)`),
  but calls `anthropic.Anthropic(api_key, base_url, timeout, max_retries=0)` — the router already owns retries, cool-downs
  and failover. SDK exceptions map to the existing kinds: `APITimeoutError → timeout`, `APIConnectionError →
  connection`, `APIStatusError → classify(status, body)` with `retry-after` preserved.
- **Current API rules (claude-api skill, Nov 2026):** no `temperature` (rejected by 5.x models and by the 2026-10-21
  API version), thinking is adaptive and cannot be disabled on Opus 5.5 — so `max_tokens` gets a floor of 1024 for
  Anthropic (thinking tokens count against it; `test_key` asks for 30), `output_config.effort="low"` for these short
  JSON tasks, server-side refusal fallback (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`) by
  default, and a `stop_reason == "refusal"` becomes `ProviderError("bad_request", …)`. If a model rejects one of
  the newer fields (400 naming `output_config`, `effort`, `fallbacks` or the beta), the call is retried once in plain
  form, mirroring the OpenAI adapter's `response_format` fallback.
- **Base URL:** keys store `…/v1`; the SDK appends `/v1/...` itself, so the adapter strips a trailing `/v1`. This keeps
  the stand-in (`demo/mock_ai.py`, path `/anthropic/v1`) and every existing test working.
- **Stand-in:** `mock_ai.py`'s Anthropic answers gain the fields a real Messages response has (`id`, `type`, `role`,
  `model`, `stop_reason`, `usage`) so the SDK parses them.
- **Model preference** (`CATALOG["anthropic"]["prefer"]`): `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-opus-5-5`,
  then the old generic patterns.
- **Dependency:** `anthropic>=2.3,<3` in `backend/requirements.txt`; `deploy/constraints.txt` regenerated.
- **Credentials:** the owner enters keys himself on the dashboard's **AI providers** page (encrypted in
  `%APPDATA%\AgentQA\ai.vault`); nothing is typed into chat or stored in the repo. Ollama (optional) is installed by
  the owner (`winget install Ollama.Ollama`, `ollama pull qwen3:4b`).
- **Cost record:** `ai-test` and the Requirement Writer run report tokens from the audit log; the plan records the
  totals.

## Tests first

`tests/test_anthropic_adapter.py` against the stand-in and a tiny request-capturing server: client built with the
`/v1`-stripped base URL and `max_retries=0`; a successful chat returns the text; rate limit → `rate_limit` with
`retry_after`; 401 → `invalid_key`; the request body carries no `temperature`, has `max_tokens ≥ 1024`, and an image
arrives as a base64 block; a 400 naming `output_config` is retried in plain form. Existing `test_ai_gateway.py`
(failover through the Anthropic stand-in) must keep passing.

## Out of scope

Per-agent tier table, cost meter UI, consent switches, LM Studio detection (M1.2); removing `agentqa/llm.py` (M1.2).

## Risks

- Real-provider behaviour differs from the stand-in (that is the point of this slice): fix in the adapter, add a test.
- Spend: `ai-test` is one tiny call per key; the Requirement Writer pass over the demo SRS is roughly 45 requirements
  → expect well under $1 on Sonnet 5.5.

## Review (fresh context, code-reviewer + python-reviewer + security-reviewer)

Verdict **Warning**: 0 CRITICAL, 2 HIGH, 5 MEDIUM, 9 LOW. Fixed before commit, each with a capture-server test first:
- HIGH-1: the plain-form retry never fired when the 400 body said "… not supported for this model" (`classify` turns
  that into kind `model`); the check now keys on `status == 400` + a newer-field name, and the field list drops the
  bare words `effort`/`betas` (LOW-10) that matched unrelated 400s.
- HIGH-2: a 200 the SDK cannot parse (a proxy's HTML) escaped as a raw exception past the router; `_call` now maps
  any remaining `anthropic.APIError`, and `chat` rejects a non-Messages answer as `bad_output`.
- MEDIUM-3: `stop_reason == "max_tokens"` is `bad_output` with the budget named, instead of a half answer.
  MEDIUM-4: the SDK client is used as a context manager (no leaked connection pools). LOW-8/9/15: `last_usage` reset
  per call, refusal category in the message, `EFFORT` constant and type annotations. LOW-13: test servers call
  `server_close()`. LOW-14: the first request's `fallbacks` and `anthropic-beta` header are asserted.
- MEDIUM-5/6/7, LOW-11/12: plan wording — explicit acceptance status, Gemini pin labelled a workaround with an M1.2
  item, run-1 cost marked as an estimate, retry claim softened, test counts corrected (below).
- Security: no findings (bodies capped at 600 chars and scrubbed; the SDK never falls back to env keys when a key is
  passed; 401 bodies do not echo keys).

## Verification (3 Nov 2026, real providers)

- `python -m agentqa ai-test`: **Claude (anthropic): OK — claude-sonnet-5-5 in 1682 ms; Gemini (gemini): OK —
  gemini-flash-lite-latest in 1437 ms.** Ollama: not installed on this machine; the owner chose Gemini as the second
  provider instead (Ollama can be added later from the same page, keyless).
- Requirement Writer, run 1 (Anthropic only, before token logging): 6 calls, ~15 s each, 35/35 requirements written
  by the model, 8 flagged by the grounding check. Estimated from run 2's per-call size (~2.8k in / ~2.7k out):
  ≈ 17k input + 16k output tokens ≈ **$0.20** at Sonnet 5.5 list price.
- Requirement Writer, run 2 (both providers, token logging on; 114 s): 35/35 by model, 4 flagged. The audit log shows
  the **failover working against real services**: Gemini `gemini-2.5-flash` → 404 "no longer available"; fallback
  `gemini-flash-latest` → 60 s timeout, then 503; router event "Gemini: Service unavailable; trying Claude" → Claude
  answered chunk 1 (16.8 s, **2,806 in / 2,749 out tokens = $0.033**); after the key was re-pinned to
  `gemini-flash-lite-latest` the other 5 chunks went to Gemini at 3.5–4.0 s each (free tier, no usage reported by the
  Gemini adapter yet — M1.2 adds usage for the other families).
- Unit suite after the review fixes: **81 passed**, lint clean; `ai-test` re-run on the final adapter passes on both
  providers. Total spend this milestone: well under $0.50 on Anthropic; Gemini free tier.

**Acceptance status.** Anthropic: **met** (SDK adapter, real `ai-test`, real Requirement Writer run, tokens recorded
for run 2; run 1's token totals were *not captured* because usage logging did not exist yet, so its cost is an
estimate). Gemini: **met via a workaround** — the key is hand-pinned to `gemini-flash-lite-latest`; `GeminiAdapter.pick`
still chooses the highest version number, so a fresh Gemini key would repeat the 503/timeout failure. Ollama: **not
met** — not installed on this machine; the owner chose Gemini as the second provider (owner decision, 3 Nov 2026).

**Opened for M1.2 (tier table):** (a) Gemini auto-pick: prefer `-latest`/lite aliases or a tested list, and fall back
to the next candidate on 503/timeout, not only on a 404 "model" error; (b) token usage for the OpenAI, Gemini and
Ollama families (`usageMetadata`, `usage`, `prompt_eval_count`/`eval_count`); (c) consider `MIN_TOKENS` 2048 when the
tier is Opus.

## Record of changes

- `agentqa/ai/providers.py`: `AnthropicAdapter` rewritten on the official SDK (`client()`, `_call()` exception
  mapping, `chat()` with the plain-form retry, refusal → `bad_request`); `_retry_after()` accepts any response with
  `.headers`; `CATALOG["anthropic"]["prefer"]` moved to the 5.5 generation. `anthropic>=2.3,<3` added to requirements.
- `demo/mock_ai.py`: Anthropic answers carry the full Messages shape; the stand-in model list names current models
  (`claude-sonnet-5-5`, `claude-haiku-5-5`), so the SDK no longer warns about a deprecated model in tests.
- Tests: `tests/test_anthropic_adapter.py` (14 after review, RED → GREEN); `tests/test_ai_gateway.py` points its
  fallback-model expectation at the renamed stand-in model and checks token usage in the audit event.
- Owner's first key paste was not an Anthropic key (31 chars, not `sk-ant-`): HTTP 401, as the adapter should report.
  A stray empty OpenAI row and that row were removed from the store; the second paste was a real key.
- **Real provider, 3 Nov 2026:** `python -m agentqa ai-test` → `Claude (anthropic): OK - claude-sonnet-5-5 answered in
  1566 ms`. Sonnet 5.5 accepts the beta Messages call with `output_config.effort=low` + `fallbacks="default"` (the
  adapter does not log whether a plain-form retry happened; a 1.5 s round trip is consistent with a single call).
  First real-model call in the engine's history.
- **Requirement Writer with the real model (run 1):** 35 requirements, 35 written by the model, 8 flagged by the
  grounding check (e.g. "FR-03: the model added 1001 (not in the source)", sample phone numbers in FR-05) — the check
  does its job: additions are flagged for a person, not accepted. 96 s wall time.
- **Token usage recording (TDD'd):** `Adapter.last_usage` (set by the Anthropic adapter from `msg.usage`) and the
  router's ok-event line now reads "… answered · N in / M out tokens", so the audit log carries what each call cost
  in tokens (the dollar meter itself is M1.2). Tests: `test_token_usage_is_kept_for_the_cost_record`,
  `test_an_answer_records_its_token_usage_for_the_cost_record` (both RED → GREEN).
- **Gemini, real provider:** the key lists 46 models. Auto-pick chose `gemini-3.8-flash` (highest version number),
  which answered 503 "high demand" twice and then timed out at 60 s and 90 s; `gemini-2.5-flash` / `-lite` return
  404 "no longer available to new users"; `gemini-flash-latest` took 83 s; **`gemini-3-flash-preview` (2.3 s) and
  `gemini-flash-lite-latest` (1.5 s) work.** Lesson for M1.2's tier table: do not pick Gemini by highest version;
  prefer the `-latest`/lite aliases or a tested list, and fall back on 503/timeout to the next candidate (the router
  only falls back on a 404 "model" error today). For this milestone the Gemini key is pinned to
  `gemini-flash-lite-latest` with fallback `gemini-3-flash-preview`.
