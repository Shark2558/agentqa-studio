# Plan — M1.3 follow-up: an empty AI credit is "billing", and the Live View says when the AI switches

**Found in:** M1.3 Phase C (4 Nov 2026), plan `m1-3-live-view-v2.md`, Review rows **C5** and **C4**.
**Marker:** 🔒 — it changes how the AI gateway reads provider errors (which keys it keeps trying) and adds a new line
from the gateway to the live recording. Reviewed by `code-reviewer`, `python-reviewer`, `typescript-reviewer` and
`security-reviewer` in a fresh context. **Owner approval:** given 4 Nov 2026, the three decisions as recommended
(1a every switch, 2a two names and "and N more", 3a no real Cloud run now). A `planner` check against the code the
same day confirmed the facts below; its findings narrowed part 1 to each provider's own error fields (safer than the
approved draft, same result for the real Anthropic answer) and are marked "planner check" where they changed the plan.
**Branch:** `claude/nervous-sutherland-913fae`, fast-forwarded to the M1.3 work (`8ff58c0`) because part 2 changes the
M1.3 Live View. Not pushed, not merged.

## In plain words (for the owner)

1. When your Anthropic credit ran out, Anthropic answered "Your credit balance is too low". The gateway read that as
   "this one question was refused" instead of "this account cannot pay", so it asked Anthropic again before **every**
   later question (27 times in a row), waited for the refusal, then used Gemini. After this change the first such
   answer marks the Anthropic key "Billing problem" on the AI page, and it is not asked again until you edit the key or
   press Test connection (for example after adding credit).
2. When the gateway moves a question from one AI company to another during a run, the Live View will say so, in the
   stream of the agent that asked: "Requirement Writer: switched from Anthropic Claude to Google Gemini (Billing or
   credit exhausted)". It never shows the key, its name, the question or the error text.
3. An agent's card will list every model it used, not only the last one: "claude-opus-5-5, gemini-flash-lite-latest"
   instead of only the Gemini one, which was misleading when almost all of that card's cost was Opus.

## What the code says (checked 4 Nov 2026)

- `ai/providers.classify` (`providers.py:43`) files every HTTP 400 that does not name a missing model as
  `bad_request`. The router's rule for `bad_request` is "go to the next key without cooling this one"
  (`router.py:9`), so the key stays usable and is first in line again on the next call. The owner's `ai.db` holds the
  exact body, 400 `{"type":"error","error":{"type":"invalid_request_error","message":"Your credit balance is too low
  to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."}}`.
- `billing` is already in `DEAD` (`providers.py:29`): `_consequences` sets the key's state to `billing`, `_usable`
  skips it, an edit or a passing Test connection clears it, and the AI page already shows "Billing problem"
  (`components/ai/KeyRow.tsx:18`). So part 1 only has to classify the answer; nothing downstream changes.
- The Anthropic adapter's plain-form retry (`_rejects_newer_fields`) looks for field names in a 400; the credit text
  names none, so a billing 400 is not sent twice. The OpenAI adapter's `response_format` retry and Ollama's `think`
  retry only run for `bad_request`, so they are skipped too (one wasted call less).
- A switch is written only to `ai_events` (`router.py:155`, outcome `switched`). The router "knows nothing about
  projects": usage already reaches the caller through `Request.on_usage`, and `AiClient._on_usage` writes the live
  `cost` line (`client.py:99-117`). A switch follows the same road.
- Live `ai` events are credited to the stage running at the time (`board.ts` `onAi`, `d.running`), because AI keys
  such as `login` and `visual_qa` serve several stages and the pytest workers. But the agent's stream
  (`AgentFocus.tsx:157`) shows only `e.agent === agent`, so an `ai` line never appears there today.
- A card keeps one `actualModel`, overwritten by each `cost` line (`board.ts:171`).

## Part 1 — C5: an empty credit is `billing`

`classify(status, text, provider="")` (moved from `providers.py` into its own pure module `ai/classify.py` after the
review, and imported back, so `P.classify` still works) learns one rule, checked before "model not found" (a credit
refusal is the stronger signal): a 400 is `billing` when **that provider's own error object**, read as JSON, says the
account cannot pay. The adapters pass their key's provider (`Adapter._send`, `AnthropicAdapter._call`); without one
(old callers) the rule does not apply.

| Provider | Field of the error object | Value | Status |
|---|---|---|---|
| `anthropic` | `error.message` / `error.type` | starts with "Your credit balance is too low" / `billing_error` | 400 (seen 4 Nov 2026) |
| `openai` | `error.code` or `error.type` | `billing_hard_limit_reached`, `billing_not_active`, `insufficient_quota` | 400 (429 is already billing) |
| `gemini` | `error.status` and `error.message` | `FAILED_PRECONDITION` and "enable billing" (free tier unavailable) | 400 |

