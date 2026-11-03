# Plan — M1.2 AI modes & selector 🔒

**Milestone:** M1.2 (PRD §9 Phase 1; FR-AI-1…8; §7.3 "one gateway"; §8 `ai_usage`, `budgets`, `ai_assignments`).
**Marker:** 🔒 — provider keys, consent before text or screenshots leave the PC, outbound calls to providers and to
loopback, money. **Owner approval:** required before building (asked 3 Nov 2026). Planned with the `planner` agent,
which checked every claim below against the code.

## Goal

Each project chooses **No AI, Local, Cloud or Hybrid**. Every agent asks for a *tier* (cheap / balanced / strong /
vision), never a model. Cloud use needs the owner's consent and stays inside a monthly budget; at the cap the project
drops back to No AI, the run continues and the owner is told. The old `agentqa/llm.py` path is removed. PRD
acceptance: **the same demo run in No-AI, Local (Ollama qwen3) and Cloud (Anthropic); cost shown per agent; the cap
triggers the fallback and the alert.**

## What the code says that changed the first design (recorded so nobody re-learns it)

1. `req_chat.py:141-148` calls `gateway.available()` / `complete_json(...)`, not `chat_json`: the new client offers both.
2. Model callers beyond the obvious seven: `login_flow.py:504-511`, `doctor.py:197-198`, `agents/requirements.py::_enrich`
   (a separate agent from `srs_analyst`), the old dashboard (`web/app.py:883, 1066-1072, 1185-1189, 1231, 1305-1307`,
   `testdata.html`), tests `test_v05.py:127,158,211,227`, `test_v06.py`, `test_visual_qa.py`.
3. The old `get_llm` sent every call through the gateway (so to cloud keys) whenever any key existed, even with
   `provider: ollama`. Mapping "enabled + ollama → local" is therefore a behaviour change; only the demo has an `llm:`
   block and it is disabled, so no real project is affected. Recorded in ADR 0002.
4. Visual QA is mostly **text** (page text, elements, accessibility tree); the screenshot is optional. It gets the
   *balanced* tier plus an image only when consent allows and the model can see — otherwise Local mode would leave it
   with no model, because `qwen3:4b` cannot read images.
5. `documents.ocr()` has no project in hand; per-project consent means passing an `ai` client down `read() → _pdf() →
   ocr()`. The installation-wide `send_screenshots` policy is retired in favour of the project's consent.
6. Tiers apply only to keys whose model is `auto`; a pinned model wins (the owner's Gemini key is pinned on purpose to
   `gemini-flash-lite-latest`). Checked 3 Nov 2026: the Anthropic key **is** `auto`, so tiers reach Opus/Sonnet/Haiku.
7. The usage table lives in the **project store** (`.agentqa/agentqa.db`), as PRD §8 counts it; budgets are per
   project. The router gets an `on_usage` callback and stays unaware of projects. `ai.db` keeps key health and the audit log.
8. The default policy order puts `gemini` first (`store.py:22`): Cloud mode would be answered by Gemini. The Anthropic
   acceptance needs Anthropic first in the order (one click on the new page).
9. "Local" must mean *this computer*: provider `ollama` or `lmstudio` **and** a loopback `base_url`. An Ollama on another
   machine is treated as cloud and needs consent.
10. One global `timeout_s` of 60 s is too short for a cold local model (the old client used 240 s): keys get their own
    `timeout_s`, local default 240.
11. `agentqa/ai/__init__.py` imports the router, which imports the Anthropic SDK; `config.py` must not pay that on every
    project load, so the package init becomes lazy (PEP 562 `__getattr__`).
12. One local model on this machine: each local key uses its own model for every tier (no size-based picking yet).
13. `tools/check_demo.py`'s "0 extra" is only guaranteed in No-AI mode; model-written cases and verdicts can add defects.
14. `cli.py` (726 lines) and `config.py` (486) take no new logic; `providers.py` (377) would pass 400, so `CATALOG` and
    the tier table move to `ai/catalog.py`.

## The `ai:` block in `project.yaml` (defaults in `config.DEFAULTS`; the `llm:` default is deleted)

