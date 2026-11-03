# ADR 0002 — One AI gateway; the per-project `llm:` client is removed

**Date:** 3 Nov 2026 · **Status:** accepted · **Decides:** PRD §7.3 "one gateway", FR-AI-1…8 (M1.2 Phase A)

## Context

v0.8 reached a model two ways. `agentqa/llm.py` held a per-project client (`LocalLLM` for Ollama, `GeminiLLM` with the
project's own Google key from the Test data page) driven by an `llm:` block in `project.yaml`. M0.3 added the
installation-wide gateway in `agentqa/ai/` (many providers, several keys each, failover, an encrypted key store and an
audit log). `get_llm()` glued the two together: whenever *any* gateway key existed, every call went through the gateway,
even for a project that said `provider: ollama`; only without keys did the project's own settings apply. Consent for
sending screenshots was a single installation-wide switch, redaction a per-project one, and cost was recorded for
Anthropic only. Agents named models, and some stand-ins (`LocalLLM({})`) existed just to carry an `.enabled` flag.

## Decision

- **One door.** Every agent gets its model through `agentqa.ai.client.model_for(project, agent)` and asks for a
  *tier* (cheap · balanced · strong · vision), never a model id. The tier table lives in `agentqa/ai/catalog.py`;
  a key whose model is pinned wins over the tier.
- **The project decides, the installation provides.** `project.yaml` has an `ai:` block (mode none · local · cloud ·
  hybrid, consent for text and for screenshots, a monthly budget, per-agent tier overrides). Keys, provider order,
  timeouts and prices stay installation-wide in the encrypted store. The router knows nothing about projects: it takes
  a scope order (`local` / `cloud`), a tier and a usage callback.
- **"Local" means this computer.** A key is local only when its provider is marked local (Ollama, LM Studio) *and* its
  address is loopback. Nothing is redacted for local keys (nothing leaves the PC); every cloud call is redacted.
- **Consent and money are per project.** Text reaches a cloud provider only with the project's consent; images only
  with its separate screenshot consent (the installation-wide `send_screenshots` policy is retired). Usage and cost
  are written to the project's own store (`ai_usage`: numbers and names only, never prompt text), priced from a
  date-stamped table the owner may override. At the monthly cap, Cloud drops to No AI and Hybrid keeps the free local
  model; the owner is told once per state per month.
- **Removed:** `agentqa/llm.py`, the `llm-check` command (`ai-test` and the AI page replace it), the Test data page's
  model panel and per-project Gemini key path, and the `llm:` defaults.

## Migration (what happens to an old `llm:` block)

`Project.__init__` runs `agentqa.ai.settings.migrate_llm` when `project.yaml` has `llm:` and no `ai:`. Nothing is
written to disk until the owner saves the AI page; then `ai:` is written and `llm:` removed (comments elsewhere kept).

| Old `llm:` | New `ai:` | Note |
|---|---|---|
| missing, or `enabled: false` | `mode: none` | the default; the demo project ships this way |
| `enabled: true`, provider ollama | `mode: local` | **behaviour change**: the old code sent these calls to cloud keys whenever any key existed; now they stay on this computer |
| `enabled: true`, provider gemini | `mode: cloud`, consent **off**, a notice | text no longer leaves the PC until the owner confirms consent; the project's own Gemini key is not carried over (add it under AI providers) |
| `polish_defects: false` (the old default) | `assignments.triage: off` | defect title polish stays off unless assigned a tier |
| `max_chunks` | `ai.max_chunks` | the Requirement Analyst's model pass cap |

Checked on 3 Nov 2026: only the demo project had an `llm:` block, and it was disabled, so no real project changes
behaviour. Gemini's auto-pick now prefers Google's `-latest` aliases (M0.3 found the newest numbered Flash timing out).

## Consequences

- Agents changed one import each; their behaviour is unchanged except that a missing or refused model is now always
  `None` with a reason the owner can read (live view `ai`/`model` event, `doctor`, the effective table).
- `agentqa.ai` loads lazily (PEP 562) so `agentqa.config` can import the pure `settings` module without paying for the
  provider SDKs on every project load.
- The `ai-test` command stays the one-call-per-key check for real keys; the demo regression stays 19 found / 0 extra
  in No-AI mode, which is the only mode in which "0 extra" is guaranteed (model-written cases can add defects).
- Phase B (the React AI page, the wizard step, acceptance in Local and Cloud modes) builds on this without touching
  the engine again.
