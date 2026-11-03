import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_AI, type AiKey, type BudgetStatus, type EffectiveRow, type LocalRow, capState, cloudKeyCount, localSummary, money, moveInOrder,
  localKeyToAdd, needsAddress, routeLabel, saveAiStep, settingsFrom,
} from "./ai";
import { fail, sentBody, stubFetch } from "../test-fetch";

afterEach(() => vi.unstubAllGlobals());

const budget = (over: Partial<BudgetStatus>): BudgetStatus => ({ month: "2026-11", spent: 0.42, cap: 10, pct: 4, alert_at_pct: 80, state: "ok", ...over });
const row = (over: Partial<EffectiveRow>): EffectiveRow => ({ agent: "triage", label: "Defect title polish", tier: "cheap", scopes: [], image: false, provider: null, model: null, reason: null, ...over });
const local = (over: Partial<LocalRow>): LocalRow => ({ provider: "ollama", name: "Ollama (local)", url: "http://127.0.0.1:11434/api/tags", base_url: "http://127.0.0.1:11434", running: false, models: [], model: null, fix: "Ollama is not running on this computer.", ms: null, ...over });
const key = (over: Partial<AiKey>): AiKey => ({ id: "k1", provider: "openai", label: "Work", masked: "sk-p…cdef", model: "auto", priority: 10, status: "active", scope: "cloud", state: {}, ...over });

describe("ai settings helpers", () => {
  it("fills a saved block with the defaults: No AI, $10 cap, 80 % warning, consent off", () => {
    expect(settingsFrom(undefined)).toEqual(DEFAULT_AI);
    const s = settingsFrom({ mode: "cloud", budget: { monthly_usd: 5 } });
    expect(s.mode).toBe("cloud");
    expect(s.budget).toEqual({ monthly_usd: 5, alert_at_pct: 80 });
    expect(s.consent).toEqual({ send_text: false, send_screenshots: false });
    expect(s.assignments).toEqual({});
    expect(settingsFrom({ mode: "turbo", assignments: { triage: "huge", casegen: "cheap" } })).toMatchObject({ mode: "none", assignments: { casegen: "cheap" } });
    expect(DEFAULT_AI.budget.monthly_usd).toBe(10);
  });

  it("formats money for the owner", () => {
    expect(money(0)).toBe("$0.00");
    expect(money(0.4199)).toBe("$0.42");
    expect(money(0.004)).toBe("under $0.01");
    expect(money(12)).toBe("$12.00");
  });

  it("turns the budget state into a level and a sentence", () => {
    expect(capState(budget({}))).toEqual({ level: "ok", text: "$0.42 of $10.00 used this month" });
    const warn = capState(budget({ spent: 8.2, pct: 82, state: "warning" }));
    expect(warn.level).toBe("warn");
    expect(warn.text).toContain("82 %");
    expect(warn.text).toContain("$10.00");
    const capped = capState(budget({ spent: 10, pct: 100, state: "capped" }));
    expect(capped.level).toBe("bad");
    expect(capped.text).toMatch(/used up/);
  });

  it("labels a route: the reason wins, then provider · model, else the scopes", () => {
    expect(routeLabel(row({ reason: "AI is off for this project" }), {})).toBe("AI is off for this project");
    expect(routeLabel(row({ provider: "anthropic", model: "claude-opus-5-5", scopes: ["cloud"] }), { anthropic: "Anthropic Claude" })).toBe("Anthropic Claude · claude-opus-5-5");
    expect(routeLabel(row({ provider: "mystery", model: null, scopes: ["cloud"] }), {})).toBe("mystery · auto");
    expect(routeLabel(row({ scopes: ["cloud", "local"] }), {})).toBe("the first cloud, then local model that answers");
  });

  it("summarises the local probe in one honest line", () => {
    expect(localSummary([local({}), local({ provider: "lmstudio", name: "LM Studio (local)" })])).toEqual({
      running: false, model: null, text: "No local AI found: Ollama and LM Studio are not running on this computer." });
    expect(localSummary([local({ running: true, models: ["qwen3:4b", "llava"], model: "qwen3:4b", fix: null })])).toEqual({
      running: true, model: "qwen3:4b", text: "Ollama (local) is running with qwen3:4b" });
    const noModel = local({ running: true, fix: "Ollama is running but no model is pulled. Open a terminal and run: ollama pull qwen3:4b" });
    expect(localSummary([noModel])).toEqual({ running: true, model: null, text: noModel.fix });
  });

  it("counts only enabled cloud keys", () => {
    expect(cloudKeyCount([key({}), key({ id: "k2", scope: "local", provider: "ollama" }), key({ id: "k3", status: "disabled" })])).toBe(1);
  });

  it("knows which providers need an address typed in", () => {
    const p = (id: string, base_url: string) => ({ id, name: id, family: "openai", base_url, vision: false, keyless: false, local: false, tiers: {} });
    expect(needsAddress(p("azure_openai", "https://<resource>.openai.azure.com"))).toBe(true);
    expect(needsAddress(p("openai_compatible", ""))).toBe(true);
    expect(needsAddress(p("openai", "https://api.openai.com/v1"))).toBe(false);
  });

  it("moves a provider in the order without mutating it and stops at the ends", () => {
    const order = ["gemini", "openai", "anthropic"];
    expect(moveInOrder(order, "anthropic", -1)).toEqual(["gemini", "anthropic", "openai"]);
    expect(moveInOrder(order, "gemini", -1)).toEqual(order);
    expect(moveInOrder(order, "anthropic", 1)).toEqual(order);
    expect(order).toEqual(["gemini", "openai", "anthropic"]);
  });
});