```yaml
ai:
  mode: none            # none | local | cloud | hybrid
  consent: {send_text: false, send_screenshots: false}   # only matter when text would leave the PC
  budget: {monthly_usd: 10, alert_at_pct: 80}            # 0.5–1000; there is no "unlimited"
  assignments: {}       # agent: cheap|balanced|strong|vision|off, overrides the default table
  max_chunks: 40        # was llm.max_chunks (SRS Analyst model pass)
```

**Migration** (`ai/settings.py: migrate_llm(raw)`, run in `Project.__init__` only when `ai:` is missing; nothing is
written to disk until the owner saves). Saving writes `ai:` with `yamledit.replace_top_block` and removes `llm:` with a
new `yamledit.remove_top_block`.

| Old `llm:` | New `ai:` |
|---|---|
| missing, or `enabled: false` | `mode: none` |
| `enabled: true`, provider ollama | `mode: local` (the old code went to cloud when keys existed — ADR 0002) |
| `enabled: true`, provider gemini | `mode: cloud`, consent **off**, and a "confirm consent" banner (the project's own Gemini key from the Test data page is not carried over — add it under AI providers) |
| `polish_defects: false` (the old default) | `assignments.triage: off` |
| `max_chunks` | `ai.max_chunks` |

## Default assignment table (`ai/modes.py: AGENTS`)

| Agent key | Where in the code | Tier |
|---|---|---|
| `req_chat` | `agents/req_chat.py` | strong |
| `req_writer` | `agents/req_writer.py` | strong |
| `srs` | `agents/srs_analyst.py` model pass + completeness check | balanced |
| `requirements` | `agents/requirements.py::_enrich` | balanced |
| `casegen` | `agents/casegen.py` | balanced |
| `visual_qa` | `agents/visual_qa.py` (text first; screenshot only if allowed and the model can see) | balanced + image |
| `documents` | `documents.ocr` (needs the image) | vision |
| `triage` | defect title polish | cheap |
| `assistant` | `agents/assistant.py` | cheap |
| `login` | `login_flow._ask_model` | cheap |

## How a request is routed (`ai/modes.py: resolve`)

| Mode | cheap | balanced / strong | needs an image | Cloud text consent off | Monthly cap reached |
|---|---|---|---|---|---|
| none | no AI | no AI | no AI | — | — |
| local | local keys | local keys | a local vision model, else text only (Visual QA) or no AI (OCR) | not needed (nothing leaves the PC) | not affected (free) |
| cloud | cloud keys | cloud keys | cloud vision model, image only if `send_screenshots` | no AI: "you have not allowed text to be sent" | no AI + alert |
| hybrid | local, then cloud | cloud, then local | cloud with consent, else local | local only | local only (owner decision 4) |

"Local key" = provider `ollama` or `lmstudio` **and** a loopback `base_url`; anything else is cloud. Agent set to
`off`, or no usable key: no AI, with a plain-English reason ("Ollama is running but no model is pulled — run
`ollama pull qwen3:4b`"). The reason appears in the effective table, in the live view (`model` event, once per agent
per stage) and in `doctor`. Redaction stays on for every cloud call.

## What is built

### Backend — `agentqa/ai/` (each file ≤ 400 lines)

| File | Responsibility | Size |
|---|---|---|
| `__init__.py` | Lazy exports (PEP 562), so `config → ai.settings` does not import the SDKs | ~25 |
| `settings.py` (new, pure) | `DEFAULT_AI`, `migrate_llm`, `AiSettings` (frozen dataclass), validation | ~120 |
| `catalog.py` (new) | `CATALOG` moved from providers (re-exported there) + `local: True` on ollama and the new `lmstudio` entry (openai family, `http://127.0.0.1:1234/v1`, keyless); `TIERS` per provider: anthropic cheap `claude-haiku-5-5` / balanced `claude-sonnet-5-5` / strong `claude-opus-5-5` / vision sonnet; gemini cheap, balanced and vision `gemini-flash-lite-latest` → `gemini-flash-latest`, strong `gemini-pro-latest` → `gemini-flash-latest`; openai family uses the existing `prefer`; local = the key's model for every tier; `is_local(key)`; `model_for_tier(key, names, tier)` (a pinned model wins) | ~150 |
| `providers.py` | `last_usage` for OpenAI (`usage`), Gemini (`usageMetadata`), Ollama (`prompt_eval_count` / `eval_count`); `GeminiAdapter.pick` prefers `-latest` aliases and never picks by highest version (M0.3 gap a) | 377 → ~330 |
| `router.py` | `complete_json(..., scopes=("cloud",), tier=None, on_usage=None)`; `ordered()` filters by scope and keeps that order (so hybrid works); per-key `timeout_s`; on timeout or unavailable, try the next candidate model before cooling the key down; `last` made per thread | 195 → ~260 |
| `usage.py` (new) | `ai_usage` table in the **project store**: at, pipeline, agent, tier, scope, provider, model, input/output tokens, cost_usd, estimated, ms — **never prompt or answer text**; `DEFAULT_PRICES` (date-stamped from the vendors' price pages on build day) + policy `prices` overrides; local = $0; unknown cloud price = that provider's highest known price, marked estimated; month / per-agent / per-run queries | ~150 |
| `budget.py` (new) | `status(store, settings)` → spent, cap, %, ok / warning / capped; one alert per state per month (`meta` key + `live.emit("ai", "cost", ..., state=...)`) | ~90 |
| `client.py` (new) | `model_for(project, agent) -> AiClient \| None` with `.available()`, `.chat_json(system, user, max_tokens, image_jpeg)`, `.complete_json(...)` (for req_chat), `.model`, `.enabled`, `.reason`; budget checked **before every cloud attempt**; pipeline id from `AGENTQA_PIPELINE_ID` | ~160 |
| `local.py` (new) | `probe()`: only `127.0.0.1:11434/api/tags` and `127.0.0.1:1234/v1/models`, 1 s timeout, plain-English fixes; `PROBES` is a constant that tests swap | ~90 |

**Call sites rewired (each a one-line import change plus the cfg key):** assistant, casegen, requirements, req_writer,
triage (`polish_defects` → assignment), srs_analyst (no `LocalLLM({})`; `want = llm is not None`), visual_qa (`_image`
reads project consent and model vision), login_flow, req_chat, `documents.read/ocr(..., ai=None)` (callers `intake` and
`srs_analyst` pass `model_for(p, "documents")`), doctor (prints the effective table). **Deleted:** `agentqa/llm.py`, the
`llm-check` command (`cli.py:487-490, 675`), the Test data page's model panel. **Old dashboard:** `/ai/project` and
line 883 read and write `ai.mode` (a toggle between none and the last non-none mode, plus a link to the new page).
**ADR** `docs/adr/0002-one-ai-gateway.md` is the migration note; README's `llm-check` section becomes `ai-test`.

### API — `api/routes_ai.py` + `api/schemas_ai.py` (owner-only, envelope, CSRF rule, the global rate limiter)

| Endpoint | What it does |
|---|---|
| `GET /ai/catalog` | Providers, family, local / vision / keyless flags, tier table |
| `GET /ai/keys` · `POST /ai/keys` | Masked list with health · add a key (`provider` must be in the catalog; `base_url` http(s) only, link-local / metadata hosts refused with preflight's checker) |
| `PATCH /ai/keys/{id}` · `DELETE /ai/keys/{id}` | Edit (an empty key keeps the stored one), enable / disable, priority, model, fallback, `timeout_s` · delete |
| `POST /ai/keys/{id}/test` | `Gateway.test` in a thread pool; detail scrubbed of key text; model list returned |
| `GET /ai/local` | `local.probe()`, takes **no address parameter**; "Use it" is `POST /ai/keys` with the fixed address |
| `GET/PUT /ai/policy` | order, failover, attempts, timeouts, cool-downs, redact, `prices` |
| `GET/PUT /projects/{slug}/ai` | Saved block + `effective`: per agent the tier, provider and model that would answer, or the reason; PUT validated with Literals and Field limits |
| `GET /projects/{slug}/ai/usage?month=YYYY-MM` | Per agent, per run, month to date, cap state |

### Frontend — `frontend/src/`

- `lib/ai.ts`: types, API calls, and pure helpers `capState`, `routeLabel` (unit-tested).
- `pages/wizard/StepAi.tsx`: four choices; the consent boxes appear only under Cloud and Hybrid; budget with the
  default; local status line ("Ollama running, no model yet — ask me how"); count of cloud keys + link. It replaces
  `StepAi` in `StepLater.tsx`. `wizard.ts` reducer gains `ai`; `NewProject.advance` does `PUT /projects/{slug}/ai`.
- `pages/ai/AiSettings.tsx` at `/projects/:slug/ai`, made of `ModeCard`, `Providers` (masked keys; add form with a
  password input that is cleared after save; Test; provider order), `LocalDetect`, `Assignments` (per agent: tier or
  off, effective model or reason), `UsageMeter` (per agent and run, month bar, warning and cap banners). Links from
  `Shell.tsx`, `Project.tsx` (an "AI: Local · $0.42 this month" card) and `App.tsx`.

## Tests first

**Stand-in changes in `demo/mock_ai.py`:** `/ollama/api/tags` and `/ollama/api/chat` (with `prompt_eval_count` /
`eval_count`); `/lmstudio/v1/models` and `/lmstudio/v1/chat/completions`; keyless paths skip the "empty key → 401"
rule; OpenAI answers carry `usage`, Gemini answers `usageMetadata`; the model list gains `gemini-flash-lite-latest`,
`gemini-flash-latest`, `gemini-pro-latest`, `gemini-3.8-flash`, `claude-opus-5-5`; model `slow-model` sleeps 5 s;
`/_seen` reports per key whether an image arrived.

**Backend:**
- `test_ai_settings.py`: DEFAULTS has `ai` and no `llm`; every migration row; an existing `ai:` beats `llm:`; the demo
  project loads as `none`; save writes `ai:` and removes `llm:` while other blocks' comments survive.
- `test_ai_catalog.py`: anthropic tiers; a pinned model wins; Gemini picks `-latest` aliases and not `gemini-3.8-flash`;
  with no aliases it still picks the stable flash (port of the `test_v05` Gemini assertions); `lmstudio` is keyless,
  local and openai-family; a non-loopback Ollama is not local.
- `test_ai_modes.py` (parametrised over the routing table): every mode × tier; consent off; hybrid order; agent off;
  capped (cloud → none, hybrid → local); Visual QA with screenshots off → text only; OCR → none.
- `test_ai_router_scope.py`: scope filter and order; per-key timeout; timeout → next candidate model before cooling;
  `on_usage` called with tokens for all four families.
- `test_ai_usage.py`: cost from prices; local $0; unknown price estimated and flagged; no column contains the prompt
  (a marker string is planted); per-agent, per-run and month queries.
- `test_ai_budget.py`: warning at 80 %; at the cap no request reaches the stand-in (`CALLS` unchanged) and the agent
  gets `None`; two capped calls → one alert and one live event; hybrid keeps answering locally; month rollover resets.
- `test_ai_client.py`: none → `None` + reason; duck-typed interface incl. `complete_json`; image withheld without
  consent (`/_seen`); redaction on cloud; pipeline id in the usage row; `model` live event emitted once.
- `test_ai_local.py`: running with models / running without models (fix text names `ollama pull qwen3:4b`) / refused /
  LM Studio; only the two fixed endpoints are ever contacted.
- `test_api_ai.py`: every endpoint with the envelope; 401 signed out; 404 unknown slug; 422 for a bad mode, tier,
  budget or provider; a planted secret never appears in any response body; PATCH with an empty key keeps it;
  `base_url` 169.254.169.254 → 422; effective table; usage.
- `test_legacy_llm_removed.py`: `import agentqa.llm` fails; no source file mentions `agentqa.llm`; no `llm-check`
  subcommand; `ai-test` remains.
- Updated, not weakened: `test_v05` (monkeypatch `agentqa.ai.client.model_for`), `test_v06`, `test_visual_qa` (set
  `ai.mode` + consent), `test_req_chat`, `test_ai_gateway`.

**Frontend:** `wizard.test.ts` (ai state), `StepAi.test.tsx` (consent hidden for none and local; default budget sent),
`Providers.test.tsx` (password field, value cleared after save, only the masked key shown), `UsageMeter.test.tsx`
(warning and cap banners), `ai.test.ts`.

## Build order (two commits)

**Phase A — backend and removal of `llm.py` (commit 1).**
1. mock_ai + `settings.py` + `catalog.py`.
2. Adapters' usage + router scope, tier, timeout and callback.
3. `usage.py` + `budget.py`.
4. `modes.py` + `client.py`; rewire the 10 call sites; delete `llm.py` and `llm-check`; doctor; old dashboard.
5. `local.py` + routes and schemas.
6. ADR 0002 + README; full suite, pyflakes, `check_demo` 19/0 in No-AI; fresh-context `code-reviewer` +
   `python-reviewer` + **`security-reviewer`**; fix HIGH and MEDIUM test-first; commit.

Steps 2–3 depend on 1, step 4 on 2–3, step 5 on 4.

**Phase B — frontend and acceptance (commit 2).**
1. `lib/ai.ts` + StepAi + reducer.
2. The AiSettings pages + links.
3. Acceptance:
   - **No-AI:** demo run, `check_demo` 19/19, 0 extra.
   - **Local:** the owner runs `ollama pull qwen3:4b` in his own terminal → "Use it" → demo run in Local.
   - **Cloud:** Anthropic moved first in the order → demo run in Cloud; per-agent cost visible.
   - **Cap:** a test project with a $0.05 cap trips the fallback, the banner and the live alert mid-run.
4. `typescript-reviewer` + `react-reviewer` + `security-reviewer`, then commit.

## Risks

- **Budget:** the cap is checked before each cloud call, so up to 4 parallel workers can overshoot by the calls already
  in flight (cents). Usage lives in the project folder, so deleting the folder resets it.
- **Outbound requests:** keys' `base_url` and Test are owner-only and use preflight's address guard; the local probe
  has fixed addresses only.
- **Speed:** a Local run is slow: qwen3:4b fits the 4 GB GPU, but Visual QA makes dozens of calls; expect a much longer
  run than No-AI.
- **LM Studio:** may reject `response_format: json_object`; the adapter's existing retry without it covers the usual
  message. Not installed here, so it is tested against the stand-in only.
- **Untrusted content:** page and document text still goes into prompts as data; model answers stay proposals
  (existing grounding checks).

## Decisions for the owner (the 🔒 gate)

**Confirmed by the owner, 3 Nov 2026: all seven as recommended** — qwen3:4b (pulled by him the same day), Opus 5.5 as
"strong", up to $5 for the acceptance with a $10 default cap and 80 % warning, Hybrid keeps the local model at the cap,
`llm-check` and the Test data page's Gemini field removed, AI-mode demo extras listed and explained, no new dependencies.
**Build order changed by the owner the same day:** the UI theme slice (`docs/plans/m1-2-ui-theme-responsive.md`) is
built first so the M1.2 pages land on the new look; Phase A (backend) may run in parallel since it touches no frontend file.

The seven as they were put to him:

1. **Model:** `qwen3:4b` (fits the GPU; `qwen3:8b` would spill to the CPU). He runs `ollama pull qwen3:4b` himself
   (about 2.5 GB).
2. **"Strong" = Opus 5.5 (PRD FR-AI-8) or Sonnet 5.5.** Only Requirement Chat and Requirement Writer use strong
   (about 7 calls per run). M0.3 measured a Writer chunk on Sonnet at about $0.033, so about $0.20 per Writer run; Opus
   costs more per token (exact figure from Anthropic's price page on build day). Whole Cloud demo run estimate:
   **about $1–3 with Sonnet as strong** (Visual QA is the bulk), more with Opus.
3. **Spend for the acceptance:** up to **$5**. Default monthly cap per project **$10**, alert at **80 %**.
4. **At the cap:** Cloud → No AI (PRD). Hybrid → keep using the free local model (recommended) or go fully No-AI.
5. **Remove `llm-check`** (`ai-test` and the AI page replace it) and the Test data page's per-project Gemini key path.
6. **AI-mode runs:** the demo check is 19 found; extras are listed and explained rather than gated at 0 (No-AI stays 19/0).
7. New dependencies: none.

## Out of scope (named so nobody expects them)

Report section "AI used in this run" (M1.6; the live view says it now) · email / Slack budget alerts (Notifier, M1.7) ·
`stage_runs.model/cost/tier` columns (cost per run comes from `ai_usage`) · team roles on keys (M2.1) · auto-pulling or
installing models · vLLM/Jan beyond "OpenAI-compatible URL" · Docker host detection for the local probe · `MIN_TOKENS`
tuning for Opus (M0.3 gap c, measured during acceptance only).

## Verification

_(filled in during the build)_

## Review (fresh context)

_(filled in during the build)_

## Record of changes

_(filled in during the build)_
