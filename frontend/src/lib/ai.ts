/** AI modes and providers (M1.2): types for the /ai endpoints, the API calls, and the pure helpers the pages share. */
import { ApiError, request } from "./api";

export type AiMode = "none" | "local" | "cloud" | "hybrid";
export type Tier = "cheap" | "balanced" | "strong" | "vision" | "off";
export type BudgetLevel = "ok" | "warning" | "capped";

export interface AiConsent {
  send_text: boolean;
  send_screenshots: boolean;
}
export interface AiBudget {
  monthly_usd: number;
  alert_at_pct: number;
}
export interface AiSettingsInput {
  mode: AiMode;
  consent: AiConsent;
  budget: AiBudget;
  assignments: Record<string, Tier>;
  max_chunks: number;
}

export const MODE_IDS: readonly AiMode[] = ["none", "local", "cloud", "hybrid"];
export const TIER_IDS: readonly Tier[] = ["cheap", "balanced", "strong", "vision", "off"];
export const TIER_LABELS: Record<Tier, string> = { cheap: "Cheap", balanced: "Balanced", strong: "Strong", vision: "Vision", off: "Off (no AI)" };
export const DEFAULT_AI: Readonly<AiSettingsInput> = Object.freeze({
  mode: "none" as AiMode,
  consent: Object.freeze({ send_text: false, send_screenshots: false }),
  budget: Object.freeze({ monthly_usd: 10, alert_at_pct: 80 }),
  assignments: Object.freeze({}) as Record<string, Tier>,
  max_chunks: 40,
});

/** The four choices as the owner reads them (PRD, AI modes). */
export const MODES: readonly { id: AiMode; title: string; blurb: string }[] = [
  { id: "none", title: "No AI", blurb: "Documents are read, the application explored and tests written by rules. Free, private, works offline." },
  { id: "local", title: "Local AI", blurb: "A model on this computer (Ollama or LM Studio) helps read vague documents and write better test ideas. Nothing leaves your PC." },
  { id: "cloud", title: "Cloud AI", blurb: "Anthropic, Google or OpenAI with your own key, a monthly budget and consent switches. Falls back to No AI at the cap." },
  { id: "hybrid", title: "Hybrid", blurb: "Cheap jobs stay on this computer; the harder ones go to the cloud with your consent. Keeps the local model at the cap." },
];

export interface EffectiveRow {
  agent: string;
  label: string;
  tier: string;
  scopes: string[];
  image: boolean;
  provider: string | null;
  model: string | null;
  reason: string | null;
}
export interface BudgetStatus {
  month: string;
  spent: number;
  cap: number;
  pct: number;
  alert_at_pct: number;
  state: BudgetLevel;
}
/** The `ai:` block as the API returns it: hand-editable in project.yaml, so every field may be missing or odd. */
export interface SavedAi {
  mode?: unknown;
  consent?: Partial<AiConsent>;
  budget?: Partial<AiBudget>;
  assignments?: Record<string, unknown>;
  max_chunks?: unknown;
}
export interface ProjectAi {
  settings: SavedAi;
  effective: EffectiveRow[];
  notice: string | null;
  budget: BudgetStatus;
}
export interface ProviderInfo {
  id: string;
  name: string;
  family: string;
  base_url: string;
  vision: boolean;
  keyless: boolean;
  local: boolean;
  tiers: Record<string, string[]>;
}
export interface CatalogAgent {
  agent: string;
  label: string;
  tier: string;
  image: "none" | "optional" | "required";
}
export interface Catalog {
  providers: ProviderInfo[];
  tiers: string[];
  agents: CatalogAgent[];
}
export interface KeyState {
  state?: string | null;
  last_kind?: string | null;
  last_error?: string | null;
  last_ms?: number | null;
  models?: string[];
}
export interface AiKey {
  id: string;
  provider: string;
  label: string;
  masked: string;
  model: string;
  priority: number;
  status: "active" | "disabled";
  scope: "local" | "cloud";
  state: KeyState;
  base_url?: string | null;
  fallback_model?: string | null;
  timeout_s?: number | null;
}
export interface KeyInput {
  provider: string;
  label: string;
  key: string;
  base_url?: string;
  model?: string;
}
export interface KeyTest {
  ok: boolean;
  kind: string;
  detail: string;
  model?: string | null;
  models?: string[];
  ms?: number | null;
}
export interface LocalRow {
  provider: string;
  name: string;
  url: string;
  base_url: string;
  running: boolean;
  models: string[];
  model: string | null;
  fix: string | null;
  ms: number | null;
}
export interface Policy {
  order: string[];
  provider_fallback: boolean;
  attempts_per_key: number;
  timeout_s: number;
  backoff_s: number;
  cooldown_s: Record<string, number>;
  redact: boolean;
  prices: Record<string, Record<string, number[]>>;
}
export interface UsageRow {
  agent?: string;
  pipeline?: string | null;
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  estimated: boolean;
  last_at: string | null;
}
export interface Usage {
  month: string;
  prices_dated: string;
  total_usd: number;
  calls: number;
  estimated: boolean;
  agents: UsageRow[];
  runs: UsageRow[];
  budget: BudgetStatus;
}

