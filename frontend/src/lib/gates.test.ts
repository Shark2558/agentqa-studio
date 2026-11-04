import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import type { GateCounts } from "./gatesApi";
import {
  WHY_MAX, byWords, cleanWhy, errorWords, exportLinks, gatePollMs, isStale, liveGateText, navBadges, needsWhy, needsYou, policyWords,
  setMany, toggle, when,
} from "./gates";
import fixture from "../test-fixtures/gates-demo.json";

const COUNTS = fixture.gates as GateCounts;
const counts = (over: Partial<GateCounts> = {}): GateCounts => ({ ...COUNTS, ...over });

describe("selection", () => {
  it("toggling returns a new set and never changes its input", () => {
    const before: ReadonlySet<string> = new Set(["TC-0001"]);
    const after = toggle(before, "TC-0002");
    expect([...after]).toEqual(["TC-0001", "TC-0002"]);
    expect([...before]).toEqual(["TC-0001"]);
    expect([...toggle(after, "TC-0001")]).toEqual(["TC-0002"]);
  });

  it("selects or clears a page of ids at once without touching the input", () => {
    const before: ReadonlySet<string> = new Set(["TC-0009"]);
    const all = setMany(before, ["TC-0001", "TC-0002"], true);
    expect([...all].sort()).toEqual(["TC-0001", "TC-0002", "TC-0009"]);
    expect([...setMany(all, ["TC-0001", "TC-0009"], false)]).toEqual(["TC-0002"]);
    expect([...before]).toEqual(["TC-0009"]);
  });
});

describe("which decisions need a reason (decision 4 and the Phase A record)", () => {
  it.each([
    ["cases", "approve", false], ["cases", "reject", true], ["cases", "reset", true],
    ["type", "approve", false], ["type", "reject", true],
    ["imported", "approve_ready", false], ["imported", "approve", false], ["imported", "reject", true], ["imported", "review", true],
    ["defects", "confirmed", false], ["defects", "rejected", true], ["defects", "draft", true],
    ["disposition", "manual", true], ["disposition", "out_of_scope", true], ["reopen", "reopen", true], ["approve", "approve", false],
  ] as const)("%s %s → %s", (what, decision, needed) => {
    expect(needsWhy(what, decision)).toBe(needed);
  });

  it("a reason is stored as one trimmed line of at most 500 characters, as the server stores it", () => {
    expect(cleanWhy("  not\nin   scope \t")).toBe("not in scope");
    expect(cleanWhy("x".repeat(WHY_MAX + 20))).toHaveLength(WHY_MAX);
    expect(cleanWhy(" \n ")).toBe("");
  });
});

describe("export links", () => {
  it("default to confirmed defects only and include drafts only when asked (decision 5)", () => {
    const off = exportLinks("demo", false);
    expect(off.map((l) => l.href)).toEqual([
      "/api/v1/projects/demo/defects/export.csv?drafts=0", "/api/v1/projects/demo/defects/zoho.csv?drafts=0",
    ]);
    expect(exportLinks("demo", true).every((l) => l.href.endsWith("drafts=1"))).toBe(true);
  });

  it("encode the project's name", () => {
    expect(exportLinks("a b/c", false)[0].href).toBe("/api/v1/projects/a%20b%2Fc/defects/export.csv?drafts=0");
  });
});

describe("who made a change, in words", () => {
  it("shows a person as recorded and names AgentQA's own rows", () => {
    expect(byWords("owner@example.com (owner)")).toBe("owner@example.com (owner)");
    expect(byWords("agents")).toBe("AgentQA's agents");
    expect(byWords("dashboard")).toBe("someone in the old dashboard");
    expect(byWords(null)).toBe("not recorded");
  });

  it("shows a stored time to the minute, or a dash", () => {
    expect(when("2026-11-04T03:48:26")).toBe("2026-11-04 03:48");
    expect(when(null)).toBe("—");
  });
});

describe("the re-plan policy, in words", () => {
  it("says what project.yaml's rule does, and names an unknown rule as written", () => {
    expect(policyWords({ divergence: "ask", inferred_access: "ask" })).toMatch(/asks you/);
    expect(policyWords({ divergence: "srs_wins", inferred_access: "ask" })).toMatch(/requirements document wins/);
    expect(policyWords({ divergence: "app_wins", inferred_access: "ask" })).toMatch(/application does wins/);
    expect(policyWords({ divergence: "<b>odd</b>", inferred_access: "ask" })).toContain("“<b>odd</b>”");
  });
});

