import { describe, expect, it } from "vitest";
import { emptyStream, endStream, mergeEvents } from "./stream";

const ev = (seq: number, t: number, w = "main", title = `step ${seq}`) => ({ t, seq, w, agent: "srs", kind: "rule", title, phase: "thought" });

describe("mergeEvents: every event once, in one order", () => {
  it("adds events in (time, seq, worker) order and moves the cursor", () => {
    const s = mergeEvents(emptyStream, [ev(2, 20), ev(1, 10)], "c1");
    expect(s.events.map((e) => e.seq)).toEqual([1, 2]);
    expect(s.cursor).toBe("c1");
    expect(s.changedFrom).toBe(0);
  });

  it("ignores repeats from a reconnect and keeps the old cursor when a batch carries none", () => {
    const one = mergeEvents(emptyStream, [ev(1, 10), ev(2, 20)], "c1");
    const two = mergeEvents(one, [ev(2, 20), ev(1, 10)]);
    expect(two.events).toHaveLength(2);
    expect(two.cursor).toBe("c1");
    expect(two.changedFrom).toBe(2);                 // nothing new: nothing to recompute
  });

  it("drops events that are not shaped like events", () => {
    const s = mergeEvents(emptyStream, [ev(1, 10), { seq: 2 }, "x", null]);
    expect(s.events).toHaveLength(1);
  });

  it("puts a late event from another worker in its place and says where the change starts", () => {
    const one = mergeEvents(emptyStream, [ev(1, 10), ev(2, 30), ev(3, 40)]);
    const two = mergeEvents(one, [ev(1, 20, "gw1")]);
    expect(two.events.map((e) => `${e.w}:${e.seq}`)).toEqual(["main:1", "gw1:1", "main:2", "main:3"]);
    expect(two.changedFrom).toBe(1);
  });

  it("never changes the state it was given", () => {
    const one = mergeEvents(emptyStream, [ev(1, 10)]);
    const snapshot = [...one.events];
    mergeEvents(one, [ev(0, 5)]);
    expect(one.events).toEqual(snapshot);
  });

  it("keeps at most the newest 50 000 events and says it dropped the oldest", () => {
    const many = Array.from({ length: 50_010 }, (_, i) => ev(i, i));
    const s = mergeEvents(emptyStream, many);
    expect(s.events).toHaveLength(50_000);
    expect(s.events[0].seq).toBe(10);
    expect(s.truncated).toBe(true);
  });
});

describe("endStream", () => {
  it("records why the stream ended", () => {
    expect(endStream(emptyStream, "finished").ended).toBe("finished");
    expect(endStream(emptyStream, "nonsense").ended).toBe("finished");
    expect(endStream(emptyStream, "gone").ended).toBe("gone");
  });
});
