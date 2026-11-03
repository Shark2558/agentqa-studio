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

let probeStatus = 200;
beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, "random").mockReturnValue(0.5);         // no jitter: each wait is exactly the backoff
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("EventSource", FakeSource);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: probeStatus })));
  sessionStorage.clear();
  cursor = "";
  probeStatus = 200;
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FakeSocket.all = [];
  FakeSource.all = [];
});

describe("liveUrl", () => {
  it("builds the WebSocket address from the page's own address, with the cursor", () => {
    expect(liveUrl("websocket", "demo", "cli-20261103-133600-pipeline", "abc=")).toBe(
      `ws://${location.host}/api/v1/projects/demo/live/cli-20261103-133600-pipeline/ws?cursor=abc%3D`);
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
    expect(sessionStorage.getItem(TRANSPORT_KEY)).toBeNull();          // not until SSE has shown it works
    last(FakeSource.all).emit("live", { events: [ev], cursor: "c1" });
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

  it("a socket that worked before is tried again, never swapped for SSE, after a blip", () => {
    const h = handlers();
    connectLive("demo", "run-1", h);
    last(FakeSocket.all).open();
    last(FakeSocket.all).send({ type: "live", events: [ev], cursor: "c1" });
    last(FakeSocket.all).drop(1006);
    vi.advanceTimersByTime(3_000);
    last(FakeSocket.all).drop(1006);                         // the retry fails before it opens (Wi-Fi blip)
    vi.advanceTimersByTime(6_000);
    expect(FakeSource.all).toHaveLength(0);
    expect(FakeSocket.all).toHaveLength(3);
    expect(sessionStorage.getItem(TRANSPORT_KEY)).toBeNull();
  });

  it("waits longer after each failed try, then gives up and says the connection is lost", () => {
    const h = handlers();
    connectLive("demo", "run-1", h);
    const waits: number[] = [];
    for (let i = 0; i < 9; i += 1) {
      const ws = last(FakeSocket.all);
      ws.open();
      ws.drop(1011);
      const before = FakeSocket.all.length;
      let waited = 0;
      while (FakeSocket.all.length === before && waited <= 60_000) {
        vi.advanceTimersByTime(1_000);
        waited += 1_000;
      }
      waits.push(waited);
    }
    expect(waits.slice(0, 6)).toEqual([3_000, 6_000, 12_000, 24_000, 48_000, 60_000]);
    expect(last(h.statuses)).toBe("lost");
    expect(FakeSocket.all).toHaveLength(9);                 // eight retries, then no more
  });

  it("uses SSE when the server refuses the socket for its origin (4403), and stops on a bad request (4400)", () => {
    const one = handlers();
    connectLive("demo", "run-1", one);
    last(FakeSocket.all).open();
    last(FakeSocket.all).drop(4403);
    expect(FakeSource.all).toHaveLength(1);
    const two = handlers();
    connectLive("demo", "run-1", two);
    last(FakeSocket.all).open();
    last(FakeSocket.all).drop(4400);
    vi.advanceTimersByTime(120_000);
    expect(last(two.statuses)).toBe("lost");
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("refuses a run id that would walk out of its folder", () => {
    expect(() => liveUrl("sse", "demo", "..", "")).toThrow();
    expect(() => liveUrl("websocket", "..", "run-1", "")).toThrow();
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
  it("streams batches and the end, and retries from the cursor on an error", async () => {
    sessionStorage.setItem(TRANSPORT_KEY, "sse");
    const h = handlers();
    connectLive("demo", "run-1", h);
    const es = last(FakeSource.all);
    es.emit("live", { events: [ev], cursor: "c2" });
    es.emit("error", {});
    await vi.advanceTimersByTimeAsync(3_000);
    expect(last(FakeSource.all).url).toContain("cursor=c2");
    last(FakeSource.all).emit("end", { cursor: "c2", reason: "idle" });
    expect(h.ends).toEqual(["idle"]);
    expect(h.transports).toEqual(["sse"]);
  });
});

describe("connectLive: why an SSE stream failed (EventSource hides the HTTP status)", () => {
  it.each([[401, "signed-out"], [404, "gone"]])("asks once; %s means %s and nothing is retried", async (status, word) => {
    sessionStorage.setItem(TRANSPORT_KEY, "sse");
    probeStatus = status;
    const h = handlers();
    connectLive("demo", "run-1", h);
    last(FakeSource.all).emit("error", {});
    await vi.advanceTimersByTimeAsync(120_000);
    expect(last(h.statuses)).toBe(word);
    expect(FakeSource.all).toHaveLength(1);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it("too busy (429) waits 10 s before trying again", async () => {
    sessionStorage.setItem(TRANSPORT_KEY, "sse");
    probeStatus = 429;
    connectLive("demo", "run-1", handlers());
    last(FakeSource.all).emit("error", {});
    await vi.advanceTimersByTimeAsync(9_000);
    expect(FakeSource.all).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(FakeSource.all).toHaveLength(2);
  });
});
