import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { DEFAULT_AI, type AiSettingsInput } from "../../lib/ai";
import { stubFetch } from "../../test-fetch";
import { StepAi } from "./StepAi";

const OLLAMA = { provider: "ollama", name: "Ollama (local)", url: "http://127.0.0.1:11434/api/tags", base_url: "http://127.0.0.1:11434", running: true, models: ["qwen3:4b"], model: "qwen3:4b", fix: null, ms: 12 };
const LMS = { ...OLLAMA, provider: "lmstudio", name: "LM Studio (local)", running: false, models: [], model: null, fix: "LM Studio is not running." };
const KEYS = [
  { id: "k1", provider: "anthropic", label: "Claude", masked: "sk-a…wxyz", model: "auto", priority: 10, status: "active", scope: "cloud", state: {} },
  { id: "k2", provider: "ollama", label: "Ollama", masked: "(none)", model: "qwen3:4b", priority: 10, status: "active", scope: "local", state: {} },
];

function mount(ai: AiSettingsInput, onChange = vi.fn()) {
  stubFetch({ "GET /ai/local": [OLLAMA, LMS], "GET /ai/keys": KEYS });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StepAi slug="demo" ai={ai} onChange={onChange} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onChange;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StepAi", () => {
  it("offers the four modes; consent and budget stay hidden under No AI and Local AI", () => {
    mount(DEFAULT_AI);
    for (const name of ["No AI", "Local AI", "Cloud AI", "Hybrid"]) expect(screen.getByRole("radio", { name: new RegExp(`^${name}`) })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^No AI/ })).toBeChecked();
    expect(screen.queryByLabelText(/Allow text/)).toBeNull();
    expect(screen.queryByLabelText(/Monthly budget/)).toBeNull();
    cleanup();
    mount({ ...DEFAULT_AI, mode: "local" });
    expect(screen.queryByLabelText(/Allow text/)).toBeNull();
  });

  it("under Cloud AI shows the consent boxes, the default $10 budget and the 80 % warning, and says what no consent means", () => {
    mount({ ...DEFAULT_AI, mode: "cloud" });
    expect(screen.getByLabelText(/Allow text/)).not.toBeChecked();
    expect(screen.getByLabelText(/Allow screenshots/)).not.toBeChecked();
    expect(screen.getByLabelText(/Monthly budget/)).toHaveValue(10);
    expect(screen.getByLabelText(/Warn me at/)).toHaveValue(80);
    expect(screen.getByText(/no cloud call is made/)).toBeInTheDocument();
  });

  it("reports every change upward without touching the previous value", () => {
    const ai = { ...DEFAULT_AI, mode: "cloud" as const };
    const onChange = mount(ai);
    fireEvent.click(screen.getByRole("radio", { name: /^Hybrid/ }));
    expect(onChange).toHaveBeenLastCalledWith({ ...ai, mode: "hybrid" });
    fireEvent.click(screen.getByLabelText(/Allow text/));
    expect(onChange).toHaveBeenLastCalledWith({ ...ai, consent: { send_text: true, send_screenshots: false } });
    fireEvent.change(screen.getByLabelText(/Monthly budget/), { target: { value: "5" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...ai, budget: { monthly_usd: 5, alert_at_pct: 80 } });
    expect(ai.mode).toBe("cloud");
  });

  it("tells the truth about the local model and the cloud keys, with a link to the AI page", async () => {
    mount(DEFAULT_AI);
    expect(await screen.findByText(/Ollama \(local\) is running with qwen3:4b/)).toBeInTheDocument();
    expect(await screen.findByText(/1 cloud key set up/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /AI providers/ });
    expect(link).toHaveAttribute("href", "/projects/demo/ai");
    expect(link).toHaveAttribute("target", "_blank");                           // the wizard's state lives only on this page
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("names each radio by its title only, forgets consent when AI leaves the cloud, and ignores an emptied budget box", () => {
    const ai = { ...DEFAULT_AI, mode: "cloud" as const, consent: { send_text: true, send_screenshots: true } };
    const onChange = mount(ai);
    expect(screen.getByRole("radio", { name: "Cloud AI" })).toBeChecked();
    fireEvent.change(screen.getByLabelText(/Monthly budget/), { target: { value: "" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("radio", { name: "No AI" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...ai, mode: "none", consent: { send_text: false, send_screenshots: false } });
  });
});
