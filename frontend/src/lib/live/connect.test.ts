import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connectLive, liveUrl, TRANSPORT_KEY, type Handlers } from "./connect";

class FakeSocket {
  static all: FakeSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  send(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
  drop(code: number) {
    this.onclose?.({ code });
  }
}

class FakeSource {
  static all: FakeSource[] = [];
  url: string;
  listeners: Record<string, ((e: { data: string }) => void)[]> = {};
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeSource.all.push(this);
  }
  addEventListener(type: string, cb: (e: { data: string }) => void) {
    (this.listeners[type] ??= []).push(cb);
  }
  emit(type: string, data: unknown) {
    for (const cb of this.listeners[type] ?? []) cb({ data: JSON.stringify(data) });
  }
  close() {
    this.closed = true;
  }
}

const ev = { t: 1, seq: 1, w: "main", agent: "srs", kind: "rule", title: "x", phase: "thought" };
let cursor = "";
function handlers(): Handlers & { frames: unknown[][]; ends: string[]; statuses: string[]; transports: string[] } {
  const h = { frames: [] as unknown[][], ends: [] as string[], statuses: [] as string[], transports: [] as string[] };
  return {
    ...h,
    cursor: () => cursor,
    onEvents: (events, next) => {
      h.frames.push(events);
      if (next) cursor = next;
    },
    onEnd: (reason) => h.ends.push(reason),
    onStatus: (s) => h.statuses.push(s),
    onTransport: (t) => h.transports.push(t),
  };
}
const last = <T>(xs: T[]) => xs[xs.length - 1];

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("EventSource", FakeSource);
  sessionStorage.clear();
  cursor = "";
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FakeSocket.all = [];
  FakeSource.all = [];
});

describe("liveUrl", () => {
  it("builds the WebSocket address from the page's own address, with the cursor", () => {
    expect(liveUrl("websocket", "demo", "run 1", "abc=")).toBe(`ws://${location.host}/api/v1/projects/demo/live/run%201/ws?cursor=abc%3D`);
    expect(liveUrl("sse", "demo", "run-1", "")).toBe("/api/v1/projects/demo/live/run-1/stream");
  });
});

describe("connectLive: WebSocket first", () => {
  it("streams batches and the end over a WebSocket", () => {
    const h = handlers();
    connectLive("demo", "run-1", h);
    const ws = last(FakeSocket.all);
    ws.open();
    ws.send({ type: "live", events: [ev], cursor: "c1" });
    ws.send({ type: "end", cursor: "c1", reason: "finished" });
    expect(h.transports).toEqual(["websocket"]);
    expect(h.frames).toEqual([[ev]]);
    expect(h.ends).toEqual(["finished"]);
    expect(last(h.statuses)).toBe("ended");
  });

  it("falls back to SSE when the socket closes before it opens, and remembers that for the tab", () => {
    const h = handlers();
    connectLive("demo", "run-1", h);
    last(FakeSocket.all).drop(1006);
    expect(FakeSource.all).toHaveLength(1);
    expect(h.transports).toEqual(["websocket", "sse"]);
    expect(sessionStorage.getItem(TRANSPORT_KEY)).toBe("sse");
    connectLive("demo", "run-2", handlers());
    expect(FakeSocket.all).toHaveLength(1);                 // the next run goes straight to SSE
  });

  it("stops and says so when the sign-in has ended (4401) or the run is gone (4404)", () => {
    for (const [code, status] of [[4401, "signed-out"], [4404, "gone"]] as const) {
      const h = handlers();
      connectLive("demo", "run-1", h);
      const ws = last(FakeSocket.all);
      ws.open();
      ws.drop(code);
      vi.advanceTimersByTime(60_000);
      expect(last(h.statuses)).toBe(status);
      expect(last(FakeSocket.all)).toBe(ws);                 // no retry
    }
  });

  it("waits 10 s and tries again when too many streams are open (4429)", () => {
    const h = handlers();
    connectLive("demo", "run-1", h);
    last(FakeSocket.all).drop(4429);
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(10_000);
    expect(FakeSocket.all).toHaveLength(2);
    expect(h.statuses).toContain("retrying");
  });

  it("reconnects from the last cursor after a drop, so nothing is read twice or missed", () => {
    const h = handlers();
    connectLive("demo", "run-1", h);
    const ws = last(FakeSocket.all);
    ws.open();
    ws.send({ type: "live", events: [ev], cursor: "c7" });
    ws.drop(1006);
    vi.advanceTimersByTime(3_000);
    expect(last(FakeSocket.all).url).toContain("cursor=c7");
  });

  it("skips a frame that is not JSON or not shaped like one", () => {
    const h = handlers();
    connectLive("demo", "run-1", h);
    const ws = last(FakeSocket.all);
    ws.open();
    ws.onmessage?.({ data: "{not json" });
    ws.send({ type: "live", events: "nope" });
    expect(h.frames).toEqual([]);
  });

  it("stopping closes the socket and cancels a pending retry", () => {
    const h = handlers();
    const stop = connectLive("demo", "run-1", h);
    last(FakeSocket.all).drop(4429);
    stop();
    vi.advanceTimersByTime(20_000);
    expect(FakeSocket.all).toHaveLength(1);
  });
});

describe("connectLive: Server-Sent Events", () => {
  it("streams batches and the end, and retries from the cursor on an error", () => {
    sessionStorage.setItem(TRANSPORT_KEY, "sse");
    const h = handlers();
    connectLive("demo", "run-1", h);
    const es = last(FakeSource.all);
    es.emit("live", { events: [ev], cursor: "c2" });
    es.emit("error", {});
    vi.advanceTimersByTime(3_000);
    expect(last(FakeSource.all).url).toContain("cursor=c2");
    last(FakeSource.all).emit("end", { cursor: "c2", reason: "idle" });
    expect(h.ends).toEqual(["idle"]);
    expect(h.transports).toEqual(["sse"]);
  });
});