Why so narrow (planner check, 4 Nov 2026): a self-hosted OpenAI-compatible server (vLLM, LiteLLM) can echo the prompt
inside a 400 validation error, and an application under test may well say "insufficient funds" or "your credit
balance is too low" itself. A phrase anywhere in the body would let a page under test mark a key dead. The official
APIs above do not echo the prompt, and their error codes are not page text. Services that answer 402 for no credit
(DeepSeek, OpenRouter) are already `billing`. Tests (RED first):

- `classify(400, <the exact Anthropic body>, "anthropic") == "billing"`; each row above → `billing`.
- The same Anthropic body from `openai_compatible`, or with no provider → `bad_request`; an OpenAI-compatible 400
  that echoes "insufficient funds" / "credit balance is too low" from the prompt → `bad_request`; an Anthropic 400
  whose message only contains the phrase later → `bad_request`; a body that is not JSON → `bad_request`.
- Ordinary 400s stay as they are: a too-long prompt, an invalid parameter, a refused request, a content-filter 400,
  a model-not-found 400 → `model`; 429 / 402 / 403 unchanged.
- Adapter (`test_anthropic_adapter.py`, new capture mode `no_credit`): the SDK's 400 becomes `ProviderError("billing")`
  after exactly one request (no plain-form retry).
- Gateway (`test_ai_gateway.py`, a new mock key word `nocredit` that answers the Anthropic 400 on chat but lists models,
  as the real API does): the first call marks the key `billing` and is answered by the next provider; three more calls
  never reach the Anthropic key (`mock_ai.CALLS` stays 1); Test connection on that key reports `billing`; editing the
  key gives it a fresh chance (as `test_edit_gives_a_dead_key_a_fresh_chance` does for `invalid_key`).
- What follows from a dead key, on purpose (planner check): it also drops out of `_keys_at_hand`, `modes.resolve` and
  `effective()` (`client.py:120-122, 160`). A Cloud project whose only cloud key runs out of credit therefore says,
  for every later agent, "no model (no cloud AI key is enabled: add one on the AI page)" instead of asking a key that
  cannot answer; with another cloud key, the next agents plan on that one. Client test: the first agent's call fails
  over to nothing, the next agent announces that reason.

## Part 2 — C4: a switch line in the Live View, and every model on the card

**Backend.**
- `router.py`: `Request` gains `on_switch` (like `on_usage`; added last and built with keywords, since `Request` was
  built positionally). In `complete_json`, when the next key is a **different
  provider** from the one that just failed, the router calls `on_switch({"from_provider", "to_provider", "kind",
  "reason", "task"})`: provider ids from the key table, the failure kind and its fixed words from `P.KINDS`. Never the
  key text, label, id, error body, prompt or answer. A broken callback is logged and never loses the answer (same
  guard as `_report_usage`). A switch between two keys of the **same** provider stays in `ai_events` only: the line
  would say nothing new and would hint at how many keys there are.
- `client.py`: `AiClient.complete_json` passes `on_switch=self._on_switch`, which writes one live line:
  `live.emit("ai", "switched", "<agent label>: switched from <provider name> to <provider name> (<reason>)",
  agent_key, tier, from_provider, to_provider, failure=<kind>)` (`failure`, not `reason`: on the `model` line `reason`
  holds words). Provider names come from `ai/catalog` (pure, no SDK
  import); an unknown id is shown as itself. A failed write loses the line, never the answer (same guard as `cost`).
- `orchestrator/phases.py`: `switched` → **result** ("what happened"), so it is a stream row, not card meta.
  `tests/test_live_phases.py` already fails if a kind has no phase; it gains `("ai", "switched", "result")`.

**Frontend.**
- `lib/live/board.ts`: a `switched` line is credited to the stage running at its time, like `cost`: the card keeps the
  line's key in `switchLines` (at most 50; a stream that invents lines cannot grow it). Each `cost` line adds its model
  to the card's `models` list (distinct, in first-use order, at most 20 names, the same cap as `planned`).
  `actualModel` stays (the final summary and the fixture use it).
- `cardModel`: the first two models, then "and N more" (`"claude-opus-5-5, gemini-flash-lite-latest"`, `"a, b and 2
  more"`); with none, the planned model or the reason, as now.
- `components/live/AgentFocus.tsx`: the agent's stream also shows the lines its card was credited with (the card's
  `switchLines` joins the `useMemo` dependencies). With no agent chosen ("What is happening") it already shows every
  non-meta line, so the switch line appears there too.