describe("localKeyToAdd", () => {
  const running = local({ running: true, models: ["qwen3:4b"], model: "qwen3:4b", fix: null });
  it("offers the running server's fixed address when no key for it is stored yet", () => {
    expect(localKeyToAdd([running, local({ provider: "lmstudio" })], [])).toEqual({ provider: "ollama", label: "Ollama (local)", key: "", base_url: "http://127.0.0.1:11434", model: "qwen3:4b" });
  });
  it("offers nothing when the server is down, lists no model, or is already a key", () => {
    expect(localKeyToAdd([local({})], [])).toBeNull();
    expect(localKeyToAdd([local({ running: true })], [])).toBeNull();
    expect(localKeyToAdd([running], [key({ id: "k9", provider: "ollama", scope: "local", base_url: "http://127.0.0.1:11434/" })])).toBeNull();
  });
});

describe("localKeyToAdd: loopback only", () => {
  it("refuses a probe row whose address is not this computer", () => {
    const far = local({ running: true, models: ["m"], model: "m", fix: null, base_url: "http://10.0.0.5:11434" });
    expect(localKeyToAdd([far], [])).toBeNull();
  });
});

describe("saveAiStep: what the wizard does when the AI step is saved", () => {
  const running = { provider: "ollama", name: "Ollama (local)", url: "u", base_url: "http://127.0.0.1:11434", running: true, models: ["qwen3:4b"], model: "qwen3:4b", fix: null, ms: 5 };
  const ollamaKey = { id: "k9", provider: "ollama", label: "Ollama (local)", masked: "(none)", model: "qwen3:4b", priority: 10, status: "active", scope: "local", state: {}, base_url: "http://127.0.0.1:11434" };
  const saved = (init: RequestInit) => ({ settings: JSON.parse(String(init.body)), effective: [], notice: null, budget: {} });
  const order = (fetch: ReturnType<typeof stubFetch>) => fetch.mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${String(url).replace("/api/v1", "")}`);

  it("Local with a running model: stores the loopback key first, then the block", async () => {
    const fetch = stubFetch({ "GET /ai/local": [running], "GET /ai/keys": [], "POST /ai/keys": ollamaKey, "PUT /projects/p/ai": saved });
    await saveAiStep("p", { ...DEFAULT_AI, mode: "local" });
    expect(order(fetch).filter((c) => !c.startsWith("GET"))).toEqual(["POST /ai/keys", "PUT /projects/p/ai"]);
    expect(sentBody(fetch, "POST", "/ai/keys")).toMatchObject({ provider: "ollama", base_url: "http://127.0.0.1:11434", key: "" });
  });

  it("Local with the key already stored, and Cloud, add nothing", async () => {
    let fetch = stubFetch({ "GET /ai/local": [running], "GET /ai/keys": [ollamaKey], "PUT /projects/p/ai": saved });
    await saveAiStep("p", { ...DEFAULT_AI, mode: "local" });
    expect(order(fetch)).not.toContain("POST /ai/keys");
    vi.unstubAllGlobals();
    fetch = stubFetch({ "PUT /projects/p/ai": saved });
    await saveAiStep("p", { ...DEFAULT_AI, mode: "cloud" });
    expect(order(fetch)).toEqual(["PUT /projects/p/ai"]);
  });

  it("a failed probe does not block the save; a failed key store does", async () => {
    let fetch = stubFetch({ "GET /ai/local": fail(500, "server", "probe broke"), "GET /ai/keys": [], "PUT /projects/p/ai": saved });
    await saveAiStep("p", { ...DEFAULT_AI, mode: "hybrid" });
    expect(order(fetch)).toContain("PUT /projects/p/ai");
    vi.unstubAllGlobals();
    fetch = stubFetch({ "GET /ai/local": [running], "GET /ai/keys": [], "POST /ai/keys": fail(422, "validation", "base_url: refused"), "PUT /projects/p/ai": saved });
    await expect(saveAiStep("p", { ...DEFAULT_AI, mode: "local" })).rejects.toMatchObject({ message: "base_url: refused" });
    expect(order(fetch)).not.toContain("PUT /projects/p/ai");
  });
});
