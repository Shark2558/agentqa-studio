import { describe, expect, it } from "vitest";
import { initialLiveState, reduceLive } from "./live";
import type { LiveEvent } from "./api";

const ev = (over: Partial<LiveEvent>): LiveEvent => ({ t: 1, seq: 1, w: "main", agent: "explorer", kind: "step", title: "x", ...over });

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
