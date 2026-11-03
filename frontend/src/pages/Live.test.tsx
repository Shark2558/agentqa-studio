import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { Live } from "./Live";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(cb);
  }
  close() {}
}

function respond(status: number, body: unknown, delayMs = 0) {
  return new Promise<Response>((resolve) =>
    setTimeout(() => resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })), delayMs),
  );
}

function mount(sessions: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(sessions));
  vi.stubGlobal("EventSource", FakeEventSource);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/demo/live"]}>
        <Routes>
          <Route path="/projects/:slug/live" element={<Live />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  FakeEventSource.instances = [];
});

describe("Live", () => {
  it("shows a skeleton board while the runs are loading", () => {
    mount(() => respond(200, { ok: true, data: [] }, 50));
    expect(screen.getByRole("region", { name: "Agents" })).toHaveAttribute("aria-busy", "true");
  });

  it("with no run yet, says so, links to the project page and hides the run selector", async () => {
    mount(() => respond(200, { ok: true, data: [] }));
    const link = await screen.findByRole("link", { name: /project page/ });     // the header says "No run yet" even while loading
    expect(link).toHaveAttribute("href", "/projects/demo");
    expect(screen.getByText(/No run yet\. Start one/)).toBeVisible();
    expect(screen.queryByRole("combobox", { name: "Run" })).toBeNull();
    expect(FakeEventSource.instances).toHaveLength(0);                      // nothing to stream
  });

  it("with a run but no events yet, waits for the first event", async () => {
    mount(() => respond(200, { ok: true, data: [{ id: "job-1-pipeline", label: "run 1", running: true, when: "now", shots: 0 }] }));
    await waitFor(() => expect(screen.getByText(/Waiting for the first event/)).toBeVisible());
    expect(screen.getByRole("combobox", { name: "Run" })).toHaveValue("job-1-pipeline");
    expect(FakeEventSource.instances[0].url).toContain("/live/job-1-pipeline/stream");
  });

  it("tells the person when the runs could not be loaded", async () => {
    mount(() => respond(500, { ok: false, error: { code: "server", message: "boom" } }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/could not be loaded/));
  });
});