const slugPath = (slug: string) => `/projects/${encodeURIComponent(slug)}/ai`;

export const aiApi = {
  catalog: () => request<Catalog>("/ai/catalog"),
  keys: () => request<AiKey[]>("/ai/keys"),
  addKey: (body: KeyInput) => request<AiKey>("/ai/keys", { method: "POST", body: JSON.stringify(body) }),
  patchKey: (id: string, body: Partial<Pick<AiKey, "label" | "status" | "model" | "priority">>) =>
    request<AiKey>(`/ai/keys/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteKey: (id: string) => request<{ deleted: string }>(`/ai/keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
  testKey: (id: string) => request<KeyTest>(`/ai/keys/${encodeURIComponent(id)}/test`, { method: "POST" }),
  local: () => request<LocalRow[]>("/ai/local"),
  policy: () => request<Policy>("/ai/policy"),
  putPolicy: (body: Partial<Policy>) => request<Policy>("/ai/policy", { method: "PUT", body: JSON.stringify(body) }),
  project: (slug: string) => request<ProjectAi>(slugPath(slug)),
  saveProject: (slug: string, body: AiSettingsInput) => request<ProjectAi>(slugPath(slug), { method: "PUT", body: JSON.stringify(body) }),
  usage: (slug: string) => request<Usage>(`${slugPath(slug)}/usage`),
};

const isMode = (v: unknown): v is AiMode => typeof v === "string" && (MODE_IDS as readonly string[]).includes(v);
export const isTier = (v: unknown): v is Tier => typeof v === "string" && (TIER_IDS as readonly string[]).includes(v);
const num = (v: unknown, fallback: number): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);

/** The message to show the owner: the API's own sentence, else the fallback (never a raw response body). */
export const errorText = (e: unknown, fallback: string): string => (e instanceof ApiError ? e.message : fallback);

/** A saved block (possibly partial or hand-edited) filled with the defaults; unknown values fall back. */
export function settingsFrom(saved: SavedAi | undefined): AiSettingsInput {
  const assignments: Record<string, Tier> = {};
  for (const [agent, tier] of Object.entries(saved?.assignments ?? {})) if (isTier(tier)) assignments[agent] = tier;
  return {
    mode: isMode(saved?.mode) ? saved.mode : DEFAULT_AI.mode,
    consent: { send_text: saved?.consent?.send_text === true, send_screenshots: saved?.consent?.send_screenshots === true },
    budget: {
      monthly_usd: num(saved?.budget?.monthly_usd, DEFAULT_AI.budget.monthly_usd),
      alert_at_pct: num(saved?.budget?.alert_at_pct, DEFAULT_AI.budget.alert_at_pct),
    },
    assignments,
    max_chunks: num(saved?.max_chunks, DEFAULT_AI.max_chunks),
  };
}

export function money(usd: number): string {
  if (usd > 0 && usd < 0.005) return "under $0.01";
  return `$${usd.toFixed(2)}`;
}

