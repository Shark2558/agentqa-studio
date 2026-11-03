import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AiKey } from "../../lib/ai";
import { fail, sentBody, stubFetch } from "../../test-fetch";
import { KeyRow } from "./KeyRow";

const key = (over: Partial<AiKey>): AiKey => ({ id: "k1", provider: "openai", label: "Work key", masked: "sk-p…cdef", model: "auto", priority: 10, status: "active", scope: "cloud", state: {}, ...over });

function mount(k: AiKey, routes = {}) {
  const fetch = stubFetch({ "GET /ai/keys": [k], ...routes });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ul>
        <KeyRow k={k} providerName="OpenAI" />
      </ul>
    </QueryClientProvider>,
  );
  return fetch;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("KeyRow", () => {
  it("names each backend state in the owner's words; a new key is 'Not tested yet', not a failure", () => {
    mount(key({ state: { state: "untested" } }));
    expect(screen.getByText("Not tested yet")).toHaveClass("neutral");
    cleanup();
    mount(key({ state: { state: "ok" } }));
    expect(screen.getByText("Working")).toHaveClass("ok");
    cleanup();
    mount(key({ state: { state: "cooling" } }));
    expect(screen.getByText("Resting after an error")).toHaveClass("warn");
    cleanup();
    mount(key({ state: { state: "invalid_key", last_error: "HTTP 401" } }));
    expect(screen.getByText("Key rejected")).toHaveClass("bad");
    expect(screen.getByText("HTTP 401")).toBeInTheDocument();
    cleanup();
    mount(key({ status: "disabled", state: { state: "ok" } }));
    expect(screen.getByText("Disabled")).toHaveClass("neutral");
  });

  it("says so when Disable fails instead of doing nothing", async () => {
    mount(key({}), { "PATCH /ai/keys/k1": fail(500, "server", "The vault is locked") });
    fireEvent.click(screen.getByRole("button", { name: "Disable Work key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The vault is locked");
  });

  it("asks before deleting, deletes only on yes, and reports a failed delete", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetch = mount(key({}), { "DELETE /ai/keys/k1": fail(404, "not_found", "No such key") });
    fireEvent.click(screen.getByRole("button", { name: "Delete Work key" }));
    expect(sentBody(fetch, "DELETE", "/ai/keys/k1")).toBeUndefined();
    expect(fetch.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete Work key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No such key");
    expect(fetch.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true);
  });

  it("drops a stale test result when the key is changed afterwards", async () => {
    mount(key({}), { "POST /ai/keys/k1/test": { ok: true, kind: "ok", detail: "fine", model: "gpt-4o-mini", models: [], ms: 12 }, "PATCH /ai/keys/k1": key({ status: "disabled" }) });
    fireEvent.click(screen.getByRole("button", { name: "Test Work key" }));
    expect(await screen.findByText(/OK · gpt-4o-mini/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disable Work key" }));
    await waitFor(() => expect(screen.queryByText(/OK · gpt-4o-mini/)).toBeNull());
  });
});
