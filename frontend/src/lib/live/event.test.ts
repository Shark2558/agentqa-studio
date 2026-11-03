import { describe, expect, it } from "vitest";
import { compareEvents, safeBox, safeShot, severity, toEvent, type LiveEvent } from "./event";

const base = { t: 1700000000.5, seq: 1, w: "main", agent: "srs", kind: "rule", title: "a rule", phase: "thought" };

describe("toEvent: only well-shaped events get in", () => {
  it("keeps a good event, and an unknown or missing phase reads as a note", () => {
    expect(toEvent(base)?.phase).toBe("thought");
    expect(toEvent({ ...base, phase: "nonsense" })?.phase).toBe("note");
    expect(toEvent({ ...base, phase: undefined })?.phase).toBe("note");
  });

  it.each([
    ["not an object", "x"],
    ["no time", { ...base, t: undefined }],
    ["time not finite", { ...base, t: Number.POSITIVE_INFINITY }],
    ["seq not a whole number", { ...base, seq: 1.5 }],
    ["negative seq", { ...base, seq: -1 }],
    ["worker not text", { ...base, w: 3 }],
    ["agent not text", { ...base, agent: null }],
    ["kind not text", { ...base, kind: ["rule"] }],
    ["title not text", { ...base, title: { html: "<b>" } }],
  ])("rejects %s", (_why, value) => {
    expect(toEvent(value)).toBeNull();
  });

  it("returns a new object and never changes its input", () => {
    const input = Object.freeze({ ...base });
    const out = toEvent(input);
    expect(out).not.toBe(input);
    expect(input).toEqual(base);
  });
});

describe("severity: only ok, warn and bad are severities", () => {
  it("reads a string level and ignores the numeric level of a heading", () => {
    expect(severity({ ...base, level: "bad" } as LiveEvent)).toBe("bad");
    expect(severity({ ...base, level: "warn" } as LiveEvent)).toBe("warn");
    expect(severity({ ...base, kind: "heading", level: 2 } as LiveEvent)).toBeNull();
    expect(severity({ ...base, level: "loud" } as LiveEvent)).toBeNull();
  });
});

describe("safeShot: a screenshot name is only ever a plain .jpg file name", () => {
  it.each(["main-00114.jpg", "gw1-00002.jpg", "tests-login-00007.jpg"])("accepts %s", (name) => {
    expect(safeShot(name)).toBe(name);
  });
  it.each(["../x.jpg", "a b.jpg", "x.png", "a/b.jpg", "a\\b.jpg", `${"x".repeat(200)}.jpg`, "", 3, null])(
    "refuses %s",
    (name) => {
      expect(safeShot(name)).toBeNull();
    },
  );
});

describe("safeBox: the outlined element only from finite numbers inside the viewport", () => {
  const ev = (box: unknown, extra: Record<string, unknown> = {}) => ({ ...base, box, vw: 1280, vh: 720, ...extra }) as LiveEvent;

  it("keeps a good box with its viewport", () => {
    expect(safeBox(ev({ x: 10, y: 20, width: 100, height: 30 }))).toEqual({ x: 10, y: 20, width: 100, height: 30, vw: 1280, vh: 720 });
  });

  it("falls back to a 1280 x 720 viewport when the event has none", () => {
    expect(safeBox({ ...base, box: { x: 1, y: 1, width: 2, height: 2 } } as LiveEvent)?.vw).toBe(1280);
  });

  it.each([
    ["no box", undefined],
    ["NaN", { x: Number.NaN, y: 0, width: 1, height: 1 }],
    ["Infinity", { x: 0, y: 0, width: Number.POSITIVE_INFINITY, height: 1 }],
    ["negative position", { x: -5, y: 0, width: 1, height: 1 }],
    ["zero size", { x: 0, y: 0, width: 0, height: 1 }],
    ["off the viewport", { x: 5000, y: 0, width: 10, height: 10 }],
    ["text numbers", { x: "1", y: "1", width: "1", height: "1" }],
  ])("drops %s", (_why, box) => {
    expect(safeBox(ev(box))).toBeNull();
  });
});

describe("compareEvents: one order for live and replay", () => {
  it("orders by time, then sequence, then worker", () => {
    const a = { ...base, t: 1, seq: 2, w: "gw1" } as LiveEvent;
    const b = { ...base, t: 1, seq: 2, w: "main" } as LiveEvent;
    const c = { ...base, t: 1, seq: 3, w: "gw0" } as LiveEvent;
    const d = { ...base, t: 0.5, seq: 9, w: "main" } as LiveEvent;
    expect([c, b, a, d].sort(compareEvents)).toEqual([d, a, b, c]);
  });
});

describe("toEvent: nothing from the application under test can grow without bound (security review)", () => {
  it("cuts long text: titles at 500 characters, code previews at 20 000, everything else at 2 000", () => {
    const e = toEvent({ ...base, title: "t".repeat(9_000), url: "u".repeat(1_000_000), preview: "p".repeat(90_000) });
    expect(e?.title).toHaveLength(500);
    expect(e?.url).toHaveLength(2_000);
    expect(e?.preview).toHaveLength(20_000);
  });

  it("keeps nested data shallow and short: lists of at most 200, three levels, text and numbers only", () => {
    const deep = { a: { b: { c: { d: "too deep" } } } };
    const e = toEvent({ ...base, rows: Array.from({ length: 900 }, (_, i) => [i, "x".repeat(5_000)]), value: deep, fn: () => 1 });
    const rows = (e?.rows ?? []) as unknown[][];
    expect(rows).toHaveLength(200);
    expect(rows[0][1]).toHaveLength(2_000);
    expect(e?.value).toEqual({ a: { b: { c: {} } } });
    expect(e).not.toHaveProperty("fn");
  });

  it("refuses a time no run can have (it would break every clock on the page)", () => {
    expect(toEvent({ ...base, t: 1e20 })).toBeNull();
    expect(toEvent({ ...base, t: -1 })).toBeNull();
  });

  it("cuts the worker, agent and kind names short", () => {
    const e = toEvent({ ...base, w: "w".repeat(500), agent: "a".repeat(500) });
    expect(e?.w).toHaveLength(64);
    expect(e?.agent).toHaveLength(64);
  });

  it("a __proto__ key is kept as plain data and changes no prototype", () => {
    const e = toEvent(JSON.parse('{"t":1700000000,"seq":1,"w":"m","agent":"srs","kind":"x","title":"y","value":{"__proto__":{"polluted":1}}}'));
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    expect(Object.getPrototypeOf(e?.value)).toBe(Object.prototype);
  });
});

describe("safeBox: the viewport is a real screen size", () => {
  it.each([["a giant viewport", 50_000], ["a zero viewport", 0]])("drops %s", (_why, vw) => {
    expect(safeBox({ ...base, vw, box: { x: 1, y: 1, width: 2, height: 2 } } as LiveEvent)).toBeNull();
  });
});