describe("error messages", () => {
  it("turn the gate refusals into plain words", () => {
    expect(errorWords(new ApiError(409, "not_open", "x"))).toMatch(/already answered/);
    expect(errorWords(new ApiError(409, "plan_changed", "x"))).toMatch(/plan changed/);
    expect(errorWords(new ApiError(409, "busy", "x"))).toMatch(/run is going/);
    expect(errorWords(new ApiError(403, "read_only", "x"))).toMatch(/can look/);
    expect(errorWords(new ApiError(422, "validation", "give a short reason"))).toBe("give a short reason");
    expect(errorWords(new Error("boom"))).toMatch(/went wrong/);
  });
});

describe("navigation badges", () => {
  it("count open questions, cases to review while the plan is not approved, and drafts to confirm", () => {
    const b = navBadges(counts({ plan: { ...COUNTS.plan, approved: false, proposed: 206 }, imported_ready: 9 }));
    expect(b.questions).toEqual({ text: "15", name: "15 open" });
    expect(b.plan).toEqual({ text: "215", name: "215 to review" });
    expect(b.defects).toEqual({ text: "19", name: "19 to confirm" });
  });

  it("show nothing when nothing waits, and a dot when only the approval itself is left", () => {
    const quiet = navBadges(counts({ questions_open: 0, defects_draft: 0 }));
    expect(quiet).toEqual({ questions: null, plan: null, defects: null });
    expect(navBadges(counts({ plan: { ...COUNTS.plan, approved: false, proposed: 0 } })).plan).toEqual({ text: "•", name: "waiting for your approval" });
    expect(navBadges(undefined)).toEqual({ questions: null, plan: null, defects: null });
  });
});

describe("what needs you", () => {
  it("lists every open item with a link to its page", () => {
    const items = needsYou(counts({ plan: { ...COUNTS.plan, approved: false, proposed: 206 }, imported_ready: 9, assist_pending: 1 }), "demo");
    expect(items.map((i) => [i.text, i.to])).toEqual([
      ["An agent is waiting for you", "/projects/demo/live"],
      ["15 questions to answer", "/projects/demo/questions"],
      ["The test plan waits for your approval: 206 cases to review", "/projects/demo/plan"],
      ["9 imported manual cases are ready to approve", "/projects/demo/plan"],
      ["19 defects to confirm or reject", "/projects/demo/defects"],
    ]);
  });

  it("names visual changes and heals without a link until their pages arrive, and is empty when nothing waits", () => {
    const items = needsYou(counts({ questions_open: 0, defects_draft: 0, visual_changed: 2, heals_proposed: 1 }), "demo");
    expect(items.map((i) => [i.text, i.to])).toEqual([
      ["2 changed screens to review (in the old dashboard for now)", null], ["1 proposed fix to review (in the old dashboard for now)", null],
    ]);
    expect(needsYou(counts({ questions_open: 0, defects_draft: 0 }), "demo")).toEqual([]);
  });
});

describe("how often the gate counts are asked for", () => {
  it("often during a run, less when idle, slowly after an error, and never again once signed out", () => {
    expect(gatePollMs(counts({ running: true }), null)).toBe(5_000);
    expect(gatePollMs(counts(), null)).toBe(30_000);
    expect(gatePollMs(undefined, new Error("network"))).toBe(60_000);
    expect(gatePollMs(undefined, new ApiError(401, "unauthorized", "x"))).toBe(false);
    expect(gatePollMs(undefined, new ApiError(404, "not_found", "x"))).toBe(false);
    expect(gatePollMs(undefined, new ApiError(429, "rate_limited", "x"))).toBe(60_000);
  });

  it("knows which refusals mean the page is out of date, and words a failed fetch", () => {
    expect(isStale(new ApiError(409, "busy", "x"))).toBe(true);
    expect(isStale(new ApiError(409, "exported", "x"))).toBe(true);
    expect(isStale(new ApiError(422, "validation", "x"))).toBe(false);
    expect(errorWords(new TypeError("Failed to fetch"))).toMatch(/could not be reached/);
  });
});

describe("the Live View's gate text for the newest run", () => {
  const board = { questions: 15, defects: 19, plan: "waiting" as const };
  it("adds what is still open now", () => {
    expect(liveGateText("questions", board, counts({ questions_open: 3 }))).toBe("15 asked · 3 open");
    expect(liveGateText("defects", board, counts({ defects_draft: 2 }))).toBe("19 found · 2 to confirm");
    expect(liveGateText("plan", board, counts())).toBe("approved");
    expect(liveGateText("plan", board, counts({ plan: { ...COUNTS.plan, approved: false } }))).toBe("waiting for you");
  });

  it("keeps the recording's words for an older run", () => {
    expect(liveGateText("questions", board, null)).toBe("15 for you");
    expect(liveGateText("defects", { ...board, defects: 0 }, null)).toBe("none");
    expect(liveGateText("plan", { ...board, plan: "pending" }, null)).toBe("not yet");
  });
});