- The title is rendered as text (React escapes it); `live.emit` cuts every title to 300 characters and `toEvent` to
  500, as for every line.

Tests (Vitest, RED first): two models on one card in first-use order; the same model twice listed once; three models
→ "a, b and 1 more"; 25 invented models keep 20; a switch line during write goes to the Writer's card and not to the
Analyst's; a switch line before any stage is credited nowhere and still shows in "What is happening"; 60 switch lines
keep 50; `AgentFocus` with the Writer chosen shows the switch row (and not the `cost` row); the board given is never
changed. Backend: `test_ai_router_scope.py` — `on_switch` fires once for Anthropic → Gemini, not for OpenAI → OpenAI,
and a broken callback keeps the answer; `test_ai_client.py` — the live line has only the allowed fields and none of
the key text, the label or the prompt markers.

The recorded fixture (`cli-fixture-pipeline`, `live-demo.json`) is **not** changed: the new behaviour is covered by the
unit and component tests above, and `make live-check` must still give the same final picture.

## Files (all under the 400-line guide)

| File | Change | Lines (built) |
|---|---|---|
| `backend/agentqa/ai/classify.py` (new, pure) | `classify` moved here with `_error_object`, `_cannot_pay`, `OPENAI_BILLING_CODES` | 67 |
| `backend/agentqa/ai/providers.py` | imports `classify`; both adapters pass the provider; the Anthropic plain-form retry never runs for a billing answer | 400 → 377 |
| `backend/agentqa/ai/router.py` | `on_switch` in `Request` (built by keyword), `_report_switch`, the provider check in `complete_json` | 304 → 323 |
| `backend/agentqa/ai/client.py` | `_on_switch`, `_label`, `_provider_name`, `_emit_switch` | 188 → 213 |
| `backend/agentqa/orchestrator/phases.py` | `switched` under result | +1 |
| `backend/demo/mock_ai.py` | key words `nocredit` (Anthropic's 400) and `hardlimit` (OpenAI's), on a chat only | +9 |
| `frontend/src/lib/live/board.ts` | `models`, `switchLines`, `withModel`, `withLine`, `cardModel` (names cut to 60 characters) | 285 → 308 |
| `frontend/src/components/live/AgentFocus.tsx` | `isCredited`: the stream includes the card's switch lines | 179 → 186 |
| tests | `test_ai_providers_classify.py` (new), `test_anthropic_adapter.py`, `test_ai_gateway.py`, `test_ai_router_scope.py`, `test_ai_client.py`, `test_live_phases.py`, `board.test.ts`, `AgentFocus.test.tsx`, `model.test.ts` | |

## Security review points

- The provider's error body is untrusted (it can come from a proxy or a self-hosted service). It only chooses a kind
  here; none of it reaches the live line, the card or the AI page beyond what is already scrubbed into `ai_events`.
- A false `billing` makes a key wait until it is edited or re-tested: no money is spent and the AI page says "Billing
  problem". The patterns are provider phrases, so text from the application under test (a bank page saying "credit
  balance") would have to be echoed by the provider inside a 400 in that exact wording.
- The live line carries provider ids, the failure kind, the agent label and the tier. The tests assert the absence of
  the key text, the key label and the prompt.
- New front-end state is capped (`switchLines` 50, `models` 20), like the existing board caps.
- No new endpoint, dependency, permission or setting.
- Accepted (security review): a Viewer, who may watch runs and replays, now also reads the AI companies' names and
  the reason in fixed words, such as "Billing or credit exhausted". The cost line already names the provider and
  model; only the account-state wording is new.

## Verification

- Backend `python -m pytest -q tests` and `pyflakes`; Vitest, typecheck and lint; `tools/check_demo.py` 19/19 with 0
  extra in No-AI mode; `make ui-check` and `make live-check` green.
- Optional, only with the owner's yes (it costs money): one Cloud demo run with his real keys, cap $1. Expected:
  Anthropic asked once, marked "Billing problem", the rest on Gemini (about $0.05), one switch line in the Live View,
  and the card listing the models it used.

**Results (4 Nov 2026, the final code after the review fixes):** RED first for both parts (part 1: 55 failing, the
behaviour tests for the right reason; part 2: 4 backend and 7 Vitest failing), then green. Backend `pytest` **546
passed**; `pyflakes` clean; contrast 232 / 232. Vitest **287 passed** (34 files); typecheck and lint clean.
`tools/check_demo.py`: **19 / 19 seeded bugs, 0 unexpected**, No-AI mode, run twice (before and after the review
fixes). `make ui-check`: passes at 320–1 440 px in both themes. `make live-check`: 447 events watched live over
WebSocket, the same final picture after a reload, a replay at Instant and over SSE. No real Cloud run (decision 3a).
`git status` also lists `cli.py`, the fixture recording and `live-demo.json` as modified: only their Drive file times
changed (`git diff` is empty for them), and they are not in the commit.

