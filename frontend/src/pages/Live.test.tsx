import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { Live } from "./Live";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  url: string;
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(cb);
  }
  emit(type: string, data?: unknown) {
    for (const cb of this.listeners[type] ?? []) cb(new MessageEvent(type, { data: typeof data === "string" ? data : JSON.stringify(data) }));
  }
  close() {
    this.closed = true;
  }
}
const last = () => FakeEventSource.instances[FakeEventSource.instances.length - 1];
const RUN = { id: "job-1-pipeline", label: "run 1", running: true, when: "now", shots: 0 };
const ev = (seq: number, agent: string, kind: string, title: string, level?: string) => ({ t: 1700000000 + seq, seq, w: "main", agent, kind, title, level });

function respond(status: number, body: unknown, delayMs = 0) {
  return new Promise<Response>((resolve) =>
    setTimeout(() => resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })), delayMs),
  );
}

function mount(sessions: () => Promise<Response>, path = "/projects/demo/live") {
  vi.stubGlobal("fetch", vi.fn(sessions));
  vi.stubGlobal("EventSource", FakeEventSource);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
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

describe("Live: states before any event", () => {
  it("shows a skeleton board and says it is loading while the runs load; the header does not claim 'No run yet'", () => {
    mount(() => respond(200, { ok: true, data: [] }, 50));
    expect(screen.getByRole("region", { name: "Agents" })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent(/Loading/);
    expect(screen.queryByText(/No run yet/)).toBeNull();
  });

  it("with no run yet, says so once, links to the project page and hides the run selector", async () => {
    mount(() => respond(200, { ok: true, data: [] }));
    const link = await screen.findByRole("link", { name: /project page/ });
    expect(link).toHaveAttribute("href", "/projects/demo");
    expect(screen.queryByRole("combobox", { name: /Run/ })).toBeNull();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("with a run but no events yet, waits for the first event and streams that run", async () => {
    mount(() => respond(200, { ok: true, data: [RUN] }));
    await waitFor(() => expect(screen.getByText(/Waiting for the first event/)).toBeVisible());
    expect(screen.getByRole("combobox", { name: /Run/ })).toHaveValue("job-1-pipeline");
    expect(last().url).toContain("/live/job-1-pipeline/stream");
  });

  it("falls back to the newest listed run when the URL names one that does not exist", async () => {
    mount(() => respond(200, { ok: true, data: [RUN] }), "/projects/demo/live?session=job-999-gone");
    await waitFor(() => expect(last().url).toContain("/live/job-1-pipeline/stream"));
    expect(screen.getByRole("combobox", { name: /Run/ })).toHaveValue("job-1-pipeline");
  });

  it("tells the person when the runs could not be loaded", async () => {
    mount(() => respond(500, { ok: false, error: { code: "server", message: "boom" } }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/could not be loaded/));
    expect(screen.queryByText(/No run yet/)).toBeNull();
  });
});

describe("Live: the stream", () => {
  async function streaming() {
    mount(() => respond(200, { ok: true, data: [RUN] }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    return last();
  }

  it("builds the board from events, marks only later changes, and shows failures with a glyph and a word", async () => {
    const source = await streaming();
    act(() => source.emit("live", { events: [ev(1, "srs", "stage_start", "analyze started"), ev(2, "srs", "stage_end", "analyze done")], cursor: "c1" }));
    const board = screen.getByRole("region", { name: "Agents" });
    const card = within(board).getByText("srs").closest(".agent")!;
    expect(card).toHaveClass("done");
    expect(card).not.toHaveClass("changed");                              // history: shown quietly
    act(() => source.emit("live", { events: [ev(3, "executor", "stage_start", "run started"), ev(4, "executor", "stage_end", "run failed", "bad")], cursor: "c2" }));
    expect(within(board).getByText("executor").closest(".agent")).toHaveClass("failed", "changed");
    const log = screen.getByRole("log", { name: /Live events/ });
    expect(log).toHaveAttribute("aria-live", "off");
    const failed = within(log).getByText("run failed").closest(".evt") as HTMLElement;
    expect(failed).toHaveClass("fail");
    expect(within(failed).getByText("Failed")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/executor.*Failed/);
  });

  it("ignores a malformed frame and a frame without an events list", async () => {
    const source = await streaming();
    act(() => source.emit("live", "{truncated"));
    act(() => source.emit("live", { nope: 1 }));
    act(() => source.emit("live", { events: [ev(1, "srs", "stage_start", "ok")], cursor: "c1" }));
    expect(within(screen.getByRole("region", { name: "Agents" })).getByText("srs")).toBeInTheDocument();
  });

  it("after a dropped connection, says so, reconnects from the last cursor and never shows an event twice", async () => {
    const source = await streaming();
    act(() => source.emit("live", { events: [ev(1, "srs", "stage_start", "analyze started")], cursor: "c1" }));
    vi.useFakeTimers();
    try {
      act(() => source.emit("error"));
      expect(screen.getByRole("alert")).toHaveTextContent(/Connection lost/);
      expect(source.closed).toBe(true);
      act(() => {
        vi.advanceTimersByTime(3000);
      });
      expect(FakeEventSource.instances).toHaveLength(2);
      expect(last().url).toContain("cursor=c1");
      act(() => last().emit("live", { events: [ev(1, "srs", "stage_start", "analyze started"), ev(2, "srs", "stage_end", "analyze done")], cursor: "c2" }));
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getAllByText("analyze started")).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("says when a run ended without any event", async () => {
    const source = await streaming();
    act(() => source.emit("end"));
    expect(screen.getByText(/ended without any event/)).toBeVisible();
  });
});