/** The budget as a level for colour and one sentence for the owner (mirrors agentqa.ai.budget.reason). */
export function capState(b: BudgetStatus): { level: "ok" | "warn" | "bad"; text: string } {
  if (b.state === "capped") {
    return { level: "bad", text: `The ${money(b.cap)} monthly budget is used up: cloud AI is off for this project until next month, or until the cap is raised` };
  }
  if (b.state === "warning") return { level: "warn", text: `${b.pct} % of the ${money(b.cap)} monthly budget is used` };
  return { level: "ok", text: `${money(b.spent)} of ${money(b.cap)} used this month` };
}

/** What would answer this agent: the reason there is no AI, the provider and model, or the scopes in order. */
export function routeLabel(row: EffectiveRow, names: Record<string, string>): string {
  if (row.reason) return row.reason;
  if (row.provider) return `${names[row.provider] ?? row.provider} · ${row.model ?? "auto"}`;
  return `the first ${row.scopes.join(", then ")} model that answers`;
}

/** The probe's rows as one line: the running server with a model, else the first fix, else "nothing found". */
export function localSummary(rows: LocalRow[]): { running: boolean; model: string | null; text: string } {
  const withModel = rows.find((r) => r.running && r.model);
  if (withModel) return { running: true, model: withModel.model, text: `${withModel.name} is running with ${withModel.model}` };
  const running = rows.find((r) => r.running);
  if (running) return { running: true, model: null, text: running.fix ?? `${running.name} is running but lists no model` };
  return { running: false, model: null, text: "No local AI found: Ollama and LM Studio are not running on this computer." };
}

export const trimSlash = (url: string | null | undefined): string => (url ?? "").replace(/\/+$/, "");
const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

function isLoopback(url: string): boolean {
  try {
    return LOOPBACK.has(new URL(url).hostname.toLowerCase());
  } catch {
    return false;
  }
}

/** Does a stored key already point at this probe row's server? */
export function hasKeyFor(row: LocalRow, keys: AiKey[]): boolean {
  return keys.some((k) => k.provider === row.provider && trimSlash(k.base_url) === trimSlash(row.base_url));
}

/** The key to store for a running local server with a model, when none is stored yet. Loopback addresses only:
 *  the probe is fixed to this computer, and this guard keeps it so even if the response were ever different. */
export function localKeyToAdd(rows: LocalRow[], keys: AiKey[]): KeyInput | null {
  const row = rows.find((r) => r.running && r.model && isLoopback(r.base_url) && !hasKeyFor(r, keys));
  return row ? { provider: row.provider, label: row.name, key: "", base_url: row.base_url, model: row.model ?? "auto" } : null;
}

/** The wizard's AI step on "Continue": a running local server becomes a key when Local or Hybrid was chosen (a failed
 *  probe is not fatal, the AI page can add it later; a refused key is), then the block is saved. */
export async function saveAiStep(slug: string, ai: AiSettingsInput): Promise<ProjectAi> {
  if (ai.mode === "local" || ai.mode === "hybrid") {
    const found = await Promise.all([aiApi.local(), aiApi.keys()]).catch(() => null);
    const add = found ? localKeyToAdd(found[0], found[1]) : null;
    if (add) await aiApi.addKey(add);
  }
  return aiApi.saveProject(slug, ai);
}

export function cloudKeyCount(keys: AiKey[]): number {
  return keys.filter((k) => k.scope === "cloud" && k.status === "active").length;
}

/** Azure and "OpenAI-compatible" have no usable default address: the owner types one. */
export function needsAddress(provider: ProviderInfo): boolean {
  return !provider.base_url || provider.base_url.includes("<");
}

export function moveInOrder(order: readonly string[], id: string, direction: -1 | 1): string[] {
  const from = order.indexOf(id);
  const to = from + direction;
  if (from < 0 || to < 0 || to >= order.length) return [...order];
  const next = [...order];
  next.splice(from, 1);
  next.splice(to, 0, id);
  return next;
}
