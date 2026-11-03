import { afterEach, describe, expect, it, vi } from "vitest";
import { toEvent, type LiveEvent } from "./event";
import { dwellMs, initialPlayer, loadPosition, playerReducer, savePosition, type Player } from "./player";

const ev = (kind: string, extra: Record<string, unknown> = {}) =>
  toEvent({ t: 1, seq: 1, w: "main", agent: "srs", kind, title: "x", phase: "result", ...extra }) as LiveEvent;

describe("dwellMs: how long replay lingers on a step (ported from the v0.8 player)", () => {
  it.each([
    ["a screenshot", ev("action", { shot: "main-00001.jpg" }), 650],
    ["a requirement", ev("requirement"), 300],
    ["a rule", ev("rule"), 55],
    ["a verdict", ev("verdict"), 160],
    ["a stage start", ev("stage_start"), 450],
    ["anything else", ev("observe"), 120],
  ])("%s at 1x", (_what, event, ms) => {
    expect(dwellMs(event, 1, 0, false)).toBe(ms);
  });

  it("goes faster with speed, catches up with a backlog when following live, and is instant at 0", () => {
    expect(dwellMs(ev("observe"), 2, 0, false)).toBe(60);
    expect(dwellMs(ev("observe"), 1, 240, true)).toBe(6);
    expect(dwellMs(ev("observe"), 1, 240, false)).toBe(120);
    expect(dwellMs(ev("observe"), 0, 0, false)).toBe(0);
  });
});

describe("playerReducer", () => {
  const p: Player = { pos: 10, playing: true, speed: 1, follow: false };

  it("steps one event and pauses", () => {
    expect(playerReducer(p, { type: "step", total: 20 })).toEqual({ ...p, pos: 11, playing: false });
    expect(playerReducer({ ...p, pos: 20 }, { type: "step", total: 20 }).pos).toBe(20);
  });

  it("restarts from the beginning, playing", () => {
    expect(playerReducer(p, { type: "restart" })).toEqual({ pos: 0, playing: true, speed: 1, follow: false });
  });

  it("goes live: to the newest event, following", () => {
    expect(playerReducer(p, { type: "live", total: 99 })).toEqual({ ...p, pos: 99, playing: true, follow: true });
  });

  it("scrubbing pauses, stops following and stays inside the run", () => {
    expect(playerReducer(p, { type: "scrub", pos: 500, total: 40 })).toEqual({ ...p, pos: 40, playing: false, follow: false });
    expect(playerReducer(p, { type: "scrub", pos: -3, total: 40 }).pos).toBe(0);
  });

  it("advances, never past the end; following keeps up with new events", () => {
    expect(playerReducer(p, { type: "advance", by: 5, total: 12 }).pos).toBe(12);
    expect(playerReducer({ ...p, follow: true }, { type: "advance", by: 1, total: 30 }).pos).toBe(11);
  });

  it("toggles play and changes speed", () => {
    expect(playerReducer(p, { type: "toggle" }).playing).toBe(false);
    expect(playerReducer(p, { type: "speed", speed: 4 }).speed).toBe(4);
  });
});

describe("initialPlayer: where a run opens (owner decision 4)", () => {
  it("a finished run opens at its final picture, paused", () => {
    expect(initialPlayer(447, false, null)).toEqual({ pos: 447, playing: false, speed: 2, follow: false });
  });

  it("a running run follows live", () => {
    expect(initialPlayer(30, true, null)).toEqual({ pos: 30, playing: true, speed: 1, follow: true });
  });

  it("a finished run reopens where this viewer left it", () => {
    expect(initialPlayer(447, false, { pos: 120, follow: false })).toMatchObject({ pos: 120, playing: false });
    expect(initialPlayer(447, false, { pos: 9999, follow: false }).pos).toBe(447);
  });
});

describe("saved position", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("is kept per run in the tab", () => {
    savePosition("demo", "run-1", { pos: 42, playing: false, speed: 1, follow: false });
    expect(loadPosition("demo", "run-1")).toEqual({ pos: 42, follow: false });
    expect(loadPosition("demo", "run-2")).toBeNull();
  });

  it("never breaks the page when storage is refused or holds rubbish", () => {
    sessionStorage.setItem("agentqa.live.demo.run-3", "{not json");
    expect(loadPosition("demo", "run-3")).toBeNull();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => savePosition("demo", "run-1", { pos: 1, playing: true, speed: 1, follow: true })).not.toThrow();
  });
});
