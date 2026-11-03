import { describe, expect, it } from "vitest";
import { initialLiveState, reduceLive } from "./live";
import type { LiveEvent } from "./api";

let nextSeq = 0;
const ev = (over: Partial<LiveEvent>): LiveEvent => ({ t: 1, seq: ++nextSeq, w: "main", agent: "explorer", kind: "step", title: "x", ...over });

describe("reduceLive", () => {
  it("builds one card per agent from the stream", () => {
    const s = reduceLive(initialLiveState, {
      type: "events",
      events: [ev({ agent: "srs", kind: "stage_start", title: "analyze started" }), ev({ agent: "explorer", title: "opened /" })],
    });
    expect(s.agents.map((a) => [a.agent, a.state])).toEqual([
      ["srs", "running"],
      ["explorer", "running"],
    ]);
    expect(s.events).toHaveLength(2);
  });

  it("marks an agent done, failed or waiting from the event kind", () => {
    let s = reduceLive(initialLiveState, { type: "events", events: [ev({ kind: "stage_start" })] });
    s = reduceLive(s, { type: "events", events: [ev({ kind: "assist", title: "needs you" })] });
    expect(s.agents[0]).toMatchObject({ state: "waiting", last: "needs you", steps: 2 });
    s = reduceLive(s, { type: "events", events: [ev({ kind: "stage_end", level: "bad" })] });
    expect(s.agents[0].state).toBe("failed");
    s = reduceLive(s, { type: "events", events: [ev({ kind: "stage_end" })] });
    expect(s.agents[0].state).toBe("done");
  });

  it("records the end of the stream", () => {
    expect(reduceLive(initialLiveState, { type: "end" }).ended).toBe(true);
  });

  it("starts from nothing again when another run is chosen", () => {
    let s = reduceLive(initialLiveState, { type: "events", events: [ev({ kind: "stage_start" })] });
    s = reduceLive(s, { type: "end" });
    expect(reduceLive(s, { type: "reset" })).toEqual(initialLiveState);
  });
});

describe("reduceLive: replay, duplicates and later changes (M1.2-UI)", () => {
  it("never counts the same event twice, so a reconnect that replays is harmless", () => {
    const e1 = ev({ seq: 1, kind: "stage_start" });
    let s = reduceLive(initialLiveState, { type: "events", events: [e1] });
    s = reduceLive(s, { type: "events", events: [e1, ev({ seq: 2, kind: "stage_end" })] });
    expect(s.events).toHaveLength(2);
    expect(s.agents[0]).toMatchObject({ steps: 2, state: "done" });
  });

  it("marks a card as changed only when its state moves after the first batch (history is quiet)", () => {
    let s = reduceLive(initialLiveState, { type: "events", events: [ev({ seq: 1, kind: "stage_start" }), ev({ seq: 2, kind: "stage_end" })] });
    expect(s.agents[0].changed).toBe(false);
    s = reduceLive(s, { type: "events", events: [ev({ seq: 3, agent: "srs", kind: "stage_start" })] });
    expect(s.agents[1]).toMatchObject({ agent: "srs", changed: false });        // a new card is not a change
    s = reduceLive(s, { type: "events", events: [ev({ seq: 4, agent: "srs", kind: "stage_end", level: "bad" })] });
    expect(s.agents[1]).toMatchObject({ state: "failed", changed: true });
    expect(s.lastChange).toEqual({ agent: "srs", state: "failed" });
  });

  it("remembers the cursor of the last batch for a reconnect", () => {
    const s = reduceLive(initialLiveState, { type: "events", events: [ev({})], cursor: "abc" });
    expect(s.cursor).toBe("abc");
  });
});