## Decisions for the owner

1. **How often the switch line appears.** (a) Every question that moves to another company (recommended: it is what
   happened, and after part 1 an empty-credit key moves only once per run). (b) Once per agent per run.
2. **A card that used several models.** (a) The first two names and "and N more" (recommended: the cards are narrow).
   (b) Every name.
3. **A real Cloud check after the build** (about $0.05, cap $1). (a) Not now; the stand-in tests cover it
   (recommended). (b) Yes, one run.

## Not in this change (follow-ups)

Two more gateway readings found by the planner check, the same kind of problem but not this task (not yet seen on
this machine; both 🔒):
- Google Gemini answers a wrong key with HTTP **400** `API_KEY_INVALID` ("API key not valid"), which `classify` files
  as `bad_request`: such a key would be asked before every call, as the empty Anthropic key was. It should be
  `invalid_key`.
- The 429 rule reads any "billing" as `billing`, and Gemini's free-tier rate-limit message is reported to say
  "please check your plan and billing details" (`RESOURCE_EXHAUSTED`): a per-minute limit would then mark the key dead
  for the run. `RESOURCE_EXHAUSTED` should be checked before the billing words. This matters more now that the owner's
  runs fall back to Gemini.

- Cost per model on the card or in the agent's panel ("$0.23 Opus, $0.01 Gemini").
- Helper agents' own lines (the Analyst inside the Writer's stage) are credited to the card but not shown in that
  card's stream; the same `switchLines` idea could carry them.
- From the reviews (older code, the same kind of problem as part 1; 🔒): the `model` rule (a 400 / 404 / 422 naming a
  model with "not found", "not available" …) and the 429 / 403 billing words still read the whole body, so a
  self-hosted server that echoes page text such as "Model X is not available" could mark a pinned key dead; read the
  provider's own error fields there too. `_retry_after` accepts `inf` / `nan` / `1e999` from a header (a cool-down
  without end until Test connection): clamp it to 0–3 600 s.
- Owner wording: when the only cloud key is dead for billing, later agents say "no cloud AI key is enabled: add one
  on the AI page" while the AI page lists the key as "Billing problem"; "your cloud key needs attention" would be
  truer.
- Not verified (from a reviewer's memory): Anthropic may answer HTTP 400 "You have reached your specified API usage
  limits" when a workspace spend limit is hit; that is still `bad_request`.
- A switch row shows the green "Result" label of the stream; a warn look or its own "Switch" label would read better.
- In Hybrid mode every local-to-cloud move (an Ollama timeout, say) also writes a switch line (decision 1a); watch the
  volume in the next Hybrid run.

## Review (fresh context, 4 Nov 2026)

| Reviewer | Verdict | Acted on |
|---|---|---|
| `planner` (before code) | facts confirmed; one wrong (titles are cut at 300 by `live.emit`, 500 by `toEvent`), gaps | part 1 narrowed to each provider's own error fields; the dead key's effect on later agents tested; `Request` built by keyword; `useMemo` deps; two Gemini readings and the echo risk recorded |
| `security-reviewer` | no CRITICAL / HIGH | the switch-report warning logs the error's type only; `_error_object` cuts the body itself; the Anthropic plain-form retry never runs for a billing answer; long model names cut to 60 characters; the Viewer wording accepted above; the older `model` / Retry-After issues are follow-ups |
| `python-reviewer` | approve | the broken-callback tests prove the callback ran; the field is `failure`; `classify` has a docstring and its own module (`providers.py` back under 400 lines); one shared test helper; full event order checked; more odd bodies and Anthropic's `billing_error` type |
| `typescript-reviewer` | approve, MEDIUMs | no event key is built for lines that are not switches; a checkpoint-boundary and out-of-order test for the new fields; the stream tests check a non-switch AI line, an early switch and a replay both before and after the line; caps keep the first entries (tested); a cost line without a model |
| `code-reviewer` | approve | the plan's file table; OpenAI's billing 400 tested through the gateway (`hardlimit`), not only through `classify`; `_label` helper; fallbacks of the switch line tested; the rest are follow-ups above |

One review suggestion was wrong and was caught by the tests: requiring kind `bad_request` before the Anthropic
plain-form retry broke it, because "fallbacks is not supported for this model" reads as kind `model`; the retry now
runs for `bad_request` or `model`, never for `billing`.
