import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { FakeSocket } from "../../test-fixtures/fakeSocket";
import { demoBoard, demoEvents } from "../../test-fixtures/live";
import { dwellMs } from "./player";
import { useLive } from "./useLive";

function open(running = true) {
  vi.stubGlobal("WebSocket", FakeSocket);
  const hook = renderHook(() => useLive("demo", "s1", demoBoard, running));
  return { ...hook, socket: FakeSocket.all[0] };
}

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FakeSocket.all = [];
});

describe("useLive: replay while the run is still streaming", () => {
  it("keeps moving although a new batch arrives before each step's pause is over", () => {
    vi.useFakeTimers();
    const { result, socket } = open();
    socket.deliver([{ type: "live", events: demoEvents.slice(0, 50), cursor: "c" }]);
    act(() => result.current.dispatch({ type: "restart" }));
    const gap = dwellMs(result.current.stream.events[0], 1, 0, false) * 0.6;
    for (let i = 0; i < 10; i += 1) {
      act(() => vi.advanceTimersByTime(gap));
      socket.deliver([{ type: "live", events: [demoEvents[50 + i]], cursor: `c${i}` }], false);
    }
    expect(result.current.player.follow).toBe(false);
    expect(result.current.pos).toBeGreaterThan(2);
  });
});

describe("useLive: a run longer than the 50 000 events a tab keeps", () => {
  it("keeps its totals exact when the oldest events are dropped", () => {
    const { result, socket } = open();
    const cost = (i: number) => ({ t: 1_700_000_000 + i, seq: i, w: "main", agent: "ai", kind: "cost", title: "call", phase: "meta", cost_usd: 0.001 });
    for (let batch = 0; batch < 52; batch += 1) {
      socket.deliver([{ type: "live", events: Array.from({ length: 1000 }, (_, k) => cost(batch * 1000 + k)), cursor: "c" + batch }], batch === 0);
    }
    expect(result.current.stream.events.length).toBeLessThanOrEqual(50_000);
    expect(result.current.stream.dropped).toBeGreaterThan(0);
    expect(result.current.model.board.ai.calls).toBe(52_000);
    expect(result.current.model.board.ai.cost).toBeCloseTo(52, 6);
  }, 30_000);
});

describe("useLive: only a finished run is over", () => {
  it.each([["idle", false], ["something new", false], ["finished", true]])("an end saying %s → run over: %s", (reason, over) => {
    const { result, socket } = open();
    socket.deliver([{ type: "live", events: demoEvents.slice(0, 20), cursor: "c" }, { type: "end", reason, cursor: "c" }]);
    expect(result.current.runOver).toBe(over);
    expect(result.current.shownOver).toBe(over);                       // following, so the picture is the end
  });

  it("the picture is the run's end only at its last event: scrubbed back it is not, though the run is over (Phase C)", () => {
    const { result, socket } = open();
    socket.deliver([{ type: "live", events: demoEvents.slice(0, 20), cursor: "c" }, { type: "end", reason: "finished", cursor: "c" }]);
    act(() => result.current.dispatch({ type: "scrub", pos: 5, total: 20 }));
    expect(result.current.runOver).toBe(true);
    expect(result.current.shownOver).toBe(false);
    act(() => result.current.dispatch({ type: "live", total: 20 }));
    expect(result.current.shownOver).toBe(true);
  });

  it("a run still streaming is never shown as over, even with the replay at its newest event", () => {
    const { result, socket } = open();
    socket.deliver([{ type: "live", events: demoEvents.slice(0, 20), cursor: "c" }]);
    expect(result.current.pos).toBe(20);
    expect(result.current.shownOver).toBe(false);
  });
});

describe("useLive: a connection that cannot go on", () => {
  it("a sign-in that ended stops the stream but does not call the run over", () => {
    const { result, socket } = open();
    socket.deliver([{ type: "live", events: demoEvents.slice(0, 20), cursor: "c" }]);
    socket.drop(4401);
    expect(result.current.status).toBe("signed-out");
    expect(result.current.stream.ended).toBe("signed-out");
    expect(result.current.runOver).toBe(false);
  });

  it("a run that no longer exists ends the stream", () => {
    const { result, socket } = open();
    socket.deliver([], true);
    socket.drop(4404);
    expect(result.current.stream.ended).toBe("gone");
    expect(result.current.runOver).toBe(false);                       // the page says it is gone, not that it finished
  });
});
