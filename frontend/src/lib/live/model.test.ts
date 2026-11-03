import { describe, expect, it } from "vitest";
import { demoBoard, demoEvents, expectedSummary } from "../../test-fixtures/live";
import { compareEvents, toEvent, type LiveEvent } from "./event";
import { CHECKPOINT_EVERY, buildTimeline, emptyModel, fold, modelAt, snapshot, summarize } from "./model";
import { emptyStream, mergeEvents } from "./stream";

const events: LiveEvent[] = demoEvents.map((e) => toEvent(e) as LiveEvent).sort(compareEvents);
const all = fold(emptyModel(demoBoard), events, demoBoard);

function seeded(seed: number): () => number {
  let x = seed;
  return () => {
    x = (x * 1103515245 + 12345) % 2147483648;
    return x / 2147483648;
  };
}

describe("model: the fixture run's final picture", () => {
  it("equals the picture counted independently from the recording", () => {
    expect(events).toHaveLength(447);
    expect(summarize(all, true)).toEqual(expectedSummary);
  });
});

describe("replay matches the live view", () => {
  it("folding in any batches gives the same model as folding everything at once", () => {
    const rand = seeded(7);
    for (let trial = 0; trial < 5; trial += 1) {
      let model = emptyModel(demoBoard);
      let i = 0;
      while (i < events.length) {
        const n = 1 + Math.floor(rand() * 60);
        model = fold(model, events.slice(i, i + n), demoBoard);
        i += n;
      }
      expect(snapshot(model)).toEqual(snapshot(all));
    }
  });

  it("events arriving out of order across workers land in the same place through the stream", () => {
    const rand = seeded(11);
    const shuffled = [...demoEvents].sort(() => rand() - 0.5);
    let stream = emptyStream;
    for (let i = 0; i < shuffled.length; i += 37) stream = mergeEvents(stream, shuffled.slice(i, i + 37));
    expect(snapshot(fold(emptyModel(demoBoard), stream.events, demoBoard))).toEqual(snapshot(all));
  });

  it("jumping to any position (a checkpoint, then the rest) equals folding up to it", () => {
    const timeline = buildTimeline(events, demoBoard);
    expect(timeline.checkpoints.length).toBe(Math.floor(events.length / CHECKPOINT_EVERY) + 1);
    for (let pos = 0; pos <= events.length; pos += 100) {
      expect(snapshot(modelAt(timeline, events, pos, demoBoard))).toEqual(snapshot(fold(emptyModel(demoBoard), events.slice(0, pos), demoBoard)));
    }
    expect(snapshot(modelAt(timeline, events, events.length, demoBoard))).toEqual(snapshot(all));
  });

  it("a late event rebuilds the timeline from the last checkpoint before it, not from the start", () => {
    const long = Array.from({ length: 3 }, (_, k) => events.map((e) => ({ ...e, t: e.t + k * 100000, seq: e.seq + k * 100000 }))).flat();
    const first = buildTimeline(long, demoBoard);
    const again = buildTimeline(long, demoBoard, first, 1100);
    expect(again.checkpoints[1]).toBe(first.checkpoints[1]);                // kept: before the change
    expect(snapshot(again.checkpoints[2])).toEqual(snapshot(first.checkpoints[2]));
  });

  it("never changes the model it was given", () => {
    const start = fold(emptyModel(demoBoard), events.slice(0, 200), demoBoard);
    const before = JSON.stringify(snapshot(start));
    fold(start, events.slice(200), demoBoard);
    expect(JSON.stringify(snapshot(start))).toBe(before);
  });

  it("folds a whole demo run's worth of events (2 700) in under 200 ms", () => {
    const big = Array.from({ length: 6 }, (_, k) => events.map((e) => ({ ...e, t: e.t + k * 100000, seq: e.seq + k * 100000 }))).flat().slice(0, 2700);
    const started = performance.now();
    fold(emptyModel(demoBoard), big, demoBoard);
    expect(performance.now() - started).toBeLessThan(200);
  });
});
