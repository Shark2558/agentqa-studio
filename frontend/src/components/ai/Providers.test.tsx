import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { aiApi, type AiKey, type Catalog, type Policy } from "../../lib/ai";
import { fail, sentBody, stubFetch } from "../../test-fetch";
import { Providers } from "./Providers";

const SECRET = "TEST-NOT-A-KEY-0000";
const KEYS: AiKey[] = [{ id: "k1", provider: "openai", label: "Work key", masked: "sk-p…cdef", model: "auto", priority: 10, status: "active", scope: "cloud", state: { state: "ok", last_kind: "ok" } }];
const CATALOG: Catalog = {
  providers: [
    { id: "gemini", name: "Google Gemini", family: "gemini", base_url: "https://g.example", vision: true, keyless: false, local: false, tiers: {} },
    { id: "anthropic", name: "Anthropic Claude", family: "anthropic", base_url: "https://a.example", vision: true, keyless: false, local: false, tiers: {} },
    { id: "openai", name: "OpenAI", family: "openai", base_url: "https://o.example", vision: true, keyless: false, local: false, tiers: {} },
    { id: "azure_openai", name: "Azure OpenAI", family: "azure", base_url: "https://<resource>.openai.azure.com", vision: true, keyless: false, local: false, tiers: {} },
  ],
  tiers: ["cheap", "balanced", "strong", "vision"],
  agents: [],
};
const POLICY: Policy = { order: ["gemini", "anthropic", "openai"], provider_fallback: true, attempts_per_key: 2, timeout_s: 60, backoff_s: 1, cooldown_s: {}, redact: true, prices: {} };
const CATALOG_WITH_LOCAL: Catalog = { ...CATALOG, providers: [...CATALOG.providers, { id: "ollama", name: "Ollama (local)", family: "ollama", base_url: "http://127.0.0.1:11434", vision: false, keyless: true, local: true, tiers: {} }] };

/** As the page mounts it: the policy comes from the query cache, so a saved order re-renders the list. */
function Host({ catalog = CATALOG }: { catalog?: Catalog }) {
  const policy = useQuery({ queryKey: ["ai", "policy"], queryFn: aiApi.policy });
  return policy.data ? <Providers keys={KEYS} catalog={catalog} policy={policy.data} /> : <p>loading</p>;
}

function mount(routes = {}, catalog = CATALOG) {
  const fetch = stubFetch({
    "POST /ai/keys": (init: RequestInit) => ({ ...KEYS[0], id: "k2", label: JSON.parse(String(init.body)).label, masked: "sk-p…cdef" }),
    "POST /ai/keys/k1/test": { ok: true, kind: "ok", detail: "fine", model: "gpt-4o-mini", models: ["gpt-4o-mini"], ms: 320 },
    "PUT /ai/policy": (init: RequestInit) => ({ ...POLICY, ...JSON.parse(String(init.body)) }),
    "GET /ai/policy": POLICY,
    "GET /ai/keys": KEYS,
    ...routes,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Host catalog={catalog} />
    </QueryClientProvider>,
  );
  return fetch;
}

const pageText = () => document.body.textContent ?? "";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Providers", () => {
  it("shows each key masked, with its provider and health", async () => {
    mount();
    expect(await screen.findByText("sk-p…cdef")).toBeInTheDocument();
    expect(screen.getByText("Work key")).toBeInTheDocument();
    expect(screen.getByText("Working")).toBeInTheDocument();
  });

  it("adds a key through a password box that never autocompletes and is emptied after saving; the address box appears only for providers without one", async () => {
    const fetch = mount();
    const keyBox = await screen.findByLabelText("API key");
    expect(keyBox).toHaveAttribute("type", "password");
    expect(keyBox).toHaveAttribute("autocomplete", "new-password");
    expect(screen.queryByLabelText("Service address")).toBeNull();
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "azure_openai" } });
    expect(screen.getByLabelText("Service address")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "openai" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Second key" } });
    fireEvent.change(keyBox, { target: { value: SECRET } });
    expect(pageText()).not.toContain(SECRET);
    fireEvent.click(screen.getByRole("button", { name: "Add key" }));
    await waitFor(() => expect(keyBox).toHaveValue(""));
    expect(sentBody(fetch, "POST", "/ai/keys")).toMatchObject({ provider: "openai", label: "Second key", key: SECRET });
    expect(pageText()).not.toContain(SECRET);
    expect(screen.getByRole("status")).toHaveTextContent(/Key stored/);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });       // typing again clears the old message
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("empties the key box after a failed save too, and shows why", async () => {
    mount({ "POST /ai/keys": fail(422, "validation", "key: this provider needs an API key") });
    const keyBox = await screen.findByLabelText("API key");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Bad" } });
    fireEvent.change(keyBox, { target: { value: SECRET } });
    fireEvent.click(screen.getByRole("button", { name: "Add key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("needs an API key");
    expect(keyBox).toHaveValue("");
  });

  it("sends no key for a keyless local provider, even if one was typed before switching", async () => {
    const fetch = mount({}, CATALOG_WITH_LOCAL);
    const keyBox = await screen.findByLabelText("API key");
    fireEvent.change(keyBox, { target: { value: SECRET } });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "ollama" } });
    expect(keyBox).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Ollama" } });
    fireEvent.click(screen.getByRole("button", { name: "Add key" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/ai/keys")).toMatchObject({ provider: "ollama", key: "" }));
  });

  it("tests a key and shows the outcome in words", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Test Work key" }));
    expect(await screen.findByText(/OK · gpt-4o-mini/)).toBeInTheDocument();
  });

  it("moves a provider up in the order the gateway tries and shows the new order", async () => {
    const fetch = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Move Anthropic Claude up" }));
    await waitFor(() => expect(sentBody(fetch, "PUT", "/ai/policy")).toEqual({ order: ["anthropic", "gemini", "openai"] }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Move Anthropic Claude up" })).toBeDisabled());
    const names = within(screen.getByRole("list", { name: "Provider order" })).getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(names[0]).toContain("Anthropic Claude");
    expect(names[1]).toContain("Google Gemini");
  });
});
