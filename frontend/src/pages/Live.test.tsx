import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { stubFetch } from "../test-fetch";
import { FakeSocket } from "../test-fixtures/fakeSocket";
import { demoBoard, demoEvents } from "../test-fixtures/live";
import { Live } from "./Live";

const RUN = { id: "cli-fixture-pipeline", label: "Command line: pipeline", running: false, when: "03 Nov 13:36", has_events: true };
const FINISHED = [{ type: "live", events: demoEvents, cursor: "c1" }, { type: "end", cursor: "c1", reason: "finished" }];

function mount(role = "owner", sessions: unknown[] = [RUN], path = "/projects/demo/live") {
  stubFetch({ "GET /auth/me": { email: "o@example.com", role }, "GET /projects/demo/live/sessions": sessions, "GET /projects/demo/live/board": demoBoard });
  vi.stubGlobal("WebSocket", FakeSocket);
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

async function socket(n = 1): Promise<FakeSocket> {
  await waitFor(() => expect(FakeSocket.all.length).toBe(n));
  return FakeSocket.all[n - 1];
}

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  FakeSocket.all = [];
});

describe("Live View: before a run", () => {
  it("says there is no run yet and offers the project page to someone who may start runs", async () => {
    mount("owner", []);
    expect(await screen.findByText(/No run yet\. Start one/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Go to the project page/ })).toBeInTheDocument();
  });

  it("a Viewer sees no prompt to start a run", async () => {
    mount("viewer", []);
    expect(await screen.findByText("No run yet.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Go to the project page/ })).toBeNull();
  });

  it("a run in the address that is not in the list yet shows a notice, never another run", async () => {
    mount("owner", [RUN], "/projects/demo/live?session=job-9-pipeline");
    expect(await screen.findByText(/not in the list yet/)).toBeInTheDocument();
    expect(FakeSocket.all).toHaveLength(0);
  });
});

describe("Live View: a finished run", () => {
  it("opens at its final picture with the replay ready", async () => {
    mount();
    (await socket()).deliver(FINISHED);
    const board = await screen.findByRole("region", { name: "Agents" });
    await waitFor(() => expect(within(board).getAllByRole("button", { name: /Done/ })).toHaveLength(12));
    expect(screen.getByRole("button", { name: /Replay from the start/ })).toBeInTheDocument();
    expect(screen.getByText(/27 · 14 passed/)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.1249/)).toBeInTheDocument();
    expect(screen.getByText(/447 \/ 447/)).toBeInTheDocument();
    expect(document.querySelector("[data-transport]")?.getAttribute("data-transport")).toBe("websocket");
  });

  it("replay from the start goes back to the beginning", async () => {
    mount();
    (await socket()).deliver(FINISHED);
    fireEvent.click(await screen.findByRole("button", { name: /Replay from the start/ }));
    expect(screen.getByText(/^0 \/ 447/)).toBeInTheDocument();
  });

  it("an agent in the address that is not on the board shows the whole run instead", async () => {
    mount("owner", [RUN], "/projects/demo/live?agent=bogus");
    (await socket()).deliver(FINISHED);
    expect(await screen.findByRole("heading", { name: "What is happening" })).toBeInTheDocument();
  });
});

describe("Live View: when the connection cannot go on", () => {
  it("says so plainly when the sign-in ended", async () => {
    mount();
    const ws = await socket();
    ws.deliver([{ type: "live", events: demoEvents.slice(0, 30), cursor: "c" }]);
    ws.drop(4401);
    expect(await screen.findByRole("alert")).toHaveTextContent(/sign-in ended/);
  });

  it("after an hour without news it offers to check again, which reconnects", async () => {
    mount();
    (await socket()).deliver([{ type: "live", events: demoEvents.slice(0, 30), cursor: "c" }, { type: "end", cursor: "c", reason: "idle" }]);
    fireEvent.click(await screen.findByRole("button", { name: "Check again" }));
    await socket(2);
  });
});

describe("Live View: content from the application under test is only text", () => {
  it("shows a page title with HTML in it as text, and an address as text, never a link", async () => {
    mount();
    const evil = { t: 1700000000, seq: 1, w: "gw0", agent: "explorer", kind: "navigate", phase: "action",
                   title: '<img src=x onerror="alert(1)">', url: "javascript:alert(1)", path: "/x" };
    (await socket()).deliver([{ type: "live", events: [{ t: 1699999999, seq: 0, w: "main", agent: "explorer", kind: "stage_start", phase: "lifecycle", title: "explore started" }, evil], cursor: "c" }]);
    expect((await screen.findAllByText('<img src=x onerror="alert(1)">')).length).toBeGreaterThan(0);
    expect(document.querySelector("img[src='x']")).toBeNull();
    expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
  });
});

describe("Details tabs", () => {
  it("move with the arrow keys, Home and End", async () => {
    mount();
    (await socket()).deliver(FINISHED);
    const doc = await screen.findByRole("tab", { name: "Document" });
    expect(doc).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(doc, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Site map" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Site map" }), { key: "End" });
    expect(screen.getByRole("tab", { name: "Activity" })).toHaveAttribute("aria-selected", "true");
  });
});
