import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { fail, sentBody, stubFetch } from "../../test-fetch";
import { AiSettings } from "./AiSettings";

const PROJECT = { slug: "demo", name: "Demo portal", url: "http://127.0.0.1:8800" };
const EFFECTIVE = [
  { agent: "req_writer", label: "Requirement Writer", tier: "strong", scopes: [], image: false, provider: null, model: null, reason: "AI is off for this project" },
  { agent: "triage", label: "Defect title polish", tier: "cheap", scopes: [], image: false, provider: null, model: null, reason: "AI is off for this project" },
];
const PROJECT_AI = {
  settings: { mode: "none", consent: { send_text: false, send_screenshots: false }, budget: { monthly_usd: 10, alert_at_pct: 80 }, assignments: {}, max_chunks: 40 },
  effective: EFFECTIVE, notice: null, budget: { month: "2026-11", spent: 0, cap: 10, pct: 0, alert_at_pct: 80, state: "ok" },
};
const CATALOG = {
  providers: [{ id: "anthropic", name: "Anthropic Claude", family: "anthropic", base_url: "https://a.example", vision: true, keyless: false, local: false, tiers: {} }],
  tiers: ["cheap", "balanced", "strong", "vision"],
  agents: [{ agent: "req_writer", label: "Requirement Writer", tier: "strong", image: "none" }, { agent: "triage", label: "Defect title polish", tier: "cheap", image: "none" }],
};
const USAGE = { month: "2026-11", prices_dated: "2026-11-03", total_usd: 0, calls: 0, estimated: false, agents: [], runs: [], budget: PROJECT_AI.budget };
const LOCAL = [{ provider: "ollama", name: "Ollama (local)", url: "u", base_url: "http://127.0.0.1:11434", running: false, models: [], model: null, fix: "Ollama is not running on this computer.", ms: null }];
const POLICY = { order: ["anthropic"], provider_fallback: true, attempts_per_key: 2, timeout_s: 60, backoff_s: 1, cooldown_s: {}, redact: true, prices: {} };

const RUNNING = [{ ...LOCAL[0], running: true, models: ["qwen3:4b"], model: "qwen3:4b", fix: null, ms: 9 }];

function mount(routes = {}) {
  const fetch = stubFetch({
    "GET /projects/demo": PROJECT,
    "GET /projects/demo/ai": PROJECT_AI,
    "PUT /projects/demo/ai": (init: RequestInit) => ({ ...PROJECT_AI, settings: JSON.parse(String(init.body)) }),
    "GET /projects/demo/ai/usage": USAGE,
    "GET /ai/catalog": CATALOG,
    "GET /ai/keys": [],
    "GET /ai/local": LOCAL,
    "GET /ai/policy": POLICY,
    ...routes,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/demo/ai"]}>
        <Routes>
          <Route path="/projects/:slug/ai" element={<AiSettings />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AiSettings", () => {
  it("loads the saved mode, the effective table and the month's spend", async () => {
    mount();
    expect(await screen.findByRole("heading", { level: 1, name: /AI for Demo portal/ })).toBeInTheDocument();
    expect(await screen.findByRole("radio", { name: /^No AI/ })).toBeChecked();
    const table = await screen.findByRole("table", { name: "Which model answers each agent" });
    expect(within(table).getAllByText("AI is off for this project")).toHaveLength(2);
    expect(await screen.findByText("$0.00 of $10.00 used this month")).toBeInTheDocument();
    expect(screen.getByText("Ollama is not running on this computer.")).toBeInTheDocument();
  });

  it("saves the mode, consent, budget and assignments in one request and shows the result", async () => {
    const fetch = mount();
    fireEvent.click(await screen.findByRole("radio", { name: /^Cloud AI/ }));
    fireEvent.click(screen.getByLabelText(/Allow text/));
    fireEvent.change(screen.getByLabelText(/Monthly budget/), { target: { value: "5" } });
    fireEvent.change(await screen.findByLabelText("Tier for Defect title polish"), { target: { value: "off" } });
    fireEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
    await waitFor(() =>
      expect(sentBody(fetch, "PUT", "/projects/demo/ai")).toEqual({
        mode: "cloud", consent: { send_text: true, send_screenshots: false }, budget: { monthly_usd: 5, alert_at_pct: 80 }, assignments: { triage: "off" }, max_chunks: 40,
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(/Saved/);
    expect(screen.getByRole("button", { name: "Save AI settings" })).toBeDisabled();
  });

  it("keeps the draft and says why when the save fails; Save stays enabled only while something differs", async () => {
    mount({ "PUT /projects/demo/ai": fail(422, "validation", "budget.monthly_usd must be between 0.5 and 1000") });
    const save = await screen.findByRole("button", { name: "Save AI settings" });
    expect(save).toBeDisabled();
    fireEvent.click(await screen.findByRole("radio", { name: /^Cloud AI/ }));
    expect(save).toBeEnabled();
    fireEvent.click(screen.getByRole("radio", { name: /^No AI/ }));            // back to what is saved: nothing to save
    expect(save).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: /^Cloud AI/ }));
    fireEvent.click(save);
    expect(await screen.findByRole("alert")).toHaveTextContent("monthly_usd");
    expect(screen.getByRole("radio", { name: /^Cloud AI/ })).toBeChecked();      // the draft survives
    expect(save).toBeEnabled();
  });

  it("stores a running local server as a key with its fixed address from 'Use it'", async () => {
    const fetch = mount({ "GET /ai/local": RUNNING, "POST /ai/keys": { id: "k9", provider: "ollama", label: "Ollama (local)", masked: "(none)", model: "qwen3:4b", priority: 10, status: "active", scope: "local", state: {} } });
    fireEvent.click(await screen.findByRole("button", { name: "Use it" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/ai/keys")).toEqual({ provider: "ollama", label: "Ollama (local)", key: "", base_url: "http://127.0.0.1:11434", model: "qwen3:4b" }));
  });

  it("says when a list could not be loaded instead of loading forever, and keeps the page on a bad refetch", async () => {
    mount({ "GET /ai/catalog": fail(500, "server", "catalogue broken") });
    expect(await screen.findByText(/agent list could not be loaded/)).toBeInTheDocument();
    expect(screen.getByText(/provider list could not be loaded/)).toBeInTheDocument();
    cleanup();
    vi.unstubAllGlobals();
    mount({ "GET /projects/demo": fail(500, "server", "database locked") });
    expect(await screen.findByRole("alert")).toHaveTextContent("database locked");
    expect(screen.queryByText(/does not exist/)).toBeNull();
  });
});
